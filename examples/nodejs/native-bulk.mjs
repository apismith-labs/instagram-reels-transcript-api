import dotenv from 'dotenv';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { BULK_EXIT_CODES, CONTROLLED_BUILD_NUMBER, DATASET_PAGE_LIMIT, EXIT_CODES, RestTransport, RunJournal, RunMetadataArchive, archiveRunMetadataBestEffort, createRunMetadataRecord, executeBulkInput, loadBulkResumeRecord, sanitize, validateBulkRunInput, validateRunChargeCap, writePrivate } from './reliable-actor.mjs';

const DEFAULT_ACTOR_ID = 'apple_yang/instagram-transcripts-scraper';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const FIXTURE_FILE = path.join(ROOT, 'tests', 'fixtures', 'live', 'tc02-native-bulk.json');
const OUTPUT_FILE = path.join(ROOT, 'sample-output', 'generated', 'nodejs-native-bulk-response.json');
const USAGE = 'Usage: node examples/nodejs/native-bulk.mjs [--resume RUN_ID]';

export async function main(argv = process.argv.slice(2), dependencies = {}) {
  const print = dependencies.print || console.log;
  if (argv.includes('--help') || argv.includes('-h')) { print(USAGE); return 0; }
  if (argv.length && (argv.length !== 2 || argv[0] !== '--resume' || !argv[1])) throw new TypeError(USAGE);
  const resumeId = argv[0] === '--resume' ? argv[1] : null;
  const runInput = validateBulkRunInput(JSON.parse(await (dependencies.readText || readFile)(dependencies.fixtureFile || FIXTURE_FILE, 'utf8')));
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
  await (dependencies.writeOutput || writePrivate)(dependencies.outputFile || OUTPUT_FILE, `${JSON.stringify(sanitize(result), null, 2)}\n`);

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
    datasetComplete: result.datasetComplete ?? false, counts: result.counts ?? null, extraResultCount: result.extraResults?.length ?? 0 }));
  if (result.executionStatus && result.executionStatus !== 'success' && result.bulkStatus === 'unknown') return EXIT_CODES[result.executionStatus] ?? EXIT_CODES.unknown;
  return BULK_EXIT_CODES[result.bulkStatus] ?? BULK_EXIT_CODES.unknown;
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : '';
if (import.meta.url === invokedPath) main().then((code) => { process.exitCode = code; }).catch((error) => { console.error(error.message || error); process.exitCode = 2; });
