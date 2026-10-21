import dotenv from 'dotenv';
import pLimit from 'p-limit';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { RestTransport, RunJournal, buildRunInput, executeInput, sanitize, summarize, writePrivate } from './reliable-actor.mjs';

const DEFAULT_ACTOR_ID = 'apple_yang/instagram-transcripts-scraper';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const OUTPUT_DIR = path.join(ROOT, 'sample-output', 'generated');
const journal = new RunJournal(path.join(OUTPUT_DIR, 'nodejs-run-journal.jsonl'));
function parseCsvLine(line) {
  const values = []; let value = ''; let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (char === '"' && quoted && line[i + 1] === '"') { value += '"'; i += 1; }
    else if (char === '"') quoted = !quoted;
    else if (char === ',' && !quoted) { values.push(value); value = ''; }
    else value += char;
  }
  values.push(value); return values;
}
async function readUrls(file) {
  const lines = (await readFile(file, 'utf8')).split(/\r?\n/).filter((line) => line.trim());
  if (!lines.length) throw new Error('CSV is empty.');
  const headers = parseCsvLine(lines[0]).map((x) => x.trim()); const index = headers.indexOf('videoUrl');
  if (index < 0) throw new Error('CSV must include a videoUrl column.');
  return lines.slice(1).map((line, row) => ({ inputRow: String(row + 2), sourceUrl: parseCsvLine(line)[index]?.trim() || '' })).filter((row) => row.sourceUrl);
}
function csvEscape(value) { const text = String(value ?? ''); return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text; }
async function main() {
  dotenv.config({ path: path.join(ROOT, '.env') });
  const token = process.env.APIFY_TOKEN; if (!token) throw new Error('APIFY_TOKEN is required.');
  const actorId = process.env.APIFY_ACTOR_ID || DEFAULT_ACTOR_ID;
  const csv = process.argv[2] ? path.resolve(process.argv[2]) : path.join(ROOT, 'sample-data', 'instagram-reel-urls.csv');
  const urls = await readUrls(csv); if (!urls.length) throw new Error('CSV contains no videoUrl values.');
  const concurrency = Number.parseInt(process.env.MAX_CONCURRENCY || '3', 10);
  if (!Number.isInteger(concurrency) || concurrency < 1) throw new Error('MAX_CONCURRENCY must be a positive integer.');
  const limit = pLimit(concurrency);
  const results = await Promise.all(urls.map((row) => limit(() => executeInput({ transport: new RestTransport(token), actorId,
    runInput: buildRunInput(row.sourceUrl, process.env.INSTAGRAM_SESSIONID), sourceUrl: row.sourceUrl, rowId: row.inputRow, journal,
    maxTotalChargeUsd: process.env.APIFY_MAX_TOTAL_CHARGE_USD, requireChargeCap: process.env.APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD === '1',
    build: process.env.APIFY_BUILD, requireBuild: process.env.APIFY_REQUIRE_BUILD === '1' }))));
  const counts = summarize(results);
  await writePrivate(path.join(OUTPUT_DIR, 'nodejs-batch-results.jsonl'), results.map((r) => JSON.stringify(sanitize(r))).join('\n') + '\n');
  const failed = results.filter((r) => r.status !== 'success');
  const rows = ['rowId,sourceUrl,runId,status,error', ...failed.map((r) => [r.rowId, r.sourceUrl, r.runId, r.status, r.error].map(csvEscape).join(','))];
  await writePrivate(path.join(OUTPUT_DIR, 'nodejs-batch-errors.csv'), `${rows.join('\n')}\n`);
  console.log(JSON.stringify(counts)); return counts.failed ? 1 : 0;
}
main().then((code) => { process.exitCode = code; }).catch((error) => { console.error(error.message || error); process.exitCode = 2; });
