import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { ApiError, CONTROLLED_BUILD_ID, CONTROLLED_BUILD_NUMBER, RunJournal } from '../../examples/nodejs/reliable-actor.mjs';
import { FakeTransport } from './offline-support.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const cleanup = (dir) => rm(dir, { recursive: true, force: true });
const reel = 'https://www.instagram.com/reels/synthetic-cli-reel/';

test('all Node CLIs import safely without reading Token, network, or creating files', async () => {
  const paths = ['single-url.mjs', 'native-bulk.mjs', 'batch-csv.mjs', 'profile.mjs'];
  for (const file of paths) {
    const module = await import(pathToFileURL(path.join(repoRoot, 'examples/nodejs', file)));
    assert.equal(typeof module.main, 'function');
  }
  const client = await import(pathToFileURL(path.join(repoRoot, 'examples/nodejs/client.mjs')));
  for (const name of ['getTranscript', 'getTranscripts', 'getProfilePosts']) assert.equal(typeof client[name], 'function');
});

test('single URL requires explicit URL and never falls back to INSTAGRAM_REEL_URL', async () => {
  const { main } = await import('../../examples/nodejs/single-url.mjs');
  const transport = new FakeTransport([]); let envLoaded = false;
  await assert.rejects(main([], { env: { APIFY_TOKEN: 'synthetic-token', INSTAGRAM_REEL_URL: reel }, transport,
    loadEnv: () => { envLoaded = true; } }), /Usage:/);
  assert.equal(envLoaded, false); assert.equal(transport.postCount, 0);
  await assert.rejects(main(['--unknown'], { env: { APIFY_TOKEN: 'synthetic-token' }, transport }), /Usage:/);
  assert.equal(transport.postCount, 0);
});

test('single URL validation rejects malformed inputs before loading credentials or POST', async () => {
  const { main } = await import('../../examples/nodejs/single-url.mjs');
  const invalid = ['', '[reel](https://www.instagram.com/reel/synthetic/)', 'http://www.instagram.com/reel/synthetic/',
    'https://example.com/reel/synthetic/', 'https://www.instagram.com/reel/synthetic/?x=1', 'https://www.instagram.com/p/synthetic/#x'];
  for (const value of invalid) {
    let envLoaded = false; const transport = new FakeTransport([]);
    await assert.rejects(main([value], { env: {}, transport, loadEnv: () => { envLoaded = true; } }));
    assert.equal(envLoaded, false); assert.equal(transport.postCount, 0);
  }
});

test('single URL with valid input but missing Token never creates a Run', async () => {
  const { main } = await import('../../examples/nodejs/single-url.mjs'); const transport = new FakeTransport([]);
  await assert.rejects(main([reel], { env: {}, loadEnv() {}, transport }), /APIFY_TOKEN is required/);
  assert.equal(transport.postCount, 0);
});

test('single URL defaults to the approved Build and sends restartOnError=false in Run query', async () => {
  const { main } = await import('../../examples/nodejs/single-url.mjs');
  const dir = await mkdtemp(path.join(os.tmpdir(), 'node-cli-single-'));
  try {
    const transport = new FakeTransport([
      { data: { id: 'single-cli-run', defaultDatasetId: 'single-cli-dataset', buildNumber: CONTROLLED_BUILD_NUMBER, buildId: CONTROLLED_BUILD_ID } },
      { data: { status: 'SUCCEEDED', defaultDatasetId: 'single-cli-dataset', buildNumber: CONTROLLED_BUILD_NUMBER, buildId: CONTROLLED_BUILD_ID } },
      [{ text: 'synthetic transcript' }],
    ]);
    const lines = [];
    const code = await main([reel], { env: { APIFY_TOKEN: 'synthetic-token' }, loadEnv() {}, transport,
      journal: new RunJournal(path.join(dir, 'runs.jsonl')), outputFile: path.join(dir, 'single.json'), print: (line) => lines.push(line) });
    assert.equal(code, 0); assert.equal(transport.postCount, 1);
    assert.deepEqual(transport.requests[0].query, { restartOnError: false, build: CONTROLLED_BUILD_NUMBER });
    assert.deepEqual(transport.requests[0].body, { videoUrl: reel });
    assert.equal(JSON.parse(lines[0]).datasetComplete, true);
  } finally { await cleanup(dir); }
});

test('single URL CLI creates a unique output path and preserves a prior result', async () => {
  const { main } = await import('../../examples/nodejs/single-url.mjs');
  const dir = await mkdtemp(path.join(os.tmpdir(), 'node-cli-single-unique-'));
  try {
    const outputBase = path.join(dir, 'result.json'); await writeFile(outputBase, 'previous result');
    const transport = new FakeTransport([
      { data: { id: 'single-unique-run', defaultDatasetId: 'single-unique-dataset', buildNumber: CONTROLLED_BUILD_NUMBER, buildId: CONTROLLED_BUILD_ID } },
      { data: { status: 'SUCCEEDED', defaultDatasetId: 'single-unique-dataset', buildNumber: CONTROLLED_BUILD_NUMBER, buildId: CONTROLLED_BUILD_ID } },
      [{ text: 'synthetic transcript' }],
    ]);
    const lines = [];
    await main([reel], { env: { APIFY_TOKEN: 'synthetic-token' }, loadEnv() {}, transport,
      journal: new RunJournal(path.join(dir, 'runs.jsonl')), outputFile: outputBase, print: (line) => lines.push(line) });
    const summary = JSON.parse(lines[0]);
    assert.notEqual(summary.outputFile, outputBase);
    assert.equal(await readFile(outputBase, 'utf8'), 'previous result');
    assert.match(await readFile(summary.outputFile, 'utf8'), /synthetic transcript/);
  } finally { await cleanup(dir); }
});

test('single URL Resume requires no URL and reuses the journal Run without POST', async () => {
  const { main } = await import('../../examples/nodejs/single-url.mjs');
  const dir = await mkdtemp(path.join(os.tmpdir(), 'node-cli-resume-'));
  try {
    const journal = new RunJournal(path.join(dir, 'runs.jsonl'));
    await journal.append({ rowId: 'resume-row', sourceUrl: reel, actorId: 'apple_yang/instagram-transcripts-scraper',
      runId: 'resume-run', datasetId: 'resume-dataset', requestedBuild: CONTROLLED_BUILD_NUMBER,
      expectedBuildNumber: CONTROLLED_BUILD_NUMBER, actualBuildNumber: CONTROLLED_BUILD_NUMBER,
      actualBuildId: CONTROLLED_BUILD_ID, buildVerification: 'verified', stage: 'run_created', status: 'unknown' });
    const transport = new FakeTransport([
      { data: { status: 'SUCCEEDED', defaultDatasetId: 'resume-dataset', buildNumber: CONTROLLED_BUILD_NUMBER, buildId: CONTROLLED_BUILD_ID } },
      [{ text: 'synthetic transcript' }],
    ]);
    const code = await main(['--resume', 'resume-run'], { env: { APIFY_TOKEN: 'synthetic-token' }, loadEnv() {}, transport,
      journal, outputFile: path.join(dir, 'resume.json'), writeOutput: async () => {}, print() {} });
    assert.equal(code, 0); assert.equal(transport.postCount, 0); assert.equal(transport.getCount, 2);
  } finally { await cleanup(dir); }
});

test('Native Bulk CLI requires explicit URLs and sends all of them in one safe creation request', async () => {
  const { main } = await import('../../examples/nodejs/native-bulk.mjs');
  const dir = await mkdtemp(path.join(os.tmpdir(), 'node-cli-bulk-'));
  try {
    const fixtureFile = path.join(repoRoot, 'tests/fixtures/live/tc02-native-bulk.json');
    const input = JSON.parse(await readFile(fixtureFile, 'utf8'));
    const items = input.bulkUrls.map((url) => ({ url, text: 'Synthetic transcript.' }));
    const transport = new FakeTransport([
      { data: { id: 'bulk-cli-run', defaultDatasetId: 'bulk-cli-dataset', buildNumber: CONTROLLED_BUILD_NUMBER, buildId: CONTROLLED_BUILD_ID } },
      { data: { status: 'SUCCEEDED', defaultDatasetId: 'bulk-cli-dataset', buildNumber: CONTROLLED_BUILD_NUMBER, buildId: CONTROLLED_BUILD_ID } },
      items,
    ]);
    const lines = [];
    const code = await main(input.bulkUrls, { env: { APIFY_TOKEN: 'synthetic-token' }, loadEnv() {}, transport,
      journal: new RunJournal(path.join(dir, 'runs.jsonl')), outputFile: path.join(dir, 'bulk.json'),
      metadataArchive: { append: async () => {} }, print: (line) => lines.push(line) });
    assert.equal(code, 0); assert.equal(transport.postCount, 1);
    assert.deepEqual(transport.requests[0].query, { restartOnError: false, build: CONTROLLED_BUILD_NUMBER });
    assert.deepEqual(transport.requests[0].body, input); assert.equal(JSON.parse(lines.at(-1)).bulkStatus, 'all_success');
  } finally { await cleanup(dir); }
});

test('CSV path is mandatory and dry-run fully validates rows without Token or POST', async () => {
  const { main } = await import('../../examples/nodejs/batch-csv.mjs');
  const dir = await mkdtemp(path.join(os.tmpdir(), 'node-cli-csv-dry-'));
  try {
    const file = path.join(dir, 'valid.csv'); await writeFile(file, `\uFEFFvideoUrl\r\n${reel}\r\n`);
    let tokenRead = false; const env = { get MAX_CONCURRENCY() { return '2'; }, get APIFY_TOKEN() { tokenRead = true; return ''; } };
    let loaded = false; const transport = new FakeTransport([]); const lines = [];
    await assert.rejects(main([], { env, transport }), /Usage:/);
    const code = await main([file, '--dry-run'], { env, transport, loadEnv: () => { loaded = true; }, print: (line) => lines.push(line) });
    assert.equal(code, 0); assert.equal(tokenRead, false); assert.equal(loaded, false); assert.equal(transport.postCount, 0);
    assert.deepEqual(JSON.parse(lines[0]), { mode: 'dry-run', rows: 1, maximumActorRuns: 1, concurrency: 2,
      actorBuild: CONTROLLED_BUILD_NUMBER, buildVerificationRequired: true, maxTotalChargeUsd: null, requireChargeCap: false, csvPath: file });
    await assert.rejects(main([file, '--dry-run'], { env: { MAX_CONCURRENCY: 'abc' }, transport,
      loadEnv: () => { throw new Error('must not load env'); } }), /MAX_CONCURRENCY must be a positive integer/);
    const bad = path.join(dir, 'bad.csv'); await writeFile(bad, `videoUrl\n${reel}\n[bad](https://www.instagram.com/reel/synthetic/)\n`);
    await assert.rejects(main([bad, '--dry-run'], { env, transport, loadEnv: () => { throw new Error('must not load env'); } }), /CSV line 3:/);
    assert.equal(transport.postCount, 0);
  } finally { await cleanup(dir); }
});

test('CSV real mock keeps one POST per row, isolates row failure, and writes unique result files', async () => {
  const { main } = await import('../../examples/nodejs/batch-csv.mjs');
  const dir = await mkdtemp(path.join(os.tmpdir(), 'node-cli-csv-run-'));
  try {
    const file = path.join(dir, 'urls.csv'); const second = reel.replace('synthetic-cli-reel', 'synthetic-cli-second');
    await writeFile(file, `videoUrl\n${reel}\n${second}\n`);
    const transport = new FakeTransport([
      { data: { id: 'csv-run-one', defaultDatasetId: 'csv-dataset-one', buildNumber: CONTROLLED_BUILD_NUMBER, buildId: CONTROLLED_BUILD_ID } },
      { data: { status: 'SUCCEEDED', defaultDatasetId: 'csv-dataset-one', buildNumber: CONTROLLED_BUILD_NUMBER, buildId: CONTROLLED_BUILD_ID } },
      [{ text: 'synthetic transcript' }], new ApiError('HTTP 403', { status: 403 }),
    ]);
    const outputDir = path.join(dir, 'outputs'); const journal = new RunJournal(path.join(dir, 'journal.jsonl')); const lines = [];
    const code = await main([file, '--concurrency', '1'], { env: { APIFY_TOKEN: 'synthetic-token' }, loadEnv() {}, transport, journal, outputDir, print: (line) => lines.push(line) });
    assert.equal(code, 1); assert.equal(transport.postCount, 2);
    assert.deepEqual(transport.requests.filter((request) => request.method === 'POST').map((request) => request.query), [
      { restartOnError: false, build: CONTROLLED_BUILD_NUMBER }, { restartOnError: false, build: CONTROLLED_BUILD_NUMBER },
    ]);
    const summary = JSON.parse(lines.at(-1)); assert.equal(summary.processed, 2); assert.equal(summary.success, 1); assert.equal(summary.transport_error, 1);
    assert.notEqual(summary.resultsFile, path.join(outputDir, 'nodejs-batch-results.jsonl'));
    const records = (await readFile(summary.resultsFile, 'utf8')).trim().split('\n').map(JSON.parse);
    assert.deepEqual(records.map((record) => record.status), ['success', 'transport_error']);
  } finally { await cleanup(dir); }
});

test('CSV stops launching later rows when a created Run cannot be journaled', async () => {
  const { main } = await import('../../examples/nodejs/batch-csv.mjs');
  const dir = await mkdtemp(path.join(os.tmpdir(), 'node-cli-csv-journal-'));
  try {
    const file = path.join(dir, 'urls.csv'); const second = reel.replace('synthetic-cli-reel', 'synthetic-cli-second');
    await writeFile(file, `videoUrl\n${reel}\n${second}\n`);
    const transport = new FakeTransport([
      { data: { id: 'csv-journal-run', defaultDatasetId: 'csv-journal-dataset', buildNumber: CONTROLLED_BUILD_NUMBER, buildId: CONTROLLED_BUILD_ID } },
    ]);
    const journal = { append: async (record) => { if (record.stage === 'run_created') throw new Error('synthetic journal failure'); } };
    const lines = [];
    const code = await main([file, '--concurrency', '1'], { env: { APIFY_TOKEN: 'synthetic-token' }, loadEnv() {}, transport, journal,
      outputDir: path.join(dir, 'outputs'), print: (line) => lines.push(line) });
    assert.equal(code, 1); assert.equal(transport.postCount, 1); assert.equal(transport.getCount, 0);
    const summary = JSON.parse(lines.at(-1)); assert.equal(summary.processed, 2);
    const records = (await readFile(summary.resultsFile, 'utf8')).trim().split('\n').map(JSON.parse);
    assert.equal(records[0].runId, 'csv-journal-run'); assert.equal(records[0].recoveryPersisted, false);
    assert.equal(records[1].status, 'unknown'); assert.match(records[1].error, /Not started/);
  } finally { await cleanup(dir); }
});

test('CSV output write failure reports completed Run IDs instead of hiding them', async () => {
  const { main } = await import('../../examples/nodejs/batch-csv.mjs');
  const dir = await mkdtemp(path.join(os.tmpdir(), 'node-cli-csv-output-fail-'));
  try {
    const file = path.join(dir, 'urls.csv'); await writeFile(file, `videoUrl\n${reel}\n`);
    const transport = new FakeTransport([
      { data: { id: 'csv-output-run', defaultDatasetId: 'csv-output-dataset', buildNumber: CONTROLLED_BUILD_NUMBER, buildId: CONTROLLED_BUILD_ID } },
      { data: { status: 'SUCCEEDED', defaultDatasetId: 'csv-output-dataset', buildNumber: CONTROLLED_BUILD_NUMBER, buildId: CONTROLLED_BUILD_ID } },
      [{ text: 'Synthetic transcript' }],
    ]);
    const lines = [];
    await assert.rejects(main([file], { env: { APIFY_TOKEN: 'synthetic-token' }, loadEnv() {}, transport,
      journal: new RunJournal(path.join(dir, 'journal.jsonl')), outputDir: path.join(dir, 'outputs'),
      writeUnique: async () => { throw new Error('synthetic output disk failure'); }, print: (line) => lines.push(line) }), /do not rerun/);
    const summary = JSON.parse(lines.at(-1));
    assert.equal(transport.postCount, 1); assert.equal(summary.results[0].runId, 'csv-output-run');
    assert.equal(summary.results[0].datasetId, 'csv-output-dataset');
  } finally { await cleanup(dir); }
});

test('Native Bulk main can be imported and help returns without token or POST', async () => {
  const { main, parseArgs } = await import('../../examples/nodejs/native-bulk.mjs'); const transport = new FakeTransport([]); const lines = [];
  assert.equal(await main(['--help'], { env: {}, transport, print: (line) => lines.push(line) }), 0);
  assert.match(lines[0], /Usage:/); assert.equal(transport.postCount, 0);
  await assert.rejects(main([], { env: { APIFY_TOKEN: 'synthetic-token' }, loadEnv() {}, transport }), /Usage:/);
  assert.equal(transport.postCount, 0);
  assert.deepEqual(parseArgs(['https://www.instagram.com/reel/one/', '--results-limit', '12', '--include-shares-count', 'false']).runInput,
    { bulkUrls: ['https://www.instagram.com/reel/one/'], resultsLimit: 12, skipPinnedPosts: false, includeSharesCount: false });
  assert.throws(() => parseArgs(['https://www.instagram.com/reel/one/', 'https://www.instagram.com/reel/one/']), /duplicates/);
});

test('Native Bulk Resume verifies exact input identity and never creates another Run', async () => {
  const { main } = await import('../../examples/nodejs/native-bulk.mjs');
  const dir = await mkdtemp(path.join(os.tmpdir(), 'node-cli-bulk-resume-'));
  try {
    const urls = ['https://www.instagram.com/reel/one/'];
    const runInput = { bulkUrls: urls, resultsLimit: 12, skipPinnedPosts: false, includeSharesCount: false };
    const journal = new RunJournal(path.join(dir, 'runs.jsonl'));
    await journal.append({ rowId: 'bulk-resume-row', sourceUrl: 'native_bulk', actorId: 'apple_yang/instagram-transcripts-scraper',
      runId: 'bulk-resume-run', datasetId: 'bulk-resume-dataset', expectedBuildNumber: CONTROLLED_BUILD_NUMBER,
      actualBuildNumber: CONTROLLED_BUILD_NUMBER, actualBuildId: CONTROLLED_BUILD_ID, buildVerification: 'verified',
      inputContext: { mode: 'native_bulk', input: runInput }, stage: 'run_created', status: 'unknown' });
    const transport = new FakeTransport([
      { data: { id: 'bulk-resume-run', status: 'SUCCEEDED', defaultDatasetId: 'bulk-resume-dataset',
        buildNumber: CONTROLLED_BUILD_NUMBER, buildId: CONTROLLED_BUILD_ID } },
      [{ url: urls[0], text: 'Synthetic transcript.' }],
    ]);
    const code = await main(['--resume', 'bulk-resume-run', ...urls], { env: { APIFY_TOKEN: 'synthetic-token' }, loadEnv() {},
      transport, journal, outputFile: path.join(dir, 'bulk.json'), metadataArchive: { append: async () => {} }, print() {} });
    assert.equal(code, 0); assert.equal(transport.postCount, 0); assert.equal(transport.getCount, 2);
    await assert.rejects(main(['--resume', 'bulk-resume-run', 'https://www.instagram.com/reel/different/'], {
      env: { APIFY_TOKEN: 'synthetic-token' }, loadEnv() {}, transport: new FakeTransport([]), journal,
    }), /does not match/);
  } finally { await cleanup(dir); }
});

test('Profile CLI sends explicit Profile input and reports metadata without requiring transcript', async () => {
  const { main } = await import('../../examples/nodejs/profile.mjs');
  const dir = await mkdtemp(path.join(os.tmpdir(), 'node-cli-profile-'));
  try {
    const transport = new FakeTransport([
      { data: { id: 'profile-run', defaultDatasetId: 'profile-dataset', buildNumber: CONTROLLED_BUILD_NUMBER, buildId: CONTROLLED_BUILD_ID } },
      { data: { status: 'SUCCEEDED', defaultDatasetId: 'profile-dataset', buildNumber: CONTROLLED_BUILD_NUMBER, buildId: CONTROLLED_BUILD_ID } },
      [{ url: 'https://www.instagram.com/p/synthetic-profile-post/', type: 'Image' }],
    ]);
    const lines = [];
    const code = await main(['alice', '--results-limit', '1'], { env: { APIFY_TOKEN: 'synthetic-token' }, loadEnv() {}, transport,
      journal: new RunJournal(path.join(dir, 'runs.jsonl')), writeOutput: async () => path.join(dir, 'profile.json'), print: (line) => lines.push(line) });
    assert.equal(code, 0); assert.equal(transport.postCount, 1);
    assert.deepEqual(transport.requests[0].body, { usernames: ['alice'], resultsLimit: 1 });
    assert.deepEqual(transport.requests[0].query, { restartOnError: false, build: CONTROLLED_BUILD_NUMBER });
    const summary = JSON.parse(lines[0]);
    assert.equal(summary.status, 'success'); assert.equal(summary.runStatus, 'SUCCEEDED');
    assert.equal(Object.hasOwn(summary, 'executionStatus'), false); assert.equal(summary.posts[0].type, 'Image');
  } finally { await cleanup(dir); }
});
