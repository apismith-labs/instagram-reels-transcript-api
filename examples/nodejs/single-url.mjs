import { ApifyClient } from 'apify-client';
import dotenv from 'dotenv';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DEFAULT_ACTOR_ID = 'apple_yang/instagram-transcripts-scraper';
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, '../..');
const OUTPUT_DIR = path.join(REPO_ROOT, 'sample-output', 'generated');
const OUTPUT_FILE = path.join(OUTPUT_DIR, 'nodejs-single-url-response.json');

dotenv.config({ path: path.join(REPO_ROOT, '.env') });

function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Error: ${name} is required. Set it in .env or your environment.`);
  }
  return value;
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

async function main() {
  const token = requireEnv('APIFY_TOKEN');
  const actorId = process.env.APIFY_ACTOR_ID || DEFAULT_ACTOR_ID;
  const sessionid = process.env.INSTAGRAM_SESSIONID || '';
  const reelUrl = process.argv[2] || process.env.INSTAGRAM_REEL_URL;

  if (!reelUrl) {
    throw new Error(
      'Error: INSTAGRAM_REEL_URL is required. Set it in .env or pass it as a CLI argument.',
    );
  }

  const client = new ApifyClient({ token });
  const runInput = {
    videoUrl: reelUrl,
    sessionid,
  };

  console.log(`Actor ID: ${actorId}`);
  console.log('Running request...');

  const run = await client.actor(actorId).call(runInput);
  const datasetId = run?.defaultDatasetId;
  if (!datasetId) {
    throw new Error('Error: Actor run completed without a defaultDatasetId.');
  }

  const items = await fetchDatasetItems(client, datasetId);
  await mkdir(OUTPUT_DIR, { recursive: true });
  await writeFile(OUTPUT_FILE, `${JSON.stringify(items, null, 2)}\n`, 'utf8');

  const text = firstValue(items, 'text');
  const segments = firstValue(items, 'segments');
  const errMsg = firstValue(items, 'errMsg');

  console.log(`Output path: ${OUTPUT_FILE}`);
  console.log(`Items: ${items.length}`);
  console.log(`Transcript characters: ${typeof text === 'string' ? text.length : 0}`);
  console.log(`Segments: ${Array.isArray(segments) ? segments.length : 0}`);
  if (errMsg) {
    console.log(`errMsg: ${errMsg}`);
  }
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
