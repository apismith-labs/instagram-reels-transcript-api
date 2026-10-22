import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, stat } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { ApiError, BULK_EXIT_CODES, CONTROLLED_BUILD_ID, DATASET_PAGE_LIMIT, RunJournal, RunMetadataArchive, archiveRunMetadataBestEffort, attributeBulkItems, createRunMetadataRecord, executeBulkInput, loadBulkResumeRecord, validateBulkRunInput } from '../../examples/nodejs/reliable-actor.mjs';
import { FakeTransport, loadFixture, repoRoot } from './offline-support.mjs';

const actorId = 'apple_yang/instagram-transcripts-scraper';
const setup = async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'native-bulk-'));
  return { dir, journal: new RunJournal(path.join(dir, 'node-runs.jsonl')) };
};
const cleanup = (dir) => rm(dir, { recursive: true, force: true });
async function readTc02() {
  const fixture = JSON.parse(await readFile(path.join(repoRoot, 'tests/fixtures/live/tc02-native-bulk.json'), 'utf8'));
  return fixture;
}
function buildResponses(items, { buildNumber = '0.0.50', buildId = CONTROLLED_BUILD_ID, runStatus = 'SUCCEEDED' } = {}) {
  return [
    { data: { id: 'bulk-run-1', defaultDatasetId: 'bulk-dataset-1', buildNumber, buildId } },
    { data: { id: 'bulk-run-1', status: runStatus, defaultDatasetId: 'bulk-dataset-1', buildNumber, buildId,
      usageTotalUsd: 0.0165, chargedEventCounts: { 'apify-default-dataset-item': items.length, speech2text: items.length } } },
    items,
  ];
}

test('TC02 fixture constructs one exact Native Bulk Actor Input without single/profile mode fields', async () => {
  const fixture = await readTc02();
  const input = validateBulkRunInput(fixture);
  assert.deepEqual(input, fixture);
  assert.equal(input.bulkUrls.length, 3);
  assert.equal(Object.hasOwn(input, 'videoUrl'), false);
  assert.equal(Object.hasOwn(input, 'usernames'), false);
});

test('Native Bulk input rejects empty, malformed, Markdown, and mixed-mode inputs before POST', async () => {
  const tc02 = await readTc02();
  for (const input of [
    { ...tc02, bulkUrls: [] },
    { ...tc02, bulkUrls: ['not-a-url'] },
    { ...tc02, bulkUrls: ['[Reel](https://www.instagram.com/reels/DeKRjqRFQuJ/)'] },
    { ...tc02, videoUrl: tc02.bulkUrls[0] },
    { ...tc02, usernames: ['synthetic-user'] },
  ]) assert.throws(() => validateBulkRunInput(input));
  const { dir, journal } = await setup();
  try {
    const transport = new FakeTransport([]);
    await assert.rejects(executeBulkInput({ transport, actorId, runInput: { ...tc02, videoUrl: tc02.bulkUrls[0] }, journal }));
    assert.equal(transport.postCount, 0);
  } finally { await cleanup(dir); }
});

test('Native Bulk rejects duplicate URLs and host aliases before any POST', async () => {
  const first = 'https://www.instagram.com/reels/synthetic-duplicate/';
  assert.throws(() => validateBulkRunInput({ bulkUrls: [first, first] }), /duplicates/);
  assert.throws(() => validateBulkRunInput({ bulkUrls: [first, first.replace('www.', '')] }), /duplicates/);
});

test('Native Bulk inherits fail-closed Build and charge-cap gates before POST', async () => {
  const input = await readTc02();
  for (const options of [
    { build: undefined, requireBuild: true, maxTotalChargeUsd: '0.30', requireChargeCap: true },
    { build: '0.0.50', requireBuild: true, maxTotalChargeUsd: undefined, requireChargeCap: true },
  ]) {
    const { dir, journal } = await setup();
    try {
      const transport = new FakeTransport([]);
      const result = await executeBulkInput({ transport, actorId, runInput: input, journal, ...options });
      assert.equal(result.executionStatus, 'transport_error'); assert.equal(transport.postCount, 0);
    } finally { await cleanup(dir); }
  }
});

test('TC02 submits all three fixture URLs in exactly one POST with fixed Build and charge controls in query', async () => {
  const input = await readTc02();
  const outputItems = [
    { url: input.bulkUrls[2], text: 'Synthetic third transcript.', errMsg: '' },
    { url: input.bulkUrls[0], text: 'Synthetic first transcript.', errMsg: '' },
    { url: input.bulkUrls[1], text: 'Synthetic second transcript.', errMsg: '' },
  ];
  const { dir, journal } = await setup();
  try {
    const transport = new FakeTransport(buildResponses(outputItems));
    const result = await executeBulkInput({ transport, actorId, runInput: input, journal,
      maxTotalChargeUsd: '0.30', requireChargeCap: true, build: '0.0.50', requireBuild: true, sleepFn: async () => {} });
    assert.equal(transport.postCount, 1);
    assert.equal(result.bulkStatus, 'all_success');
    assert.deepEqual(transport.requests[0].body, input);
    assert.deepEqual(transport.requests[0].query, { maxTotalChargeUsd: 0.3, restartOnError: false, build: '0.0.50' });
    assert.equal(Object.hasOwn(transport.requests[0].body, 'build'), false);
    assert.equal(Object.hasOwn(transport.requests[0].body, 'maxTotalChargeUsd'), false);
    assert.equal(Object.hasOwn(transport.requests[0].body, 'restartOnError'), false);
    assert.deepEqual(result.inputs.map((row) => row.inputUrl), input.bulkUrls);
    assert.deepEqual(result.inputs.map((row) => row.results[0].url), input.bulkUrls);
    assert.equal(transport.requests[2].query.limit, DATASET_PAGE_LIMIT);
    assert.equal(transport.requests[2].query.offset, 0);
    assert.equal(result.datasetComplete, true);
    assert.equal(result.runMetadata.usageTotalUsd, 0.0165);
  } finally { await cleanup(dir); }
});

test('bulk mapping is order-independent and retains successes beside explicit item failure', async () => {
  const partial = await loadFixture('bulk-partial.synthetic.json');
  const mapped = attributeBulkItems(partial.input.bulkUrls, [...partial.items].reverse());
  assert.equal(mapped.bulkStatus, 'partial_success');
  assert.equal(mapped.inputs[0].status, 'success_transcript');
  assert.equal(mapped.inputs[1].status, 'actor_error');
  assert.equal(mapped.inputs[1].results[0].errMsg, 'Synthetic item failure.');
  assert.equal(BULK_EXIT_CODES.partial_success, 11);
});

test('definite per-item failures produce all_failed while no transcript stays distinct', async () => {
  const partial = await loadFixture('bulk-partial.synthetic.json');
  const mapped = attributeBulkItems(partial.input.bulkUrls, [
    { url: partial.input.bulkUrls[0], text: null, errMsg: 'Synthetic failure.' },
    { url: partial.input.bulkUrls[1], text: '' },
  ]);
  assert.equal(mapped.inputs[0].status, 'actor_error');
  assert.equal(mapped.inputs[1].status, 'no_transcript');
  assert.equal(mapped.bulkStatus, 'all_failed');
  assert.equal(BULK_EXIT_CODES.all_failed, 12);
  assert.equal(BULK_EXIT_CODES.all_success, 0);
  assert.equal(BULK_EXIT_CODES.unknown, 13);
});

test('bulk attribution marks missing, duplicate, and extra outputs without dropping or guessing', async () => {
  const partial = await loadFixture('bulk-partial.synthetic.json');
  const [first, second] = partial.input.bulkUrls;
  const mapped = attributeBulkItems(partial.input.bulkUrls, [
    { url: first, text: 'Synthetic transcript.' },
    { url: first, text: 'Duplicate synthetic transcript.' },
    { url: 'https://www.instagram.com/reels/unmapped-synthetic/', text: 'Extra synthetic result.' },
    { text: 'Synthetic result without url.' },
  ]);
  assert.equal(mapped.bulkStatus, 'unknown');
  assert.equal(mapped.inputs[0].status, 'duplicate_result');
  assert.equal(mapped.inputs[0].results.length, 2);
  assert.equal(mapped.inputs[1].status, 'missing_result');
  assert.equal(mapped.extraResults.length, 2);
  assert.equal(mapped.counts.duplicate_result, 1);
  assert.equal(mapped.counts.missing_result, 1);
  assert.equal(mapped.counts.unknown, 0, 'counts are per-input rows; extras stay in extraResults');
});

test('URL mapping only folds www host variance and refuses path or trailing-slash guesses', async () => {
  const input = await readTc02();
  const rows = attributeBulkItems(input.bulkUrls.slice(0, 1), [
    { url: input.bulkUrls[0].replace('www.instagram.com', 'instagram.com'), text: 'Synthetic transcript.' },
    { url: input.bulkUrls[0].replace(/\/$/, ''), text: 'Uncertain synthetic duplicate.' },
  ]);
  assert.equal(rows.inputs[0].status, 'success_transcript');
  assert.equal(rows.extraResults.length, 1);
  assert.equal(rows.bulkStatus, 'unknown');
});

test('Native Bulk uses a unique shortcode only when output URL is absent and rejects conflicting code', async () => {
  const input = await readTc02(); const first = input.bulkUrls[0]; const code = new URL(first).pathname.split('/').filter(Boolean).at(-1);
  const byCode = attributeBulkItems([first], [{ code, text: 'Synthetic transcript.' }]);
  assert.equal(byCode.inputs[0].status, 'success_transcript');
  const conflict = attributeBulkItems([first], [{ url: first, code: 'different-code', text: 'Synthetic transcript.' }]);
  assert.equal(conflict.inputs[0].status, 'missing_result');
  assert.equal(conflict.extraResults[0].reason, 'url_code_conflict');
  assert.equal(conflict.bulkStatus, 'unknown');
});

test('missing output under an incomplete Dataset is unknown per input, not a definite miss', async () => {
  const input = await readTc02();
  const result = attributeBulkItems(input.bulkUrls, [], { datasetComplete: false });
  assert.deepEqual(result.inputs.map((row) => row.status), ['unknown', 'unknown', 'unknown']);
  assert.equal(result.bulkStatus, 'unknown');
  assert.deepEqual(result.counts, { success_transcript: 0, actor_error: 0, no_transcript: 0, missing_result: 0, duplicate_result: 0, unknown: 3 });
});

test('ambiguous duplicate input URLs never associate one output with multiple inputs', async () => {
  const duplicate = 'https://www.instagram.com/reels/synthetic-same/';
  const result = attributeBulkItems([duplicate, duplicate], [{ url: duplicate, text: 'Synthetic transcript.' }]);
  assert.equal(result.bulkStatus, 'unknown');
  assert.deepEqual(result.inputs.map((row) => row.status), ['missing_result', 'missing_result']);
  assert.equal(result.extraResults.length, 1);
  assert.equal(result.extraResults[0].reason, 'ambiguous_duplicate_input_url');
});

test('dataset page cap makes Native Bulk completeness and run outcome UNKNOWN', async () => {
  const input = (await readTc02()).bulkUrls.slice(0, 1);
  const items = Array.from({ length: DATASET_PAGE_LIMIT }, (_, i) => ({ url: input[0], text: `Synthetic ${i}` }));
  const mapped = attributeBulkItems(input, items, { datasetComplete: false });
  assert.equal(mapped.bulkStatus, 'unknown');
  assert.equal(mapped.datasetComplete, false);
  assert.equal(mapped.inputs[0].status, 'duplicate_result');
});

test('Build mismatch stops before Dataset GET and never creates a second Run', async () => {
  const input = await readTc02(); const { dir, journal } = await setup();
  try {
    const transport = new FakeTransport([{ data: { id: 'bulk-mismatch-run', defaultDatasetId: 'bulk-mismatch-dataset', buildNumber: '0.0.51', buildId: 'unexpected' } }]);
    const result = await executeBulkInput({ transport, actorId, runInput: input, journal,
      maxTotalChargeUsd: '0.30', requireChargeCap: true, build: '0.0.50', requireBuild: true });
    assert.equal(result.executionStatus, 'transport_error');
    assert.equal(transport.postCount, 1); assert.equal(transport.getCount, 0);
    assert.equal((await journal.latest('bulk-mismatch-run')).stage, 'build_mismatch');
  } finally { await cleanup(dir); }
});

test('unknown create result, timeout and 429 each make one POST and no GET retry', async () => {
  const input = await readTc02();
  for (const failure of [new ApiError('ambiguous timeout', { ambiguous: true }), new ApiError('HTTP 429', { status: 429 }), { data: {} }]) {
    const { dir, journal } = await setup();
    try {
      const transport = new FakeTransport([failure]);
      const result = await executeBulkInput({ transport, actorId, runInput: input, journal,
        maxTotalChargeUsd: '0.30', requireChargeCap: true, build: '0.0.50', requireBuild: true });
      assert.equal(result.executionStatus, 'creation_unknown');
      assert.equal(transport.postCount, 1); assert.equal(transport.getCount, 0);
    } finally { await cleanup(dir); }
  }
});

test('Native Bulk Resume verifies fixture association and never posts', async () => {
  const input = await readTc02(); const { dir, journal } = await setup();
  try {
    await journal.append({ rowId: 'bulk-row', sourceUrl: 'native_bulk', actorId, runId: 'bulk-resume-run', datasetId: 'bulk-resume-dataset', inputContext: { mode: 'native_bulk', input }, buildVerification: 'verified', expectedBuildNumber: '0.0.50', actualBuildNumber: '0.0.50', actualBuildId: CONTROLLED_BUILD_ID, stage: 'complete', status: 'unknown' });
    const prior = await loadBulkResumeRecord(journal, 'bulk-resume-run', actorId, input, '0.0.50');
    const transport = new FakeTransport([
      { data: { status: 'SUCCEEDED', defaultDatasetId: 'bulk-resume-dataset', buildNumber: '0.0.50', buildId: CONTROLLED_BUILD_ID } },
      [{ url: input.bulkUrls[0], text: 'Synthetic transcript.' }, { url: input.bulkUrls[1], text: 'Synthetic transcript.' }, { url: input.bulkUrls[2], text: 'Synthetic transcript.' }],
    ]);
    const result = await executeBulkInput({ transport, actorId, runInput: input, journal, runId: prior.runId,
      datasetId: prior.datasetId, rowId: prior.rowId, resumeBuildRecord: prior, sleepFn: async () => {} });
    assert.equal(result.bulkStatus, 'all_success'); assert.equal(transport.postCount, 0);
    await assert.rejects(loadBulkResumeRecord(journal, 'bulk-resume-run', actorId, { ...input, resultsLimit: 11 }), /does not match/);
  } finally { await cleanup(dir); }
});

test('Run metadata archive is separate, private, credential-free, and preserves missing charges as null', async () => {
  const { dir } = await setup();
  try {
    const archive = new RunMetadataArchive(path.join(dir, 'nodejs-run-metadata.jsonl'));
    const record = createRunMetadataRecord({ apiRun: { status: 'SUCCEEDED', buildNumber: '0.0.50', buildId: CONTROLLED_BUILD_ID,
      defaultDatasetId: 'ds-meta', usageTotalUsd: null, chargedEventCounts: null, token: 'must-not-persist', sessionid: 'must-not-persist' },
      actorId, runId: 'run-meta', chargeCap: 0.3, chargeCapRequired: true, buildVerification: 'verified' });
    await archive.append(record);
    const text = await readFile(archive.file, 'utf8'); const saved = JSON.parse(text);
    if (process.platform !== 'win32') assert.equal((await stat(archive.file)).mode & 0o777, 0o600);
    else assert.equal((await stat(archive.file)).isFile(), true);
    assert.equal(saved.usageTotalUsd, null); assert.equal(saved.chargedEventCounts, null);
    assert.equal(saved.chargeCap.configuredValue, 0.3);
    assert.equal('token' in saved, false); assert.equal('sessionid' in saved, false);
    assert.equal(text.includes('must-not-persist'), false);
  } finally { await cleanup(dir); }
});

test('metadata archive failure does not mutate completed Run identity or business status', async () => {
  const input = (await readTc02()); const { dir, journal } = await setup();
  try {
    const transport = new FakeTransport(buildResponses(input.bulkUrls.map((url) => ({ url, text: 'Synthetic transcript.' }))));
    const result = await executeBulkInput({ transport, actorId, runInput: input, journal,
      maxTotalChargeUsd: '0.30', requireChargeCap: true, build: '0.0.50', requireBuild: true, sleepFn: async () => {} });
    const warnings = [];
    const archived = await archiveRunMetadataBestEffort({ append: async () => { throw new Error('synthetic disk failure'); } }, {}, (warning) => warnings.push(warning));
    assert.equal(archived, false); assert.equal(result.bulkStatus, 'all_success');
    assert.equal(result.runId, 'bulk-run-1'); assert.equal(transport.postCount, 1);
    assert.equal(warnings.length, 1);
  } finally { await cleanup(dir); }
});
