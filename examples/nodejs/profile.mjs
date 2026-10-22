import dotenv from 'dotenv';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { CONTROLLED_BUILD_NUMBER, DATASET_PAGE_LIMIT, RestTransport, RunJournal, executeProfileInput, sanitize, validateBuildSelection, validateProfileInput, validateRunChargeCap, writePrivateUnique } from './reliable-actor.mjs';

const DEFAULT_ACTOR_ID = 'apple_yang/instagram-transcripts-scraper';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const OUTPUT_FILE = path.join(ROOT, 'sample-output', 'generated', 'nodejs-profile-response.json');
const USAGE = 'Usage: node examples/nodejs/profile.mjs <username> [username ...] [--results-limit N] [--only-posts-newer-than DATE_OR_PERIOD] [--skip-pinned-posts] [--include-shares-count]';
const EXIT_CODES = { success: 0, actor_error: 4, empty: 5, unknown: 7, transport_error: 8, run_failed: 9, creation_unknown: 10 };

export function profilePersistedResult(result, journalRecord = null, requestedUsernames = [], journalReadError = null) {
  const { executionStatus: _transcriptExecutionStatus, ...profileResult } = result;
  const persisted = {
    ...profileResult,
    runStatus: result.runStatus ?? result.runMetadata?.status ?? null,
    buildNumber: journalRecord?.actualBuildNumber ?? result.buildNumber ?? result.runMetadata?.buildNumber ?? null,
    buildId: journalRecord?.actualBuildId ?? result.buildId ?? result.runMetadata?.buildId ?? null,
    buildVerification: journalRecord?.buildVerification ?? result.buildVerification ?? 'unknown',
    usernames: result.usernames ?? requestedUsernames,
  };
  if (journalReadError) persisted.diagnostics = { ...(profileResult.diagnostics || {}), journalReadError };
  return persisted;
}

function requiredOptionValue(argv, index, option) {
  const value = argv[index + 1];
  if (typeof value !== 'string' || value.length === 0 || value.startsWith('--')) {
    throw new TypeError(`${option} requires a non-empty value`);
  }
  return value;
}

function rejectBooleanFlagValue(argv, index, option) {
  if (['true', 'false', '1', '0'].includes(argv[index + 1])) {
    throw new TypeError(`${option} is a flag and does not accept a value; omit ${argv[index + 1]}`);
  }
}

export function parseArgs(argv) {
  if (argv.includes('--help') || argv.includes('-h')) return { help: true };
  const usernames = []; const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--results-limit') {
      if (Object.hasOwn(options, 'resultsLimit')) throw new TypeError('--results-limit may be supplied once');
      options.resultsLimit = Number(requiredOptionValue(argv, index, arg)); index += 1;
    }
    else if (arg === '--only-posts-newer-than') {
      if (Object.hasOwn(options, 'onlyPostsNewerThan')) throw new TypeError('--only-posts-newer-than may be supplied once');
      options.onlyPostsNewerThan = requiredOptionValue(argv, index, arg); index += 1;
    }
    else if (arg === '--resume') throw new TypeError('Profile Resume is not supported');
    else if (arg === '--skip-pinned-posts') {
      rejectBooleanFlagValue(argv, index, arg);
      options.skipPinnedPosts = true;
    }
    else if (arg === '--include-shares-count') {
      rejectBooleanFlagValue(argv, index, arg);
      options.includeSharesCount = true;
    }
    else if (arg.startsWith('-')) throw new TypeError(`Unknown option: ${arg}\n${USAGE}`);
    else usernames.push(arg);
  }
  return { help: false, runInput: validateProfileInput(usernames, options) };
}

export async function main(argv = process.argv.slice(2), dependencies = {}) {
  const print = dependencies.print || console.log;
  let parsed;
  try { parsed = parseArgs(argv); }
  catch (error) { (dependencies.error || console.error)(error.message || String(error)); return 2; }
  if (parsed.help) { print(USAGE); return 0; }
  const env = dependencies.env || process.env;
  (dependencies.loadEnv || (() => dotenv.config({ path: path.join(ROOT, '.env') })))();
  const token = env.APIFY_TOKEN;
  if (!token) throw new TypeError('APIFY_TOKEN is required.');
  const actorId = env.APIFY_ACTOR_ID || DEFAULT_ACTOR_ID;
  const build = validateBuildSelection(env.APIFY_BUILD || CONTROLLED_BUILD_NUMBER, true);
  const requireChargeCap = env.APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD === '1';
  const chargeCap = validateRunChargeCap(env.APIFY_MAX_TOTAL_CHARGE_USD, requireChargeCap);
  const journal = dependencies.journal || new RunJournal(path.join(ROOT, 'sample-output', 'generated', 'nodejs-run-journal.jsonl'));
  const transport = dependencies.transport || new RestTransport(token);
  const result = await (dependencies.executeProfileInput || executeProfileInput)({
    transport, actorId, runInput: parsed.runInput, journal,
    maxTotalChargeUsd: chargeCap, requireChargeCap, build, requireBuild: true, datasetPageLimit: DATASET_PAGE_LIMIT,
  });
  let latest = null; let journalReadError = null;
  try { latest = result.runId && typeof journal.latest === 'function' ? await journal.latest(result.runId) : null; }
  catch (error) { journalReadError = error.message || String(error); }
  let outputFile;
  try { outputFile = await (dependencies.writeOutput || writePrivateUnique)(dependencies.outputFile || OUTPUT_FILE, `${JSON.stringify(sanitize(profilePersistedResult(result, latest, parsed.runInput.usernames, journalReadError)), null, 2)}\n`); }
  catch (error) { throw new Error(`Profile output could not be saved. Preserve Run ID ${result.runId || '(unknown)'} and reconcile before retrying. ${error.message || error}`); }
  const status = result.status || 'unknown';
  print(JSON.stringify({ mode: 'profile', status, runStatus: result.runStatus ?? result.runMetadata?.status ?? null,
    runId: result.runId ?? null, datasetId: result.datasetId ?? null, buildNumber: latest?.actualBuildNumber ?? null,
    buildId: latest?.actualBuildId ?? null, buildVerification: latest?.buildVerification ?? 'unknown',
    usernames: parsed.runInput.usernames, datasetComplete: result.datasetComplete === true,
    postCount: result.posts?.length ?? 0, posts: (result.posts || []).map(({ url, type, ownerUsername, timestamp, status: postStatus }) => ({ url, type, ownerUsername, timestamp, status: postStatus })),
    error: result.error || null, outputFile }));
  return EXIT_CODES[status] ?? EXIT_CODES.unknown;
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : '';
if (import.meta.url === invokedPath) main().then((code) => { process.exitCode = code; }).catch((error) => { console.error(error.message || error); process.exitCode = 2; });
