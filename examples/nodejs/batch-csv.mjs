import dotenv from 'dotenv';
import pLimit from 'p-limit';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { CONTROLLED_BUILD_NUMBER, DATASET_PAGE_LIMIT, RestTransport, RunJournal, buildRunInput, executeInput, sanitize, summarize, validateBuildSelection, validateRunChargeCap, validateVideoUrl, writePrivateUnique } from './reliable-actor.mjs';

const DEFAULT_ACTOR_ID = 'apple_yang/instagram-transcripts-scraper';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const OUTPUT_DIR = path.join(ROOT, 'sample-output', 'generated');
const USAGE = 'Usage: node examples/nodejs/batch-csv.mjs <csv-path> [--dry-run] [--concurrency N]';

function parseCsvLine(line) {
  const values = []; let value = ''; let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (char === '"' && quoted && line[i + 1] === '"') { value += '"'; i += 1; }
    else if (char === '"') quoted = !quoted;
    else if (char === ',' && !quoted) { values.push(value); value = ''; }
    else value += char;
  }
  if (quoted) throw new TypeError('CSV contains an unterminated quoted field.');
  values.push(value); return values;
}

export async function readUrls(file, readText = readFile) {
  const contents = String(await readText(file, 'utf8')).replace(/^\uFEFF/, '');
  const lines = contents.split(/\r?\n/);
  const headerIndex = lines.findIndex((line) => line.trim());
  if (headerIndex < 0) throw new TypeError('CSV is empty.');
  const headers = parseCsvLine(lines[headerIndex]).map((value) => value.trim()); const index = headers.indexOf('videoUrl');
  if (index < 0) throw new TypeError('CSV must include a videoUrl column.');
  const rows = [];
  for (let lineIndex = headerIndex + 1; lineIndex < lines.length; lineIndex += 1) {
    const line = lines[lineIndex]; if (!line.trim()) continue;
    const sourceUrl = parseCsvLine(line)[index]?.trim() || '';
    if (!sourceUrl) continue;
    try { validateVideoUrl(sourceUrl); } catch (error) { throw new TypeError(`CSV line ${lineIndex + 1}: ${error.message}`); }
    rows.push({ inputRow: String(lineIndex + 1), sourceUrl });
  }
  if (!rows.length) throw new TypeError('CSV contains no videoUrl values.');
  return rows;
}

function parseArgs(argv) {
  let csvPath = null; let dryRun = false; let concurrency = null;
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--help' || arg === '-h') return { help: true };
    if (arg === '--dry-run') dryRun = true;
    else if (arg === '--concurrency') { concurrency = argv[++index]; if (!concurrency) throw new TypeError('--concurrency requires a positive integer.'); }
    else if (arg.startsWith('-')) throw new TypeError(`Unknown option: ${arg}\n${USAGE}`);
    else if (csvPath == null) csvPath = arg;
    else throw new TypeError(`Unexpected argument: ${arg}\n${USAGE}`);
  }
  if (!csvPath) throw new TypeError(USAGE);
  return { csvPath, dryRun, concurrency };
}

function parseConcurrency(explicit, env) {
  const raw = explicit ?? env.MAX_CONCURRENCY ?? '3';
  if (!/^\d+$/.test(String(raw)) || Number(raw) < 1) throw new TypeError('MAX_CONCURRENCY must be a positive integer.');
  return Number(raw);
}
function csvEscape(value) { const text = String(value ?? ''); return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text; }

export async function main(argv = process.argv.slice(2), dependencies = {}) {
  const print = dependencies.print || console.log;
  const parsed = parseArgs(argv);
  if (parsed.help) { print(USAGE); return 0; }
  const file = path.resolve(parsed.csvPath);
  const rows = await (dependencies.readUrls || readUrls)(file, dependencies.readText || readFile);
  const env = dependencies.env || process.env;
  if (!parsed.dryRun) (dependencies.loadEnv || (() => dotenv.config({ path: path.join(ROOT, '.env') })))();
  const concurrency = parseConcurrency(parsed.concurrency, env);
  const build = validateBuildSelection(env.APIFY_BUILD || CONTROLLED_BUILD_NUMBER, true);
  const requireChargeCap = env.APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD === '1';
  const chargeCap = validateRunChargeCap(env.APIFY_MAX_TOTAL_CHARGE_USD, requireChargeCap);
  if (parsed.dryRun) {
    print(JSON.stringify({ mode: 'dry-run', rows: rows.length, maximumActorRuns: rows.length, concurrency,
      actorBuild: build, buildVerificationRequired: true, maxTotalChargeUsd: chargeCap, requireChargeCap, csvPath: file }));
    return 0;
  }

  const token = env.APIFY_TOKEN; if (!token) throw new TypeError('APIFY_TOKEN is required.');
  const actorId = env.APIFY_ACTOR_ID || DEFAULT_ACTOR_ID;
  const journal = dependencies.journal || new RunJournal(path.join(OUTPUT_DIR, 'nodejs-run-journal.jsonl'));
  const transport = dependencies.transport || new RestTransport(token);
  const limit = dependencies.limitFactory ? dependencies.limitFactory(concurrency) : pLimit(concurrency);
  let next = 0; let stopLaunching = false;
  const results = Array(rows.length);
  const worker = async () => {
    while (!stopLaunching) {
      const index = next; next += 1; if (index >= rows.length) return;
      const row = rows[index];
      let result;
      try {
        result = await limit(() => (dependencies.executeInput || executeInput)({
          transport, actorId, runInput: buildRunInput(row.sourceUrl, env.INSTAGRAM_SESSIONID), sourceUrl: row.sourceUrl,
          rowId: row.inputRow, journal, maxTotalChargeUsd: chargeCap, requireChargeCap, build,
          requireBuild: true, datasetPageLimit: DATASET_PAGE_LIMIT,
        }));
      } catch (error) { result = { rowId: row.inputRow, sourceUrl: row.sourceUrl, runId: null, datasetId: null, status: 'transport_error', error: String(error?.message || error).slice(0, 300) }; }
      results[index] = result;
      if (result.recoveryPersisted === false) stopLaunching = true;
    }
  };
  await Promise.all(Array.from({ length: Math.min(concurrency, rows.length) }, worker));
  for (let index = 0; index < results.length; index += 1) if (!results[index]) {
    results[index] = { rowId: rows[index].inputRow, sourceUrl: rows[index].sourceUrl, runId: null, datasetId: null,
      status: 'unknown', error: 'Not started because Run journal persistence failed for another row.' };
  }
  const counts = summarize(results);
  const output = dependencies.writeUnique || writePrivateUnique;
  const failed = results.filter((result) => result.status !== 'success');
  const errorRows = ['rowId,sourceUrl,runId,status,error', ...failed.map((result) => [result.rowId, result.sourceUrl, result.runId, result.status, result.error].map(csvEscape).join(','))];
  const identities = results.map((result) => ({ rowId: result.rowId, runId: result.runId ?? null, datasetId: result.datasetId ?? null, status: result.status, error: result.error ?? null }));
  let resultsFile; let errorsFile;
  try {
    resultsFile = await output(path.join(dependencies.outputDir || OUTPUT_DIR, 'nodejs-batch-results.jsonl'), `${results.map((result) => JSON.stringify(sanitize(result))).join('\n')}\n`);
    errorsFile = await output(path.join(dependencies.outputDir || OUTPUT_DIR, 'nodejs-batch-errors.csv'), `${errorRows.join('\n')}\n`);
  } catch (error) {
    print(JSON.stringify({ ...counts, outputPersistenceError: String(error?.message || error).slice(0, 200), results: identities }));
    throw new Error('CSV result output could not be fully saved. Reconcile the reported Run IDs; do not rerun rows automatically.');
  }
  print(JSON.stringify({ ...counts, resultsFile, errorsFile }));
  return counts.failed ? 1 : 0;
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : '';
if (import.meta.url === invokedPath) main().then((code) => { process.exitCode = code; }).catch((error) => { console.error(error.message || error); process.exitCode = 2; });
