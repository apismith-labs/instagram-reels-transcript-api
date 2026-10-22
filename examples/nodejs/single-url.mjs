import dotenv from 'dotenv';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { CONTROLLED_BUILD_NUMBER, DATASET_PAGE_LIMIT, EXIT_CODES, RestTransport, RunJournal, buildRunInput, executeInput, loadResumeRecord, sanitize, validateVideoUrl, writePrivate } from './reliable-actor.mjs';

const DEFAULT_ACTOR_ID = 'apple_yang/instagram-transcripts-scraper';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const OUTPUT_FILE = path.join(ROOT, 'sample-output', 'generated', 'nodejs-single-url-response.json');
const USAGE = 'Usage: node examples/nodejs/single-url.mjs <Instagram Reel URL> | --resume <RUN_ID>';

export async function main(argv = process.argv.slice(2), dependencies = {}) {
  const print = dependencies.print || console.log;
  if (argv.includes('--help') || argv.includes('-h')) { print(USAGE); return 0; }
  let resumeId = null; let url = null;
  if (argv[0] === '--resume' && argv.length === 2 && argv[1]) resumeId = argv[1];
  else if (argv.length === 1 && !argv[0].startsWith('-')) url = validateVideoUrl(argv[0]);
  else throw new TypeError(USAGE);

  const env = dependencies.env || process.env;
  (dependencies.loadEnv || (() => dotenv.config({ path: path.join(ROOT, '.env') })))();
  const actorId = env.APIFY_ACTOR_ID || DEFAULT_ACTOR_ID;
  const journal = dependencies.journal || new RunJournal(path.join(ROOT, 'sample-output', 'generated', 'nodejs-run-journal.jsonl'));
  const prior = resumeId ? await (dependencies.loadResumeRecord || loadResumeRecord)(journal, resumeId, actorId, env.APIFY_BUILD || CONTROLLED_BUILD_NUMBER) : null;
  if (prior) url = validateVideoUrl(prior.sourceUrl);
  const token = env.APIFY_TOKEN;
  if (!token) throw new TypeError('APIFY_TOKEN is required.');
  const result = await (dependencies.executeInput || executeInput)({
    transport: dependencies.transport || new RestTransport(token), actorId,
    runInput: buildRunInput(url, env.INSTAGRAM_SESSIONID), sourceUrl: url, journal,
    runId: resumeId, datasetId: prior?.datasetId || null, rowId: prior?.rowId || null,
    maxTotalChargeUsd: env.APIFY_MAX_TOTAL_CHARGE_USD, requireChargeCap: env.APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD === '1',
    build: env.APIFY_BUILD || CONTROLLED_BUILD_NUMBER, requireBuild: true, resumeBuildRecord: prior,
    datasetPageLimit: DATASET_PAGE_LIMIT,
  });
  try { await (dependencies.writeOutput || writePrivate)(dependencies.outputFile || OUTPUT_FILE, `${JSON.stringify(sanitize(result.rawItems ?? result), null, 2)}\n`); }
  catch (error) {
    print(JSON.stringify({ rowId: result.rowId ?? null, runId: result.runId ?? null, datasetId: result.datasetId ?? null, status: result.status, outputError: String(error?.message || error).slice(0, 200) }));
    throw new Error(`Result output could not be saved. Preserve Run ID ${result.runId || '(unknown)'} and do not repeat the creation request.`);
  }
  print(JSON.stringify(Object.fromEntries(['rowId', 'sourceUrl', 'runId', 'datasetId', 'status', 'error', 'datasetComplete'].map((key) => [key, result[key] ?? null]))));
  return EXIT_CODES[result.status] ?? EXIT_CODES.unknown;
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : '';
if (import.meta.url === invokedPath) main().then((code) => { process.exitCode = code; }).catch((error) => { console.error(error.message || error); process.exitCode = 2; });
