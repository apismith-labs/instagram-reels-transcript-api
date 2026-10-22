// Staged, injectable Apify REST runner. Importing this module performs no I/O.
import { chmod, mkdir, open, readFile } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

export const STATUSES = ['success', 'actor_error', 'empty', 'no_transcript', 'unknown', 'transport_error', 'run_failed', 'creation_unknown'];
export const EXIT_CODES = { success: 0, actor_error: 4, empty: 5, no_transcript: 6, unknown: 7, transport_error: 8, run_failed: 9, creation_unknown: 10 };
export const CONTROLLED_BUILD_NUMBER = '0.0.50';
export const CONTROLLED_BUILD_ID = 'aJLRmMdQapLQRT4sJ';
export function buildRunInput(videoUrl, sessionid) { return { videoUrl, ...(sessionid ? { sessionid } : {}) }; }
export const DATASET_PAGE_LIMIT = 100;
export const BULK_EXIT_CODES = { all_success: 0, partial_success: 11, all_failed: 12, unknown: 13 };
const REEL_URL = /^https:\/\/(?:www\.)?instagram\.com\/(?:reel|reels|p)\/[A-Za-z0-9_-]+\/?$/;
export function validateVideoUrl(value) {
  if (typeof value !== 'string' || !value || value.trim() !== value || !REEL_URL.test(value)) {
    throw new TypeError('URL must be a bare HTTPS Instagram Reel URL, not a Markdown link');
  }
  return value;
}
export function validateBulkRunInput(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new TypeError('Native Bulk input must be a JSON object');
  if (Object.hasOwn(input, 'videoUrl') || Object.hasOwn(input, 'usernames')) throw new TypeError('Native Bulk input must not include videoUrl or usernames');
  const allowedFields = new Set(['bulkUrls', 'includeSharesCount', 'resultsLimit', 'skipPinnedPosts']);
  const unexpected = Object.keys(input).find((key) => !allowedFields.has(key));
  if (unexpected) throw new TypeError(`Unsupported Native Bulk input field: ${unexpected}`);
  if (!Array.isArray(input.bulkUrls) || input.bulkUrls.length === 0) throw new TypeError('Native Bulk requires a non-empty bulkUrls array');
  if (Object.hasOwn(input, 'includeSharesCount') && typeof input.includeSharesCount !== 'boolean') throw new TypeError('includeSharesCount must be a boolean');
  if (Object.hasOwn(input, 'resultsLimit') && (!Number.isInteger(input.resultsLimit) || input.resultsLimit < 1)) throw new TypeError('resultsLimit must be a positive integer');
  if (Object.hasOwn(input, 'skipPinnedPosts') && typeof input.skipPinnedPosts !== 'boolean') throw new TypeError('skipPinnedPosts must be a boolean');
  const urls = input.bulkUrls.map((value, index) => {
    try { return validateVideoUrl(value); } catch (error) { throw new TypeError(`bulkUrls[${index}]: ${error.message}`); }
  });
  const keys = new Set(); const codes = new Set();
  for (const [index, value] of urls.entries()) {
    const parsed = new URL(value); const key = `https://instagram.com${parsed.pathname}`;
    const code = parsed.pathname.replace(/\/$/, '').split('/').at(-1);
    if (keys.has(key) || codes.has(code)) throw new TypeError(`bulkUrls[${index}] duplicates or ambiguously aliases another Reel input`);
    keys.add(key); codes.add(code);
  }
  return { ...structuredClone(input), bulkUrls: urls };
}
function bulkUrlKey(value) {
  if (typeof value !== 'string') return null;
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== 'https:' || !['instagram.com', 'www.instagram.com'].includes(parsed.hostname) || parsed.username || parsed.password || parsed.port || parsed.search || parsed.hash) return null;
    if (!/^\/(?:reel|reels|p)\/[A-Za-z0-9_-]+\/?$/.test(parsed.pathname)) return null;
    // Only www/non-www host variation is normalized; path and trailing slash remain exact.
    return `https://instagram.com${parsed.pathname}`;
  } catch { return null; }
}
function bulkItemStatus(item) {
  if (item?.errMsg != null && String(item.errMsg).trim()) return 'actor_error';
  if (typeof item?.text === 'string' && item.text.trim()) return 'success_transcript';
  if (item?.text == null || typeof item?.text === 'string') return 'no_transcript';
  return 'unknown';
}
export function attributeBulkItems(bulkUrls, items, { datasetComplete = true } = {}) {
  if (!Array.isArray(bulkUrls) || bulkUrls.length === 0) throw new TypeError('bulkUrls must be a non-empty array');
  if (!Array.isArray(items)) return { mode: 'native_bulk', bulkStatus: 'unknown', datasetComplete: false, inputs: bulkUrls.map((inputUrl) => ({ inputUrl, status: 'unknown', results: [] })), extraResults: [], counts: { success_transcript: 0, actor_error: 0, no_transcript: 0, missing_result: 0, duplicate_result: 0, unknown: bulkUrls.length } };
  const inputKeys = new Map(); const shortcodeIndices = new Map();
  bulkUrls.forEach((url, index) => {
    const key = bulkUrlKey(url); if (key) inputKeys.set(key, [...(inputKeys.get(key) || []), index]);
    const code = new URL(url).pathname.replace(/\/$/, '').split('/').at(-1);
    shortcodeIndices.set(code, [...(shortcodeIndices.get(code) || []), index]);
  });
  const mapped = bulkUrls.map(() => []); const extraResults = [];
  for (const item of items) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) { extraResults.push({ status: 'unknown', reason: 'dataset_item_not_object', result: item }); continue; }
    const itemUrl = item.url; const codeMatches = typeof item.code === 'string' ? (shortcodeIndices.get(item.code) || []) : [];
    let target = null; let reason = null;
    if (itemUrl != null) {
      const key = bulkUrlKey(itemUrl); const indices = key ? (inputKeys.get(key) || []) : [];
      if (!key) reason = 'invalid_output_url';
      else if (indices.length !== 1) reason = indices.length > 1 ? 'ambiguous_duplicate_input_url' : 'output_url_not_in_input';
      else {
        const parsed = new URL(itemUrl); const urlCode = parsed.pathname.replace(/\/$/, '').split('/').at(-1);
        if (typeof item.code === 'string' && item.code !== urlCode) reason = 'url_code_conflict';
        else if (codeMatches.length && (codeMatches.length !== 1 || codeMatches[0] !== indices[0])) reason = 'ambiguous_url_code_mapping';
        else target = indices[0];
      }
    } else if (typeof item.code === 'string') {
      if (codeMatches.length === 1) target = codeMatches[0]; else reason = 'missing_or_ambiguous_shortcode';
    } else reason = 'missing_mapping_identity';
    if (target == null) extraResults.push({ status: 'unknown', reason, result: item }); else mapped[target].push(item);
  }
  const inputs = bulkUrls.map((inputUrl, index) => {
    const results = mapped[index];
    if (results.length === 0) return { inputUrl, status: datasetComplete ? 'missing_result' : 'unknown', results: [] };
    if (results.length > 1) return { inputUrl, status: 'duplicate_result', results };
    return { inputUrl, status: bulkItemStatus(results[0]), results };
  });
  const counts = Object.fromEntries(['success_transcript', 'actor_error', 'no_transcript', 'missing_result', 'duplicate_result', 'unknown'].map((status) => [status, inputs.filter((row) => row.status === status).length]));
  const uncertain = !datasetComplete || extraResults.length > 0 || counts.missing_result > 0 || counts.duplicate_result > 0 || counts.unknown > 0 || inputs.some((row) => row.status === 'unknown');
  const successCount = counts.success_transcript;
  const definiteFailures = counts.actor_error + counts.no_transcript;
  const bulkStatus = uncertain ? 'unknown' : successCount === bulkUrls.length ? 'all_success' : successCount > 0 ? 'partial_success' : definiteFailures === bulkUrls.length ? 'all_failed' : 'unknown';
  return { mode: 'native_bulk', bulkStatus, datasetComplete, inputs, extraResults, counts };
}
export function validateRunChargeCap(value, required = false) {
  if (value == null || (typeof value === 'string' && !value.trim())) {
    if (required) throw new TypeError('APIFY_MAX_TOTAL_CHARGE_USD is required for capped test mode');
    return null;
  }
  if (typeof value === 'boolean' || (typeof value === 'string' && !/^(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim()))) {
    throw new TypeError('APIFY_MAX_TOTAL_CHARGE_USD must be a finite positive number');
  }
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount <= 0) throw new TypeError('APIFY_MAX_TOTAL_CHARGE_USD must be a finite positive number');
  return amount;
}
export function validateBuildSelection(value, required = false) {
  if (value == null || (typeof value === 'string' && !value.trim())) {
    if (required) throw new TypeError('APIFY_BUILD is required when APIFY_REQUIRE_BUILD=1');
    return null;
  }
  if (typeof value !== 'string') throw new TypeError('APIFY_BUILD must be a Build number');
  const build = value.trim();
  if (!/^\d+\.\d+\.\d+$/.test(build) || build.toLowerCase() === 'latest') {
    throw new TypeError('APIFY_BUILD must be an explicit numeric Build number, not a tag such as latest');
  }
  return build;
}
const TERMINAL = new Set(['SUCCEEDED', 'FAILED', 'TIMED-OUT', 'ABORTED']);

export class ApiError extends Error {
  constructor(message, { status = null, retryAfter = null, ambiguous = false } = {}) { super(message); Object.assign(this, { status, retryAfter, ambiguous }); }
}
export class RestTransport {
  constructor(token, { fetchImpl = fetch, baseUrl = 'https://api.apify.com/v2' } = {}) { this.token = token; this.fetchImpl = fetchImpl; this.baseUrl = baseUrl.replace(/\/$/, ''); }
  async request(method, endpoint, body, timeoutMs = 30_000, query = null) {
    const requestUrl = new URL(this.baseUrl + endpoint);
    if (query) for (const [key, value] of Object.entries(query)) requestUrl.searchParams.set(key, String(value));
    let response;
    try {
      response = await this.fetchImpl(requestUrl.toString(), { method, headers: { Authorization: `Bearer ${this.token}`, 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(timeoutMs) });
    } catch (error) { throw new ApiError(`Apify ${method} transport failure: ${error.name || 'Error'}`, { ambiguous: method === 'POST' }); }
    if (!response.ok) {
      const raw = response.headers.get('retry-after');
      const retryAfter = raw && Number.isFinite(Number(raw)) ? Number(raw) : raw && Number.isFinite(Date.parse(raw)) ? Math.max(0, (Date.parse(raw) - Date.now()) / 1000) : null;
      throw new ApiError(`Apify HTTP ${response.status}`, { status: response.status, retryAfter, ambiguous: method === 'POST' && response.status >= 500 });
    }
    if (response.status === 204) return {};
    try { return await response.json(); } catch { throw new ApiError('Apify returned invalid JSON', { ambiguous: method === 'POST' }); }
  }
}
export class RunJournal {
  constructor(file) { this.file = file; }
  async validate() { return withJournalLock(this.file, () => this.validateUnlocked()); }
  async validateUnlocked() { try { const rows = (await readFile(this.file, 'utf8')).split(/\r?\n/).filter(Boolean); for (const [index, row] of rows.entries()) { let item; try { item = JSON.parse(row); } catch { throw new Error(`Run journal is corrupt at record ${index + 1}; refusing to continue`); } if (!item || Array.isArray(item) || typeof item !== 'object') throw new Error(`Run journal record ${index + 1} is not an object; refusing to continue`); } } catch (error) { if (error.code !== 'ENOENT') throw error; } }
  async append(record) { return withJournalLock(this.file, async () => {
      await this.validateUnlocked(); await mkdir(path.dirname(this.file), { recursive: true });
      const handle = await open(this.file, 'a', 0o600);
      try { try { await chmod(this.file, 0o600); } catch (error) { if (!['EPERM', 'ENOSYS', 'EOPNOTSUPP'].includes(error.code)) throw error; } await handle.writeFile(`${JSON.stringify(record)}\n`); await handle.sync(); } finally { await handle.close(); }
    }); }
  async latest(runId) { return withJournalLock(this.file, async () => { try { const rows = (await readFile(this.file, 'utf8')).split(/\r?\n/).filter(Boolean); let found; for (const [index, row] of rows.entries()) { let item; try { item = JSON.parse(row); } catch { throw new Error(`Run journal is corrupt at record ${index + 1}; refusing resume`); } if (!item || Array.isArray(item) || typeof item !== 'object') throw new Error(`Run journal record ${index + 1} is not an object; refusing resume`); if (item.runId === runId) found = item; } return found || null; } catch (e) { if (e.code === 'ENOENT') return null; throw e; } }); }
}
const journalTails = new Map();
async function withJournalLock(file, operationFn) {
  const key = path.resolve(file); const previous = journalTails.get(key) || Promise.resolve();
  const operation = previous.catch(() => {}).then(operationFn); journalTails.set(key, operation);
  try { return await operation; } finally { if (journalTails.get(key) === operation) journalTails.delete(key); }
}
export async function writePrivate(file, text) { await mkdir(path.dirname(file), { recursive: true }); const handle = await open(file, 'w', 0o600); try { try { await chmod(file, 0o600); } catch (error) { if (!['EPERM', 'ENOSYS', 'EOPNOTSUPP'].includes(error.code)) throw error; } await handle.writeFile(text); await handle.sync(); } finally { await handle.close(); } }
export async function writePrivateUnique(file, text, { uuid = randomUUID } = {}) {
  await mkdir(path.dirname(file), { recursive: true }); const extension = path.extname(file); const stem = path.basename(file, extension);
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const candidate = path.join(path.dirname(file), `${stem}-${uuid()}${extension}`);
    try { const handle = await open(candidate, 'wx', 0o600); try { await handle.writeFile(text); await handle.sync(); } finally { await handle.close(); } return candidate; }
    catch (error) { if (error.code !== 'EEXIST') throw error; }
  }
  throw new Error(`Could not reserve a unique output path for ${path.basename(file)}`);
}
export async function loadResumeRecord(journal, runId, actorId, expectedBuild = null) {
  const record = await journal.latest(runId);
  if (!record) throw new Error(`No journal record found for Run ID ${runId}; refusing resume`);
  if (record.runId !== runId || record.actorId !== actorId) throw new Error('Run journal Actor/Run ID does not match the requested resume; refusing resume');
  if (typeof record.sourceUrl !== 'string' || !record.sourceUrl.trim() || typeof record.rowId !== 'string') throw new Error('Run journal is missing input association fields; refusing resume');
  if (record.buildVerification === 'mismatch') throw new Error('Run journal records a Build mismatch; refusing to process its Dataset');
  if (record.buildVerification === 'verified') {
    if (typeof record.actualBuildNumber !== 'string' || typeof record.actualBuildId !== 'string') throw new Error('Verified Build identity is incomplete in the journal; refusing resume');
    if (record.actualBuildNumber === CONTROLLED_BUILD_NUMBER && record.actualBuildId !== CONTROLLED_BUILD_ID) throw new Error('Verified Build number/ID pair is inconsistent in the journal; refusing resume');
    if (expectedBuild && record.actualBuildNumber !== expectedBuild) throw new Error('Journal Build does not match the requested resume Build; refusing resume');
  }
  if (expectedBuild && record.expectedBuildNumber && record.expectedBuildNumber !== expectedBuild) throw new Error('Journal expected Build does not match the requested resume Build; refusing resume');
  return record;
}
function redactText(value) {
  return String(value).replace(/(bearer\s+)[A-Za-z0-9._~+/-]+=*/gi, '$1[REDACTED]')
    .replace(/(sessionid|token|authorization|cookie|password|api[_-]?key)(\s*[:=]\s*["']?)[^\s,;&"']+/gi, '$1$2[REDACTED]');
}
export function safeError(error) { return redactText(String(error?.message || error).replace(/[\r\n]/g, ' ')).slice(0, 300); }
export function classifyItems(items) {
  if (!Array.isArray(items)) return ['unknown', 'Dataset response is not an item list'];
  if (!items.length) return ['empty', 'Dataset contains no items'];
  if (!items.every((x) => x && typeof x === 'object' && !Array.isArray(x))) return ['unknown', 'Dataset contains a non-object item'];
  const errors = items.map((x) => x.errMsg).filter((x) => x != null && String(x).trim()).map(String);
  if (errors.length) return ['actor_error', redactText(errors.join('; ')).slice(0, 500)];
  const texts = items.map((x) => x.text);
  if (texts.some((x) => typeof x === 'string' && x.trim())) return ['success', ''];
  if (texts.some((x) => x === null) || texts.some((x) => typeof x === 'string')) return ['no_transcript', 'Transcript text is null or empty'];
  if (items.some((x) => !Object.hasOwn(x, 'text'))) return ['no_transcript', 'Transcript text is absent'];
  return ['unknown', 'Transcript text has an unsupported type'];
}
function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }
async function getWithRetry(transport, endpoint, deadline, maxAttempts, sleepFn, query = null) {
  let last;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (Date.now() >= deadline) throw new ApiError('Overall run deadline exceeded');
    try { return await transport.request('GET', endpoint, undefined, Math.max(1, Math.min(30_000, deadline - Date.now())), query); } catch (error) {
      last = error;
      const retryable = error.status === 429 || (error.status >= 500 && error.status < 600) || error.status == null;
      const delay = error.retryAfter ?? Math.min(2 ** attempt, 8);
      if (!retryable || attempt + 1 >= maxAttempts || Date.now() + delay * 1000 >= deadline) throw error;
      await sleepFn(delay * 1000);
    }
  }
  throw last;
}
function extractRunMetadata(run) {
  const rawCounts = run?.chargedEventCounts && typeof run.chargedEventCounts === 'object' && !Array.isArray(run.chargedEventCounts) ? run.chargedEventCounts : null;
  const counts = rawCounts ? Object.fromEntries(Object.entries(rawCounts).filter(([key, value]) => !/(token|session|cookie|auth|secret)/i.test(key) && typeof value === 'number' && Number.isFinite(value))) : null;
  const unparsedEventFields = rawCounts ? Object.keys(rawCounts).filter((key) => !/(token|session|cookie|auth|secret)/i.test(key) && !(typeof rawCounts[key] === 'number' && Number.isFinite(rawCounts[key]))) : [];
  return { status: typeof run?.status === 'string' ? run.status : null,
    buildNumber: typeof run?.buildNumber === 'string' ? run.buildNumber : null,
    buildId: typeof run?.buildId === 'string' ? run.buildId : null,
    defaultDatasetId: typeof run?.defaultDatasetId === 'string' ? run.defaultDatasetId : null,
    usageTotalUsd: typeof run?.usageTotalUsd === 'number' && Number.isFinite(run.usageTotalUsd) ? run.usageTotalUsd : null,
    chargedEventCounts: counts,
    unparsedEventFields };
}
export function createRunMetadataRecord({ apiRun, actorId, runId, chargeCap = null, chargeCapRequired = false, buildVerification = null, recoveredFromResume = false, recordedAt = new Date().toISOString() }) {
  const api = extractRunMetadata(apiRun);
  return { schemaVersion: 1, client: 'nodejs', runId, actorId, ...api,
    chargeCap: { configuredValue: chargeCap, required: Boolean(chargeCapRequired) },
    buildVerification, recordedAt, recoveredFromResume: Boolean(recoveredFromResume),
    processExitCode: null, processExitCodeUnavailableReason: 'not captured by the Run runner',
    provenance: { runId: 'api', actorId: 'local_request', status: 'api', buildNumber: 'api', buildId: 'api', defaultDatasetId: 'api', usageTotalUsd: 'api', chargedEventCounts: 'api', unparsedEventFields: 'api_shape_review', chargeCap: 'local_config', buildVerification: 'local_derived', recordedAt: 'local_derived', processExitCode: 'unavailable' } };
}
export class RunMetadataArchive {
  constructor(file) { this.file = file; }
  async append(record) {
    const allowed = createRunMetadataRecord({ apiRun: record, actorId: record.actorId, runId: record.runId, chargeCap: record.chargeCap?.configuredValue ?? null, chargeCapRequired: record.chargeCap?.required, buildVerification: record.buildVerification, recoveredFromResume: record.recoveredFromResume, recordedAt: record.recordedAt });
    allowed.unparsedEventFields = Array.isArray(record.unparsedEventFields) ? record.unparsedEventFields.filter((field) => typeof field === 'string' && !/(token|session|cookie|auth|secret)/i.test(field)) : allowed.unparsedEventFields;
    await mkdir(path.dirname(this.file), { recursive: true });
    const handle = await open(this.file, 'a', 0o600);
    try { await chmod(this.file, 0o600); await handle.writeFile(`${JSON.stringify(allowed)}\n`); await handle.sync(); } finally { await handle.close(); }
  }
}
export async function archiveRunMetadataBestEffort(archive, record, warn = () => {}) {
  try { await archive.append(record); return true; } catch (error) { warn(`Run metadata archive failed: ${safeError(error)}`); return false; }
}
export async function executeInput({ transport, actorId, runInput, sourceUrl, inputContext = null, datasetPageLimit = null, journal, deadlineMs = 900_000, maxAttempts = 4, sleepFn = sleep, runId: resumeRunId = null, datasetId: resumeDatasetId = null, rowId: inputRowId = null, maxTotalChargeUsd = null, requireChargeCap = false, build = null, requireBuild = false, resumeBuildRecord = null }) {
  const deadline = Date.now() + deadlineMs;
  const rowId = inputRowId || randomUUID();
  const record = { rowId, sourceUrl, actorId, runId: resumeRunId, datasetId: resumeDatasetId, ...(inputContext ? { inputContext } : {}), stage: 'start', status: 'unknown', updatedAt: new Date().toISOString() };
  let persistenceError = null;
  const save = async (stage, status = 'unknown', error) => { Object.assign(record, { stage, status, updatedAt: new Date().toISOString() }); if (error) record.error = safeError(error); else delete record.error; try { await journal.append({ ...record }); return true; } catch (failure) { persistenceError = safeError(failure); return false; } };
  const persistenceFailure = () => ({ rowId, sourceUrl, status: 'transport_error', runId, datasetId, error: `Run journal persistence failed; do not retry creation. ${persistenceError}`, recoveryPersisted: false });
  let runId = resumeRunId, datasetId = resumeDatasetId;
  let requestedBuild = null;
  let expectedBuild = null;
  let buildVerified = false;
  let observedBuildNumber = null;
  let observedBuildId = null;
  let finalRun = null;
  try {
    requestedBuild = validateBuildSelection(build, requireBuild && !resumeRunId);
    if (resumeRunId) {
      if (requireBuild) expectedBuild = requestedBuild || CONTROLLED_BUILD_NUMBER;
      else if (requestedBuild) expectedBuild = requestedBuild;
      else if (resumeBuildRecord?.buildVerification === 'verified') expectedBuild = resumeBuildRecord.actualBuildNumber;
      else if (typeof resumeBuildRecord?.expectedBuildNumber === 'string') expectedBuild = resumeBuildRecord.expectedBuildNumber;
      else if (typeof resumeBuildRecord?.requestedBuild === 'string') expectedBuild = resumeBuildRecord.requestedBuild;
      if (resumeBuildRecord?.buildVerification === 'verified') {
        if (expectedBuild && expectedBuild !== resumeBuildRecord.actualBuildNumber) throw new Error('Journal Build does not match the requested resume Build');
        if (resumeBuildRecord.actualBuildNumber === CONTROLLED_BUILD_NUMBER && resumeBuildRecord.actualBuildId !== CONTROLLED_BUILD_ID) throw new Error('Journal Build number/ID pair is inconsistent');
        observedBuildNumber = resumeBuildRecord.actualBuildNumber;
        observedBuildId = resumeBuildRecord.actualBuildId;
        buildVerified = true;
      }
    } else if (requestedBuild) expectedBuild = requestedBuild;
  } catch (error) {
    return { rowId, sourceUrl, status: 'transport_error', runId: resumeRunId, datasetId: resumeDatasetId, error: safeError(error) };
  }
  if (expectedBuild) Object.assign(record, { requestedBuild: requestedBuild || null, expectedBuildNumber: expectedBuild,
    ...(observedBuildNumber ? { actualBuildNumber: observedBuildNumber, actualBuildId: observedBuildId, buildVerification: 'verified' } : {}) });
  else if (resumeRunId && resumeBuildRecord && !resumeBuildRecord.buildVerification) record.buildVerification = 'legacy_unverified';
  if (!runId) {
    let chargeCap;
    try { chargeCap = validateRunChargeCap(maxTotalChargeUsd, requireChargeCap); }
    catch (error) { return { rowId, sourceUrl, status: 'transport_error', runId: null, error: safeError(error) }; }
    if (!(await save('creating'))) return persistenceFailure();
    const endpoint = `/acts/${actorId.replaceAll('/', '~')}/runs`;
    let created;
    if (Date.now() >= deadline) { const persisted = await save('create_failed', 'transport_error', 'Overall run deadline exceeded before POST'); return { rowId, sourceUrl, status: 'transport_error', runId: null, error: 'Overall run deadline exceeded before POST', ...(persisted ? {} : { recoveryPersisted: false }) }; }
    const runOptions = { restartOnError: false, ...(chargeCap == null ? {} : { maxTotalChargeUsd: chargeCap }), ...(requestedBuild ? { build: requestedBuild } : {}) };
    try { created = await transport.request('POST', endpoint, runInput, Math.max(1, Math.min(30_000, deadline - Date.now())), runOptions); }
    catch (error) {
      let status = error.ambiguous || error.status == null ? 'creation_unknown' : 'transport_error';
      if (error.status === 429) { status = 'creation_unknown'; error = new ApiError('HTTP 429 on Run creation; acceptance semantics are unverified; POST was not retried', { status: 429 }); }
      const persisted = await save(status === 'creation_unknown' ? status : 'create_failed', status, error);
      return { rowId, sourceUrl, status, runId: null, error: safeError(error), ...(persisted ? {} : { recoveryPersisted: false }) };
    }
    created = created && typeof created === 'object' && !Array.isArray(created) ? (created.data || created) : null;
    finalRun = created;
    runId = created?.id; datasetId = created?.defaultDatasetId;
    if (!runId) { const persisted = await save('creation_unknown', 'creation_unknown', 'POST response did not include a run ID'); return { rowId, sourceUrl, status: 'creation_unknown', runId: null, error: 'POST response did not include a run ID', ...(persisted ? {} : { recoveryPersisted: false }) }; }
    Object.assign(record, { runId, datasetId, ...(expectedBuild ? { requestedBuild, expectedBuildNumber: expectedBuild } : {}) });
    if (expectedBuild) {
      observedBuildNumber = typeof created.buildNumber === 'string' ? created.buildNumber : null;
      observedBuildId = typeof created.buildId === 'string' ? created.buildId : null;
      const hasAnyBuildIdentity = observedBuildNumber != null || observedBuildId != null;
      if (hasAnyBuildIdentity && ((observedBuildNumber && observedBuildNumber !== expectedBuild) || (observedBuildId && expectedBuild === CONTROLLED_BUILD_NUMBER && observedBuildId !== CONTROLLED_BUILD_ID))) {
        Object.assign(record, { actualBuildNumber: observedBuildNumber, actualBuildId: observedBuildId, buildVerification: 'mismatch' });
        const persisted = await save('build_mismatch', 'transport_error', 'Created Run Build identity does not match the requested Build');
        return { rowId, sourceUrl, runId, datasetId, status: 'transport_error', error: 'Created Run Build identity does not match the requested Build', runMetadata: extractRunMetadata(created), ...(persisted ? {} : { recoveryPersisted: false }) };
      }
      if (observedBuildNumber === expectedBuild && observedBuildId) {
        if (expectedBuild === CONTROLLED_BUILD_NUMBER && observedBuildId !== CONTROLLED_BUILD_ID) {
          Object.assign(record, { actualBuildNumber: observedBuildNumber, actualBuildId: observedBuildId, buildVerification: 'mismatch' });
          const persisted = await save('build_mismatch', 'transport_error', 'Created Run Build ID does not match the approved Build');
          return { rowId, sourceUrl, runId, datasetId, status: 'transport_error', error: 'Created Run Build ID does not match the approved Build', runMetadata: extractRunMetadata(created), ...(persisted ? {} : { recoveryPersisted: false }) };
        }
        buildVerified = true;
        Object.assign(record, { actualBuildNumber: observedBuildNumber, actualBuildId: observedBuildId, buildVerification: 'verified' });
      }
    }
    if (!(await save('run_created'))) return persistenceFailure();
  } else { Object.assign(record, { runId, datasetId }); if (!(await save('resuming'))) return persistenceFailure(); }
  try {
    for (;;) {
      if (Date.now() >= deadline) throw new ApiError('Overall run deadline exceeded');
      const raw = await getWithRetry(transport, `/actor-runs/${runId}`, deadline, maxAttempts, sleepFn);
      const run = raw.data || raw;
      finalRun = run;
      if (run.defaultDatasetId) {
        if (datasetId && datasetId !== run.defaultDatasetId) throw new ApiError('Journal Dataset ID does not match the Run response');
        datasetId = datasetId || run.defaultDatasetId;
        record.datasetId = datasetId;
      }
      if (expectedBuild) {
        const runBuildNumber = typeof run.buildNumber === 'string' ? run.buildNumber : null;
        const runBuildId = typeof run.buildId === 'string' ? run.buildId : null;
        if ((observedBuildNumber && runBuildNumber && observedBuildNumber !== runBuildNumber) ||
            (observedBuildId && runBuildId && observedBuildId !== runBuildId) ||
            (runBuildNumber && runBuildNumber !== expectedBuild) ||
            (runBuildId && expectedBuild === CONTROLLED_BUILD_NUMBER && runBuildId !== CONTROLLED_BUILD_ID)) {
          Object.assign(record, { actualBuildNumber: runBuildNumber || observedBuildNumber, actualBuildId: runBuildId || observedBuildId, buildVerification: 'mismatch' });
          const persisted = await save('build_mismatch', 'transport_error', 'Run Build identity does not match the requested Build');
          return { rowId, sourceUrl, runId, datasetId, status: 'transport_error', error: 'Run Build identity does not match the requested Build', runMetadata: extractRunMetadata(run), ...(persisted ? {} : { recoveryPersisted: false }) };
        }
        observedBuildNumber = runBuildNumber || observedBuildNumber;
        observedBuildId = runBuildId || observedBuildId;
        if (observedBuildNumber === expectedBuild && observedBuildId && (expectedBuild !== CONTROLLED_BUILD_NUMBER || observedBuildId === CONTROLLED_BUILD_ID)) {
          buildVerified = true;
          Object.assign(record, { requestedBuild: requestedBuild || null, expectedBuildNumber: expectedBuild, actualBuildNumber: observedBuildNumber, actualBuildId: observedBuildId, buildVerification: 'verified' });
          if (record.stage !== 'build_verified' && !(await save('build_verified'))) return persistenceFailure();
        } else if (!buildVerified && (TERMINAL.has(run.status) || runBuildNumber || runBuildId)) {
          Object.assign(record, { actualBuildNumber: observedBuildNumber, actualBuildId: observedBuildId, buildVerification: 'unverified' });
          const persisted = await save('build_unverified', 'transport_error', 'Run response did not provide sufficient Build identity');
          return { rowId, sourceUrl, runId, datasetId, status: 'transport_error', error: 'Run response did not provide sufficient Build identity', runMetadata: extractRunMetadata(run), ...(persisted ? {} : { recoveryPersisted: false }) };
        }
      }
      if (TERMINAL.has(run.status)) {
        if (run.status !== 'SUCCEEDED') { if (!(await save('run_finished', 'run_failed', `Run ended with ${run.status}`))) return persistenceFailure(); return { rowId, sourceUrl, runId, datasetId, status: 'run_failed', error: `Run ended with ${run.status}`, runMetadata: extractRunMetadata(run) }; }
        if (datasetId && run.defaultDatasetId && datasetId !== run.defaultDatasetId) throw new ApiError('Journal Dataset ID does not match the Run response');
        datasetId = datasetId || run.defaultDatasetId; record.datasetId = datasetId; if (!(await save('run_finished'))) return persistenceFailure(); break;
      }
      await sleepFn(Math.min(2_000, Math.max(0, deadline - Date.now())));
    }
    if (!datasetId) { if (!(await save('recoverable', 'transport_error', 'Run succeeded without a dataset ID'))) return persistenceFailure(); return { rowId, sourceUrl, runId, status: 'transport_error', error: 'Run succeeded without a dataset ID' }; }
    const datasetQuery = datasetPageLimit ? { limit: datasetPageLimit, offset: 0 } : null;
    let items = await getWithRetry(transport, `/datasets/${datasetId}/items`, deadline, maxAttempts, sleepFn, datasetQuery);
    // Dataset visibility can lag terminal Run status; confirm empty reads on the same Dataset.
    for (let emptyAttempt = 0; emptyAttempt < 2; emptyAttempt += 1) {
      const waitMs = (emptyAttempt + 1) * 1_000;
      if (!Array.isArray(items) || items.length > 0 || Date.now() + waitMs >= deadline) break;
      await sleepFn(waitMs);
      items = await getWithRetry(transport, `/datasets/${datasetId}/items`, deadline, maxAttempts, sleepFn, datasetQuery);
    }
    const [status, message] = classifyItems(items); if (!(await save('complete', status, message || null))) return persistenceFailure();
    return { rowId, sourceUrl, runId, datasetId, status, error: message, rawItems: items,
      datasetComplete: datasetPageLimit ? Array.isArray(items) && items.length < datasetPageLimit : null,
      datasetReadLimit: datasetPageLimit, runMetadata: extractRunMetadata(finalRun) };
  } catch (error) {
    if (persistenceError) return persistenceFailure();
    if (expectedBuild && !buildVerified) {
      Object.assign(record, { actualBuildNumber: observedBuildNumber, actualBuildId: observedBuildId, buildVerification: 'unverified' });
      if (!(await save('build_unverified', 'transport_error', error))) return persistenceFailure();
      return { rowId, sourceUrl, runId, datasetId, status: 'transport_error', error: safeError(error), runMetadata: finalRun ? extractRunMetadata(finalRun) : null };
    }
    if (!(await save('recoverable', 'transport_error', error))) return persistenceFailure();
    return { rowId, sourceUrl, runId, datasetId, status: 'transport_error', error: safeError(error), runMetadata: finalRun ? extractRunMetadata(finalRun) : null };
  }
}
export async function loadBulkResumeRecord(journal, runId, actorId, bulkInput, expectedBuild = null) {
  const input = validateBulkRunInput(bulkInput);
  const prior = await loadResumeRecord(journal, runId, actorId, expectedBuild);
  if (prior.inputContext?.mode !== 'native_bulk' || JSON.stringify(prior.inputContext.input) !== JSON.stringify(input)) {
    throw new Error('Run journal Native Bulk input does not match the current fixture; refusing resume');
  }
  return prior;
}
export async function executeBulkInput({ transport, actorId, runInput, journal, datasetPageLimit = DATASET_PAGE_LIMIT, runId = null, datasetId = null, rowId = null, resumeBuildRecord = null, ...options }) {
  const input = validateBulkRunInput(runInput);
  const base = await executeInput({ transport, actorId, runInput: input, sourceUrl: 'native_bulk',
    inputContext: { mode: 'native_bulk', input }, datasetPageLimit, journal, runId, datasetId, rowId, resumeBuildRecord, ...options });
  if (!Array.isArray(base.rawItems)) {
    const attribution = attributeBulkItems(input.bulkUrls, null, { datasetComplete: false });
    return { ...base, executionStatus: base.status, bulkStatus: 'unknown', ...attribution };
  }
  const attribution = attributeBulkItems(input.bulkUrls, base.rawItems, { datasetComplete: base.datasetComplete === true });
  return { ...base, executionStatus: base.status, status: attribution.bulkStatus, ...attribution };
}
export function summarize(results) {
  const counts = Object.fromEntries(STATUSES.map((s) => [s, 0]));
  for (const result of results) counts[Object.hasOwn(counts, result.status) ? result.status : 'unknown'] += 1;
  counts.processed = STATUSES.reduce((sum, key) => sum + counts[key], 0);
  counts.failed = counts.processed - counts.success;
  return counts;
}
export function sanitize(value) {
  const blocked = new Set(['token', 'sessionid', 'cookie', 'authorization', 'password', 'secret', 'accesstoken', 'refreshtoken', 'apikey']);
  if (Array.isArray(value)) return value.map(sanitize);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).filter(([key]) => !blocked.has(key.toLowerCase().replaceAll('_', '').replaceAll('-', ''))).map(([key, v]) => [key, sanitize(v)]));
  if (typeof value === 'string') return redactText(value);
  return value;
}
