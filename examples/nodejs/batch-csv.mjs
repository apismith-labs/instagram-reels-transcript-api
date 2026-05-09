import { ApifyClient } from 'apify-client';
import dotenv from 'dotenv';
import pLimit from 'p-limit';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DEFAULT_ACTOR_ID = 'apple_yang/instagram-transcripts-scraper';
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, '../..');
const DEFAULT_CSV = path.join(REPO_ROOT, 'sample-data', 'instagram-reel-urls.csv');
const OUTPUT_DIR = path.join(REPO_ROOT, 'sample-output', 'generated');
const RESULTS_FILE = path.join(OUTPUT_DIR, 'nodejs-batch-results.jsonl');
const ERRORS_FILE = path.join(OUTPUT_DIR, 'nodejs-batch-errors.csv');
const MAX_RETRIES = 2;

dotenv.config({ path: path.join(REPO_ROOT, '.env') });

function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Error: ${name} is required. Set it in .env or your environment.`);
  }
  return value;
}

function parseMaxConcurrency() {
  const value = Number.parseInt(process.env.MAX_CONCURRENCY || '3', 10);
  if (!Number.isInteger(value) || value < 1) {
    throw new Error('Error: MAX_CONCURRENCY must be an integer of at least 1.');
  }
  return value;
}

function parseCsvLine(line) {
  const values = [];
  let value = '';
  let inQuotes = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    const nextChar = line[index + 1];

    if (char === '"' && inQuotes && nextChar === '"') {
      value += '"';
      index += 1;
    } else if (char === '"') {
      inQuotes = !inQuotes;
    } else if (char === ',' && !inQuotes) {
      values.push(value);
      value = '';
    } else {
      value += char;
    }
  }

  values.push(value);
  return values;
}

async function readUrls(csvPath) {
  let content;
  try {
    content = await readFile(csvPath, 'utf8');
  } catch {
    throw new Error(`Error: CSV file not found: ${csvPath}`);
  }

  const lines = content.split(/\r?\n/).filter((line) => line.trim());
  if (lines.length === 0) {
    throw new Error('Error: CSV is empty.');
  }

  const headers = parseCsvLine(lines[0]).map((header) => header.trim());
  const videoUrlIndex = headers.indexOf('videoUrl');
  if (videoUrlIndex === -1) {
    throw new Error('Error: CSV must include a videoUrl column.');
  }

  return lines
    .slice(1)
    .map((line) => parseCsvLine(line)[videoUrlIndex]?.trim() || '')
    .filter(Boolean);
}

function firstValue(items, key) {
  for (const item of items) {
    if (item?.[key]) return item[key];
  }
  return undefined;
}

async function fetchDatasetItems(client, datasetId) {
  const response = await client.dataset(datasetId).listItems();
  return response.items ?? [];
}

async function callActorOnce(token, actorId, videoUrl, sessionid) {
  const client = new ApifyClient({ token });
  const run = await client.actor(actorId).call({
    videoUrl,
    sessionid,
  });
  const datasetId = run?.defaultDatasetId;
  if (!datasetId) {
    throw new Error('Actor run completed without a defaultDatasetId.');
  }
  return fetchDatasetItems(client, datasetId);
}

function buildResult(sourceUrl, items) {
  const text = firstValue(items, 'text');
  const segments = firstValue(items, 'segments');
  const errMsg = firstValue(items, 'errMsg');
  let status = 'success';
  if (errMsg) status = 'actor_error';
  if (items.length === 0) status = 'empty';

  return {
    sourceUrl,
    status,
    itemCount: items.length,
    text: text || '',
    segments: segments || [],
    errMsg: errMsg || '',
    rawItems: items,
  };
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function processUrl(token, actorId, videoUrl, sessionid) {
  let lastError;
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt += 1) {
    try {
      const items = await callActorOnce(token, actorId, videoUrl, sessionid);
      return buildResult(videoUrl, items);
    } catch (error) {
      lastError = error;
      if (attempt < MAX_RETRIES) {
        await sleep(1000 * 2 ** attempt);
      }
    }
  }

  throw new Error(lastError?.message || 'Unknown error');
}

function csvEscape(value) {
  const text = String(value ?? '');
  if (/[",\n\r]/.test(text)) {
    return `"${text.replaceAll('"', '""')}"`;
  }
  return text;
}

async function writeOutputs(results, errors) {
  await mkdir(OUTPUT_DIR, { recursive: true });
  const jsonl = results.map((result) => JSON.stringify(result)).join('\n');
  await writeFile(RESULTS_FILE, jsonl ? `${jsonl}\n` : '', 'utf8');

  const rows = ['sourceUrl,error'];
  for (const error of errors) {
    rows.push(`${csvEscape(error.sourceUrl)},${csvEscape(error.error)}`);
  }
  await writeFile(ERRORS_FILE, `${rows.join('\n')}\n`, 'utf8');
}

async function main() {
  const token = requireEnv('APIFY_TOKEN');
  const actorId = process.env.APIFY_ACTOR_ID || DEFAULT_ACTOR_ID;
  const sessionid = process.env.INSTAGRAM_SESSIONID || '';
  const csvPath = process.argv[2] ? path.resolve(process.argv[2]) : DEFAULT_CSV;
  const maxConcurrency = parseMaxConcurrency();
  const urls = await readUrls(csvPath);

  if (urls.length === 0) {
    throw new Error('Error: CSV does not contain any videoUrl values.');
  }

  console.log(`Actor ID: ${actorId}`);
  console.log(`Total URLs: ${urls.length}`);
  console.log(`Max concurrency: ${maxConcurrency}`);
  // Higher concurrency can increase Apify usage cost and rate-limit risk.

  const limit = pLimit(maxConcurrency);
  const results = [];
  const errors = [];
  let processed = 0;
  let success = 0;
  let failed = 0;

  await Promise.all(
    urls.map((videoUrl) =>
      limit(async () => {
        try {
          const result = await processUrl(token, actorId, videoUrl, sessionid);
          results.push(result);
          success += 1;
        } catch (error) {
          errors.push({ sourceUrl: videoUrl, error: error.message || String(error) });
          failed += 1;
        } finally {
          processed += 1;
          console.log(
            `Progress: total=${urls.length} processed=${processed} success=${success} failed=${failed}`,
          );
        }
      }),
    ),
  );

  await writeOutputs(results, errors);

  console.log(`Results path: ${RESULTS_FILE}`);
  console.log(`Errors path: ${ERRORS_FILE}`);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
