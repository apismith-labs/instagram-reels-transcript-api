import dotenv from 'dotenv';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { BULK_EXIT_CODES, CONTROLLED_BUILD_NUMBER, DATASET_PAGE_LIMIT, EXIT_CODES, RestTransport, RunJournal, RunMetadataArchive, archiveRunMetadataBestEffort, createRunMetadataRecord, executeBulkInput, loadBulkResumeRecord, sanitize, validateBulkRunInput, validateRunChargeCap, writePrivateUnique } from './reliable-actor.mjs';

const DEFAULT_ACTOR_ID = 'apple_yang/instagram-transcripts-scraper';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const OUTPUT_FILE = path.join(ROOT, 'sample-output', 'generated', 'nodejs-native-bulk-response.json');
const USAGE = 'Usage: node examples/nodejs/native-bulk.mjs <URL> [URL ...] [--results-limit N] [--skip-pinned-posts true|false] [--include-shares-count true|false] | --resume <RUN_ID> <same URL> [URL ...] [options]';

export function parseArgs(argv) {
  if (argv.includes('--help') || argv.includes('-h')) return { help: true };
  let runId = null; let args = argv;
  if (args[0] === '--resume') { if (args.length < 3 || !args[1]) throw new TypeError(USAGE); runId = args[1]; args = args.slice(2); }
  const urls = []; const input = { resultsLimit: 12, skipPinnedPosts: false, includeSharesCount: false };
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === '--results-limit') input.resultsLimit = Number(args[++index]);
    else if (arg === '--skip-pinned-posts' || arg === '--include-shares-count') {
      const value = args[++index]; if (!['true', 'false'].includes(value)) throw new TypeError(`${arg} requires true or false`);
      input[arg === '--skip-pinned-posts' ? 'skipPinnedPosts' : 'includeSharesCount'] = value === 'true';
    } else if (arg.startsWith('-')) throw new TypeError(`Unknown option: ${arg}\n${USAGE}`);
    else urls.push(arg);
  }
  if (urls.length === 0) throw new TypeError(USAGE);
  return { help: false, runId, runInput: validateBulkRunInput({ bulkUrls: urls, ...input }) };
}

export async function main(argv = process.argv.slice(2), dependencies = {}) {
  const print = dependencies.print || console.log;
  const parsed = parseArgs(argv);
  if (parsed.help) { print(USAGE); return 0; }
  const { runId: resumeId, runInput } = parsed;
  const env = dependencies.env || process.env;
  (dependencies.loadEnv || (() => dotenv.config({ path: path.join(ROOT, '.env') })))();
  const token = env.APIFY_TOKEN; if (!token) throw new TypeError('APIFY_TOKEN is required.');
  const actorId = env.APIFY_ACTOR_ID || DEFAULT_ACTOR_ID;
  const journal = dependencies.journal || new RunJournal(path.join(ROOT, 'sample-output', 'generated', 'nodejs-run-journal.jsonl'));
  const prior = resumeId ? await (dependencies.loadResumeRecord || loadBulkResumeRecord)(journal, resumeId, actorId, runInput, env.APIFY_BUILD || CONTROLLED_BUILD_NUMBER) : null;
  const result = await (dependencies.executeBulkInput || executeBulkInput)({
    transport: dependencies.transport || new RestTransport(token), actorId, runInput, journal,
    runId: resumeId, datasetId: prior?.datasetId || null, rowId: prior?.rowId || null, resumeBuildRecord: prior,
    maxTotalChargeUsd: env.APIFY_MAX_TOTAL_CHARGE_USD, requireChargeCap: env.APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD === '1',
    build: env.APIFY_BUILD || CONTROLLED_BUILD_NUMBER, requireBuild: true, datasetPageLimit: DATASET_PAGE_LIMIT,
  });
  const outputFile = await (dependencies.writeOutput || writePrivateUnique)(dependencies.outputFile || OUTPUT_FILE, `${JSON.stringify(sanitize(result), null, 2)}\n`);

  if (result.runId && result.runMetadata && (Array.isArray(result.rawItems) || result.executionStatus === 'run_failed')) {
    try {
      let chargeCap = null;
      try { chargeCap = validateRunChargeCap(env.APIFY_MAX_TOTAL_CHARGE_USD, false); } catch { /* the runner already rejected invalid creation configuration */ }
      const latest = await journal.latest(result.runId);
      const metadata = createRunMetadataRecord({ apiRun: result.runMetadata, actorId, runId: result.runId,
        chargeCap, chargeCapRequired: env.APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD === '1',
        buildVerification: latest?.buildVerification || null, recoveredFromResume: Boolean(resumeId) });
      await archiveRunMetadataBestEffort(dependencies.metadataArchive || new RunMetadataArchive(path.join(ROOT, 'sample-output', 'generated', 'nodejs-run-metadata.jsonl')), metadata, (message) => console.error(message));
    } catch (error) { console.error(`Run metadata archive preparation failed: ${error.message || error}`); }
  }
  print(JSON.stringify({ runId: result.runId ?? null, datasetId: result.datasetId ?? null,
    executionStatus: result.executionStatus ?? result.status, bulkStatus: result.bulkStatus ?? 'unknown',
    datasetComplete: result.datasetComplete ?? false, counts: result.counts ?? null, extraResultCount: result.extraResults?.length ?? 0, outputFile }));
  if (result.executionStatus && result.executionStatus !== 'success' && result.bulkStatus === 'unknown') return EXIT_CODES[result.executionStatus] ?? EXIT_CODES.unknown;
  return BULK_EXIT_CODES[result.bulkStatus] ?? BULK_EXIT_CODES.unknown;
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : '';
if (import.meta.url === invokedPath) main().then((code) => { process.exitCode = code; }).catch((error) => { console.error(error.message || error); process.exitCode = 2; });
