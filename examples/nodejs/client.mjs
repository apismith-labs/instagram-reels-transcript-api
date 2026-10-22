// Reusable ESM API. Importing this module performs no credential, file, or network I/O.
import {
  CONTROLLED_BUILD_ID, CONTROLLED_BUILD_NUMBER, DATASET_PAGE_LIMIT, RestTransport,
  aggregateProfile, buildRunInput, executeBulkInput, executeInput, executeProfileInput,
  safeError, validateBuildSelection, validateBulkRunInput, validateProfileInput,
  validateRunChargeCap, validateVideoUrl,
} from './reliable-actor.mjs';

export const DEFAULT_ACTOR_ID = 'apple_yang/instagram-transcripts-scraper';

export class ClientConfigurationError extends TypeError {}
export class ClientProtocolError extends Error {
  constructor(message, result = null) { super(message); this.name = 'ClientProtocolError'; this.result = result; }
}
export class ClientTransportError extends Error {
  constructor(message, result = null) { super(message); this.name = 'ClientTransportError'; this.result = result; }
}
export class ClientCreationUnknownError extends ClientTransportError {
  constructor(message, result = null) { super(message, result); this.name = 'ClientCreationUnknownError'; }
}

const COMMON_OPTIONS = new Set(['token', 'actorId', 'build', 'maxTotalChargeUsd', 'requireChargeCap',
  'requestTimeoutMs', 'pollingTimeoutMs', 'datasetPageLimit', 'maxAttempts', 'transport', 'journal', 'sleepFn']);
function validateOptions(options, mode) {
  if (!options || typeof options !== 'object' || Array.isArray(options)) throw new ClientConfigurationError('options must be an object');
  const accepted = new Set(COMMON_OPTIONS);
  if (mode === 'native_bulk') for (const key of ['resultsLimit', 'skipPinnedPosts', 'includeSharesCount']) accepted.add(key);
  if (mode === 'profile') for (const key of ['resultsLimit', 'onlyPostsNewerThan', 'skipPinnedPosts', 'includeSharesCount']) accepted.add(key);
  const unexpected = Object.keys(options).find((key) => !accepted.has(key));
  if (unexpected) throw new ClientConfigurationError(`Unsupported ${mode} client option: ${unexpected}`);
}

class MemoryJournal {
  records = [];
  async append(record) { this.records.push({ ...record }); }
  async latest(runId) { return [...this.records].reverse().find((record) => record.runId === runId) || null; }
}

function positiveInteger(value, name, fallback) {
  const selected = value ?? fallback;
  if (!Number.isInteger(selected) || selected <= 0) throw new ClientConfigurationError(`${name} must be a positive integer`);
  return selected;
}
function positiveTimeout(value, name, fallback) {
  const selected = value ?? fallback;
  if (typeof selected !== 'number' || !Number.isFinite(selected) || selected <= 0) throw new ClientConfigurationError(`${name} must be a finite positive number of milliseconds`);
  return selected;
}
function prepare(options = {}) {
  if (!options || typeof options !== 'object' || Array.isArray(options)) throw new ClientConfigurationError('options must be an object');
  const token = options.token ?? process.env.APIFY_TOKEN;
  if (typeof token !== 'string' || !token.trim()) throw new ClientConfigurationError('APIFY_TOKEN is required; pass token or set it in the process environment');
  const actorId = options.actorId ?? process.env.APIFY_ACTOR_ID ?? DEFAULT_ACTOR_ID;
  if (typeof actorId !== 'string' || !actorId.trim() || actorId.trim().startsWith('/')) throw new ClientConfigurationError('actorId must be a non-empty Apify Actor ID or owner/name');
  let build; let maxTotalChargeUsd; let requireChargeCap;
  try {
    build = validateBuildSelection(options.build ?? process.env.APIFY_BUILD ?? CONTROLLED_BUILD_NUMBER, true);
    requireChargeCap = options.requireChargeCap ?? process.env.APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD === '1';
    if (typeof requireChargeCap !== 'boolean') throw new TypeError('requireChargeCap must be a boolean');
    maxTotalChargeUsd = options.maxTotalChargeUsd ?? process.env.APIFY_MAX_TOTAL_CHARGE_USD;
    validateRunChargeCap(maxTotalChargeUsd, requireChargeCap);
  } catch (error) { throw new ClientConfigurationError(error.message); }
  const requestTimeoutMs = positiveTimeout(options.requestTimeoutMs, 'requestTimeoutMs', 30_000);
  const pollingTimeoutMs = positiveTimeout(options.pollingTimeoutMs, 'pollingTimeoutMs', 900_000);
  const datasetPageLimit = positiveInteger(options.datasetPageLimit, 'datasetPageLimit', DATASET_PAGE_LIMIT);
  const maxAttempts = positiveInteger(options.maxAttempts, 'maxAttempts', 4);
  if (options.transport && typeof options.transport.request !== 'function') throw new ClientConfigurationError('transport must provide an async request(method, path, body, timeoutMs, query) function');
  if (options.journal && typeof options.journal.append !== 'function') throw new ClientConfigurationError('journal must provide an append(record) function');
  return { actorId: actorId.trim(), build, maxTotalChargeUsd, requireChargeCap, requestTimeoutMs, pollingTimeoutMs,
    datasetPageLimit, maxAttempts, transport: options.transport || new RestTransport(token), journal: options.journal || new MemoryJournal(),
    sleepFn: options.sleepFn };
}
async function buildEvidence(journal, runId) {
  if (!runId || typeof journal.latest !== 'function') return { buildNumber: null, buildId: null, buildVerification: 'unknown' };
  const record = await journal.latest(runId);
  return { buildNumber: record?.actualBuildNumber ?? null, buildId: record?.actualBuildId ?? null,
    buildVerification: record?.buildVerification ?? 'unknown' };
}
function runnerOptions(config, runInput, sourceUrl) {
  return { transport: config.transport, actorId: config.actorId, runInput, sourceUrl, journal: config.journal,
    deadlineMs: config.pollingTimeoutMs, requestTimeoutMs: config.requestTimeoutMs, maxAttempts: config.maxAttempts,
    maxTotalChargeUsd: config.maxTotalChargeUsd, requireChargeCap: config.requireChargeCap,
    build: config.build, requireBuild: true, datasetPageLimit: config.datasetPageLimit,
    ...(config.sleepFn ? { sleepFn: config.sleepFn } : {}) };
}
async function handleExecutionError(result, config) {
  const evidence = await buildEvidence(config.journal, result.runId);
  const enriched = { ...result, ...evidence };
  const executionStatus = result.executionStatus ?? result.status;
  if (executionStatus === 'creation_unknown') throw new ClientCreationUnknownError(`${safeError(result.error || 'Run creation outcome is unknown')}; do not retry the creation request blindly`, enriched);
  if (executionStatus === 'transport_error') {
    if (result.stage === 'build_mismatch' || evidence.buildVerification === 'mismatch') throw new ClientProtocolError(safeError(result.error || 'Build identity mismatch; Dataset was not accepted'), enriched);
    throw new ClientTransportError(safeError(result.error || 'Apify transport failed; reconcile the existing Run before retrying'), enriched);
  }
  return enriched;
}

/** Run one transcript request. Business statuses are returned; ambiguous creation throws a typed error. */
export async function getTranscript(url, options = {}) {
  validateOptions(options, 'single_url');
  let validUrl;
  try { validUrl = validateVideoUrl(url); } catch (error) { throw new ClientConfigurationError(error.message); }
  const config = prepare(options);
  const base = await executeInput(runnerOptions(config, buildRunInput(validUrl), validUrl));
  const result = await handleExecutionError(base, config);
  const items = Array.isArray(result.rawItems) ? result.rawItems : [];
  const item = items.find((candidate) => candidate && typeof candidate === 'object' && typeof candidate.text === 'string' && candidate.text.trim()) || null;
  const status = result.status;
  if (status === 'success' && !item) throw new ClientProtocolError('Runner reported transcript success without a non-empty text item', result);
  return { mode: 'single_url', url: validUrl, status, text: item?.text ?? null,
    segments: Array.isArray(item?.segments) ? item.segments : [], items, runId: result.runId ?? null,
    datasetId: result.datasetId ?? null, error: result.error || null, buildNumber: result.buildNumber,
    buildId: result.buildId, buildVerification: result.buildVerification, datasetComplete: result.datasetComplete ?? null,
    executionStatus: result.executionStatus ?? status };
}

/** Submit every URL in one Actor-native bulkUrls Run, never one Run per URL. */
export async function getTranscripts(urls, options = {}) {
  validateOptions(options, 'native_bulk');
  let runInput;
  try { runInput = validateBulkRunInput({ bulkUrls: urls, ...(options.resultsLimit == null ? {} : { resultsLimit: options.resultsLimit }),
    ...(options.skipPinnedPosts == null ? {} : { skipPinnedPosts: options.skipPinnedPosts }),
    ...(options.includeSharesCount == null ? {} : { includeSharesCount: options.includeSharesCount }) }); }
  catch (error) { throw new ClientConfigurationError(error.message); }
  const config = prepare(options);
  const base = await executeBulkInput(runnerOptions(config, runInput, `native_bulk:${runInput.bulkUrls.join(',')}`));
  const result = await handleExecutionError(base, config);
  const inputs = Array.isArray(result.inputs) ? result.inputs : [];
  return { mode: 'native_bulk', status: result.bulkStatus || 'unknown', bulkStatus: result.bulkStatus || 'unknown',
    urls: runInput.bulkUrls, results: inputs, extraResults: result.extraResults || [], counts: result.counts || {},
    runId: result.runId ?? null, datasetId: result.datasetId ?? null, error: result.error || null,
    buildNumber: result.buildNumber, buildId: result.buildId, buildVerification: result.buildVerification,
    datasetComplete: result.datasetComplete === true, rawItems: result.rawItems || [],
    executionStatus: result.executionStatus ?? result.status };
}

/** Collect Profile post metadata. Profile results do not require transcript text or segments. */
export async function getProfilePosts(usernames, options = {}) {
  validateOptions(options, 'profile');
  const profileOptions = Object.fromEntries(['resultsLimit', 'onlyPostsNewerThan', 'skipPinnedPosts', 'includeSharesCount']
    .filter((key) => Object.hasOwn(options, key)).map((key) => [key, options[key]]));
  let runInput;
  try { runInput = validateProfileInput(usernames, profileOptions); } // Input validation precedes credentials and POST.
  catch (error) { throw new ClientConfigurationError(error.message); }
  const config = prepare(options);
  const base = await executeProfileInput(runnerOptions(config, runInput, `profile:${runInput.usernames.join(',')}`));
  const result = await handleExecutionError(base, config);
  if (base.status === 'run_failed') return { ...aggregateProfile([], [], false, runInput.usernames), mode: 'profile', status: 'run_failed',
    runId: base.runId ?? null, datasetId: base.datasetId ?? null, error: base.error || 'Actor Run failed',
    buildNumber: result.buildNumber, buildId: result.buildId, buildVerification: result.buildVerification,
    runStatus: base.runMetadata?.status ?? null, datasetComplete: false, rawItems: base.rawItems || [] };
  return { mode: 'profile', status: result.status, posts: result.posts || [], usernames: runInput.usernames,
    counts: result.counts || {}, runId: result.runId ?? null, datasetId: result.datasetId ?? null,
    error: result.error || null, buildNumber: result.buildNumber, buildId: result.buildId,
    buildVerification: result.buildVerification, datasetComplete: result.datasetComplete === true,
    rawItems: result.rawItems || [], runStatus: result.runMetadata?.status ?? null };
}
