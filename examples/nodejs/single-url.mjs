import dotenv from 'dotenv';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { CONTROLLED_BUILD_NUMBER, EXIT_CODES, RestTransport, RunJournal, buildRunInput, executeInput, loadResumeRecord, sanitize, writePrivate } from './reliable-actor.mjs';

const DEFAULT_ACTOR_ID = 'apple_yang/instagram-transcripts-scraper';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const OUTPUT_DIR = path.join(ROOT, 'sample-output', 'generated');
const OUTPUT_FILE = path.join(ROOT, 'sample-output', 'generated', 'nodejs-single-url-response.json');
const journal = new RunJournal(path.join(OUTPUT_DIR, 'nodejs-run-journal.jsonl'));

async function main() {
  dotenv.config({ path: path.join(ROOT, '.env') });
  let [url, resumeId] = process.argv.slice(2);
  if (url === '--resume' && (!resumeId || process.argv.length !== 4)) throw new Error('--resume accepts exactly one Run ID.');
  const token = process.env.APIFY_TOKEN;
  if (!token) throw new Error('APIFY_TOKEN is required.');
  const actorId = process.env.APIFY_ACTOR_ID || DEFAULT_ACTOR_ID;
  const requireBuild = process.env.APIFY_REQUIRE_BUILD === '1';
  const build = process.env.APIFY_BUILD;
  const resumeExpectedBuild = build || (requireBuild ? CONTROLLED_BUILD_NUMBER : null);
  const prior = resumeId && url === '--resume' ? await loadResumeRecord(journal, resumeId, actorId, resumeExpectedBuild) : null;
  if (prior) url = prior.sourceUrl;
  url ||= process.env.INSTAGRAM_REEL_URL;
  if (!url) throw new Error('Pass a Reel URL or --resume RUN_ID.');
  const result = await executeInput({ transport: new RestTransport(token), actorId,
    runInput: buildRunInput(url, process.env.INSTAGRAM_SESSIONID), sourceUrl: url, journal,
    runId: resumeId || null, datasetId: prior?.datasetId || null, rowId: prior?.rowId || null,
    maxTotalChargeUsd: process.env.APIFY_MAX_TOTAL_CHARGE_USD, requireChargeCap: process.env.APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD === '1',
    build, requireBuild, resumeBuildRecord: prior });
  await writePrivate(OUTPUT_FILE, `${JSON.stringify(sanitize(result.rawItems ?? result), null, 2)}\n`);
  console.log(JSON.stringify(Object.fromEntries(['rowId', 'sourceUrl', 'runId', 'datasetId', 'status', 'error'].map((key) => [key, result[key] ?? null]))));
  return EXIT_CODES[result.status] ?? 7;
}

main().then((code) => { process.exitCode = code; }).catch((error) => { console.error(error.message || error); process.exitCode = 2; });
