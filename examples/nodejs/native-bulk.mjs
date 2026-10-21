import dotenv from 'dotenv';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { BULK_EXIT_CODES, CONTROLLED_BUILD_NUMBER, EXIT_CODES, RestTransport, RunJournal, RunMetadataArchive, archiveRunMetadataBestEffort, createRunMetadataRecord, executeBulkInput, loadBulkResumeRecord, sanitize, validateRunChargeCap, writePrivate } from './reliable-actor.mjs';

const DEFAULT_ACTOR_ID = 'apple_yang/instagram-transcripts-scraper';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const OUTPUT_DIR = path.join(ROOT, 'sample-output', 'generated');
const FIXTURE_FILE = path.join(ROOT, 'tests', 'fixtures', 'live', 'tc02-native-bulk.json');
const OUTPUT_FILE = path.join(OUTPUT_DIR, 'nodejs-native-bulk-response.json');
const journal = new RunJournal(path.join(OUTPUT_DIR, 'nodejs-run-journal.jsonl'));
const metadataArchive = new RunMetadataArchive(path.join(OUTPUT_DIR, 'nodejs-run-metadata.jsonl'));

async function readFixtureInput() {
  const fixture = JSON.parse(await readFile(FIXTURE_FILE, 'utf8'));
  return fixture;
}

async function main() {
  dotenv.config({ path: path.join(ROOT, '.env') });
  const args = process.argv.slice(2);
  if (args.length && (args.length !== 2 || args[0] !== '--resume' || !args[1])) throw new Error('Usage: node native-bulk.mjs [--resume RUN_ID]');
  const resumeId = args[0] === '--resume' ? args[1] : null;
  const runInput = await readFixtureInput();
  const token = process.env.APIFY_TOKEN;
  if (!token) throw new Error('APIFY_TOKEN is required.');
  const actorId = process.env.APIFY_ACTOR_ID || DEFAULT_ACTOR_ID;
  const requireBuild = process.env.APIFY_REQUIRE_BUILD === '1';
  const build = process.env.APIFY_BUILD;
  const expectedBuild = build || (requireBuild ? CONTROLLED_BUILD_NUMBER : null);
  const prior = resumeId ? await loadBulkResumeRecord(journal, resumeId, actorId, runInput, expectedBuild) : null;
  const result = await executeBulkInput({ transport: new RestTransport(token), actorId, runInput, journal,
    runId: resumeId, datasetId: prior?.datasetId || null, rowId: prior?.rowId || null, resumeBuildRecord: prior,
    build, requireBuild, maxTotalChargeUsd: process.env.APIFY_MAX_TOTAL_CHARGE_USD,
    requireChargeCap: process.env.APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD === '1' });
  await writePrivate(OUTPUT_FILE, `${JSON.stringify(sanitize(result), null, 2)}\n`);

  if (result.runId && result.runMetadata && (Array.isArray(result.rawItems) || result.executionStatus === 'run_failed')) {
    try {
      let chargeCap = null;
      try { chargeCap = validateRunChargeCap(process.env.APIFY_MAX_TOTAL_CHARGE_USD, false); } catch { /* Runner has already rejected invalid creation configuration. */ }
      const latest = await journal.latest(result.runId);
      const metadata = createRunMetadataRecord({ apiRun: result.runMetadata, actorId, runId: result.runId,
        chargeCap, chargeCapRequired: process.env.APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD === '1',
        buildVerification: latest?.buildVerification || null, recoveredFromResume: Boolean(resumeId) });
      await archiveRunMetadataBestEffort(metadataArchive, metadata, (message) => console.error(message));
    } catch (error) { console.error(`Run metadata archive preparation failed: ${error.message || error}`); }
  }

  console.log(JSON.stringify({ runId: result.runId ?? null, datasetId: result.datasetId ?? null,
    executionStatus: result.executionStatus ?? result.status, bulkStatus: result.bulkStatus ?? 'unknown',
    datasetComplete: result.datasetComplete ?? false, counts: result.counts ?? null, extraResultCount: result.extraResults?.length ?? 0 }));
  if (result.executionStatus && result.executionStatus !== 'success' && result.bulkStatus === 'unknown') return EXIT_CODES[result.executionStatus] ?? EXIT_CODES.unknown;
  return BULK_EXIT_CODES[result.bulkStatus] ?? BULK_EXIT_CODES.unknown;
}

main().then((code) => { process.exitCode = code; }).catch((error) => { console.error(error.message || error); process.exitCode = 2; });
