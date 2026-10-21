import test from 'node:test';
import assert from 'node:assert/strict';
import { chmod, mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { ApiError, CONTROLLED_BUILD_ID, CONTROLLED_BUILD_NUMBER, EXIT_CODES, RestTransport, RunJournal, buildRunInput, classifyItems, executeInput, loadResumeRecord, sanitize, summarize, validateBuildSelection, validateRunChargeCap, writePrivate } from '../../examples/nodejs/reliable-actor.mjs';
import { FakeTransport, loadFixture } from './offline-support.mjs';

const url = 'https://www.instagram.com/reel/synthetic-test/';
async function setup() { const dir = await mkdtemp(path.join(os.tmpdir(), 'reels-r02-')); return { dir, journal: new RunJournal(path.join(dir, 'runs.jsonl')) }; }
async function runOne(journal, responses, options = {}) {
  const transport = new FakeTransport(responses);
  const result = await executeInput({ transport, actorId: 'synthetic/actor', runInput: { videoUrl: url }, sourceUrl: url,
    journal, sleepFn: async () => {}, ...options });
  return { result, transport };
}
const cleanup = async (dir) => rm(dir, { recursive: true, force: true });

test('optional sessionid is omitted unless explicitly set', () => {
  assert.deepEqual(buildRunInput(url), { videoUrl: url });
  assert.deepEqual(buildRunInput(url, 'synthetic-session'), { videoUrl: url, sessionid: 'synthetic-session' });
});

test('charge cap is a Run query option and remains outside Actor input', async () => {
  assert.equal(validateRunChargeCap('0.30'), 0.3);
  const { dir, journal } = await setup();
  try {
    const { result, transport } = await runOne(journal, [
      { data: { id: 'run-capped', defaultDatasetId: 'ds-capped' } },
      { data: { status: 'SUCCEEDED', defaultDatasetId: 'ds-capped' } },
      [{ text: 'synthetic transcript' }],
    ], { maxTotalChargeUsd: '0.30', requireChargeCap: true });
    const post = transport.requests.find((request) => request.method === 'POST');
    assert.equal(result.status, 'success');
    assert.deepEqual(post.query, { maxTotalChargeUsd: 0.3, restartOnError: false });
    assert.deepEqual(post.body, { videoUrl: url });
  } finally { await cleanup(dir); }
});

test('fixed Build is sent only as a Run query option with charge and restart controls', async () => {
  assert.equal(validateBuildSelection('0.0.50', true), '0.0.50');
  const { dir, journal } = await setup();
  try {
    const { result, transport } = await runOne(journal, [
      { data: { id: 'run-build-query', defaultDatasetId: 'ds-build-query', buildNumber: '0.0.50', buildId: CONTROLLED_BUILD_ID } },
      { data: { status: 'SUCCEEDED', defaultDatasetId: 'ds-build-query', buildNumber: '0.0.50', buildId: CONTROLLED_BUILD_ID } },
      [{ text: 'synthetic transcript' }],
    ], { maxTotalChargeUsd: '0.30', requireChargeCap: true, build: '0.0.50', requireBuild: true });
    const post = transport.requests.find((request) => request.method === 'POST');
    assert.equal(result.status, 'success');
    assert.deepEqual(post.query, { maxTotalChargeUsd: 0.3, restartOnError: false, build: '0.0.50' });
    assert.deepEqual(post.body, { videoUrl: url });
    const saved = await journal.latest('run-build-query');
    assert.equal(saved.requestedBuild, '0.0.50');
    assert.equal(saved.actualBuildNumber, '0.0.50');
    assert.equal(saved.actualBuildId, CONTROLLED_BUILD_ID);
    assert.equal(saved.buildVerification, 'verified');
  } finally { await cleanup(dir); }
});

test('Build selection defaults to omitted and invalid or wrong fixed builds do not POST', async () => {
  assert.equal(validateBuildSelection(undefined, false), null);
  const defaultCase = await setup();
  try {
    const { transport } = await runOne(defaultCase.journal, [
      { data: { id: 'run-no-build', defaultDatasetId: 'ds-no-build' } },
      { data: { status: 'SUCCEEDED', defaultDatasetId: 'ds-no-build' } }, [{ text: 'synthetic transcript' }],
    ], { maxTotalChargeUsd: '0.30', requireChargeCap: true });
    assert.deepEqual(transport.requests[0].query, { maxTotalChargeUsd: 0.3, restartOnError: false });
  } finally { await cleanup(defaultCase.dir); }
  for (const build of [undefined, 'latest', 'not-a-version', '0.0.51']) {
    const { dir, journal } = await setup();
    try {
      const { result, transport } = await runOne(journal, [], { maxTotalChargeUsd: '0.30', requireChargeCap: true, build, requireBuild: true });
      assert.equal(result.status, 'transport_error', String(build));
      assert.equal(transport.postCount, 0, String(build));
    } finally { await cleanup(dir); }
  }
});

test('created Run Build mismatch retains identities and stops before Dataset without repost', async () => {
  const { dir, journal } = await setup();
  try {
    const { result, transport } = await runOne(journal, [
      { data: { id: 'run-build-mismatch', defaultDatasetId: 'ds-build-mismatch', buildNumber: '0.0.51', buildId: 'unexpected-build' } },
    ], { maxTotalChargeUsd: '0.30', requireChargeCap: true, build: '0.0.50', requireBuild: true });
    const saved = await journal.latest('run-build-mismatch');
    assert.equal(result.status, 'transport_error');
    assert.equal(result.runId, 'run-build-mismatch'); assert.equal(result.datasetId, 'ds-build-mismatch');
    assert.equal(transport.postCount, 1); assert.equal(transport.getCount, 0);
    assert.equal(saved.stage, 'build_mismatch'); assert.equal(saved.buildVerification, 'mismatch');
    assert.equal(saved.actualBuildNumber, '0.0.51'); assert.equal(saved.actualBuildId, 'unexpected-build');
  } finally { await cleanup(dir); }
});

test('missing POST Build identity is checked by GET on the same Run before Dataset access', async () => {
  const { dir, journal } = await setup();
  try {
    const { result, transport } = await runOne(journal, [
      { data: { id: 'run-build-get', defaultDatasetId: 'ds-build-get', options: { build: '0.0.50' } } },
      { data: { status: 'SUCCEEDED', defaultDatasetId: 'ds-build-get', buildNumber: '0.0.50', buildId: CONTROLLED_BUILD_ID } },
      [{ text: 'synthetic transcript' }],
    ], { maxTotalChargeUsd: '0.30', requireChargeCap: true, build: '0.0.50', requireBuild: true });
    assert.equal(result.status, 'success'); assert.equal(transport.postCount, 1);
    assert.deepEqual(transport.requests.map((request) => request.path), [
      '/acts/synthetic~actor/runs', '/actor-runs/run-build-get', '/datasets/ds-build-get/items',
    ]);
    assert.equal((await journal.latest('run-build-get')).buildVerification, 'verified');
  } finally { await cleanup(dir); }
});

test('Build request echo is not evidence and missing actual identity fails closed with IDs retained', async () => {
  const { dir, journal } = await setup();
  try {
    const { result, transport } = await runOne(journal, [
      { data: { id: 'run-build-unknown', defaultDatasetId: 'ds-build-unknown', options: { build: '0.0.50' } } },
      { data: { status: 'SUCCEEDED', defaultDatasetId: 'ds-build-unknown', options: { build: '0.0.50' } } },
    ], { maxTotalChargeUsd: '0.30', requireChargeCap: true, build: '0.0.50', requireBuild: true });
    const saved = await journal.latest('run-build-unknown');
    assert.equal(result.status, 'transport_error'); assert.equal(result.runId, 'run-build-unknown');
    assert.equal(result.datasetId, 'ds-build-unknown'); assert.equal(transport.postCount, 1);
    assert.equal(transport.requests.some((request) => request.path === '/datasets/ds-build-unknown/items'), false);
    assert.equal(saved.stage, 'build_unverified'); assert.equal(saved.buildVerification, 'unverified');
  } finally { await cleanup(dir); }
});

test('GET failure during Build verification preserves Run and does not POST again', async () => {
  const { dir, journal } = await setup();
  try {
    const { result, transport } = await runOne(journal, [
      { data: { id: 'run-build-get-fail', defaultDatasetId: 'ds-build-get-fail' } },
      new ApiError('temporary GET failure', { status: 503 }),
    ], { maxAttempts: 1, maxTotalChargeUsd: '0.30', requireChargeCap: true, build: '0.0.50', requireBuild: true });
    const saved = await journal.latest('run-build-get-fail');
    assert.equal(result.status, 'transport_error'); assert.equal(result.runId, 'run-build-get-fail');
    assert.equal(result.datasetId, 'ds-build-get-fail'); assert.equal(transport.postCount, 1);
    assert.equal(saved.stage, 'build_unverified'); assert.equal(saved.buildVerification, 'unverified');
  } finally { await cleanup(dir); }
});

test('Resume validates recorded Build identity and never creates another Run', async () => {
  const { dir, journal } = await setup();
  try {
    await journal.append({ rowId: 'row-build-resume', sourceUrl: url, actorId: 'synthetic/actor', runId: 'run-build-resume', datasetId: 'ds-build-resume', stage: 'build_verified', status: 'unknown', buildVerification: 'verified', requestedBuild: '0.0.50', expectedBuildNumber: '0.0.50', actualBuildNumber: '0.0.50', actualBuildId: CONTROLLED_BUILD_ID });
    const prior = await loadResumeRecord(journal, 'run-build-resume', 'synthetic/actor', '0.0.50');
    const { result, transport } = await runOne(journal, [
      { data: { status: 'SUCCEEDED', defaultDatasetId: 'ds-build-resume', buildNumber: '0.0.50', buildId: CONTROLLED_BUILD_ID } },
      [{ text: 'synthetic transcript' }],
    ], { runId: prior.runId, datasetId: prior.datasetId, rowId: prior.rowId, resumeBuildRecord: prior });
    assert.equal(result.status, 'success'); assert.equal(transport.postCount, 0);
    assert.equal(transport.getCount, 2);
    await assert.rejects(loadResumeRecord(journal, 'run-build-resume', 'synthetic/actor', '0.0.51'), /does not match/);
  } finally { await cleanup(dir); }
});

test('legacy Build-less journal resumes same Run safely and remains explicitly unverified', async () => {
  const { dir, journal } = await setup();
  try {
    await journal.append({ rowId: 'row-legacy', sourceUrl: url, actorId: 'synthetic/actor', runId: 'run-legacy', datasetId: 'ds-legacy', stage: 'run_created', status: 'unknown' });
    const prior = await loadResumeRecord(journal, 'run-legacy', 'synthetic/actor');
    const { result, transport } = await runOne(journal, [
      { data: { status: 'SUCCEEDED', defaultDatasetId: 'ds-legacy' } }, [{ text: 'synthetic transcript' }],
    ], { runId: prior.runId, datasetId: prior.datasetId, rowId: prior.rowId, resumeBuildRecord: prior });
    assert.equal(result.status, 'success'); assert.equal(transport.postCount, 0);
    assert.equal((await journal.latest('run-legacy')).buildVerification, 'legacy_unverified');
  } finally { await cleanup(dir); }
});

test('Python and Node live outputs and journals use separate files', async () => {
  const [nodeEntry, pythonEntry] = await Promise.all([
    readFile('examples/nodejs/single-url.mjs', 'utf8'), readFile('examples/python/single_url.py', 'utf8'),
  ]);
  assert.match(nodeEntry, /nodejs-run-journal\.jsonl/);
  assert.match(nodeEntry, /nodejs-single-url-response\.json/);
  assert.match(pythonEntry, /python-run-journal\.jsonl/);
  assert.match(pythonEntry, /python-single-url-response\.json/);
});

test('capped test mode missing or invalid amount never posts', async () => {
  for (const amount of [undefined, '', 'NaN', 'Infinity', '0', '-0.30', 'not-money']) {
    const { dir, journal } = await setup();
    try {
      const { result, transport } = await runOne(journal, [], { maxTotalChargeUsd: amount, requireChargeCap: true });
      assert.equal(result.status, 'transport_error', String(amount));
      assert.equal(transport.postCount, 0, String(amount));
    } finally { await cleanup(dir); }
  }
});

test('API rejecting Run cap does not retry POST', async () => {
  const { dir, journal } = await setup();
  try {
    const { result, transport } = await runOne(journal, [new ApiError('HTTP 400', { status: 400 })], { maxTotalChargeUsd: '0.30', requireChargeCap: true });
    assert.equal(result.status, 'transport_error');
    assert.equal(transport.postCount, 1);
  } finally { await cleanup(dir); }
});

test('resume does not require creation cap and never posts again', async () => {
  const { dir, journal } = await setup();
  try {
    await journal.append({ rowId: 'row-1', sourceUrl: url, actorId: 'synthetic/actor', runId: 'run-capped', datasetId: 'ds-capped', stage: 'run_created', status: 'unknown' });
    const { result, transport } = await runOne(journal, [
      { data: { status: 'SUCCEEDED', defaultDatasetId: 'ds-capped' } }, [{ text: 'synthetic transcript' }],
    ], { runId: 'run-capped', datasetId: 'ds-capped', rowId: 'row-1', requireChargeCap: true });
    assert.equal(result.status, 'success');
    assert.equal(transport.postCount, 0);
  } finally { await cleanup(dir); }
});

test('classifies transcript, errMsg, empty dataset, metadata-only and null/missing text', async () => {
  assert.equal(classifyItems((await loadFixture('transcript-success.synthetic.json')).items)[0], 'success');
  assert.equal(classifyItems((await loadFixture('transcript-error.synthetic.json')).items)[0], 'actor_error');
  assert.equal(classifyItems((await loadFixture('dataset-empty.synthetic.json')).items)[0], 'empty');
  assert.equal(classifyItems((await loadFixture('metadata-no-text.synthetic.json')).items)[0], 'no_transcript');
  assert.equal(classifyItems([{ text: null }])[0], 'no_transcript');
  assert.equal(classifyItems([{}])[0], 'no_transcript');
  assert.equal(classifyItems([{ text: 0 }])[0], 'unknown');
  assert.equal(EXIT_CODES.success, 0); assert.notEqual(EXIT_CODES.actor_error, 0); assert.notEqual(EXIT_CODES.no_transcript, 0);
});

test('REST transport builds authorized Actor path and JSON body', async () => {
  let captured;
  const transport = new RestTransport('synthetic-token', { fetchImpl: async (url, options) => {
    captured = { url, options };
    return { ok: true, status: 200, json: async () => ({ data: { id: 'run-http', defaultDatasetId: 'ds-http' } }) };
  } });
  const result = await transport.request('POST', '/acts/synthetic~actor/runs', { videoUrl: url }, 30_000, { maxTotalChargeUsd: 0.3, restartOnError: false });
  assert.equal(result.data.id, 'run-http');
  assert.equal(captured.url, 'https://api.apify.com/v2/acts/synthetic~actor/runs?maxTotalChargeUsd=0.3&restartOnError=false');
  assert.equal(captured.options.headers.Authorization, 'Bearer synthetic-token');
  assert.deepEqual(JSON.parse(captured.options.body), { videoUrl: url });
  assert.ok(captured.options.signal);
});

test('Run creation, polling, and Dataset reads share the configured REST fetch transport', async () => {
  const calls = [];
  const replies = [
    { data: { id: 'run-shared-transport', defaultDatasetId: 'ds-shared-transport' } },
    { data: { status: 'SUCCEEDED', defaultDatasetId: 'ds-shared-transport' } },
    [{ text: 'synthetic transcript' }],
  ];
  const transport = new RestTransport('synthetic-token', { fetchImpl: async (requestUrl, options) => {
    calls.push({ requestUrl, options });
    return { ok: true, status: 200, headers: new Headers(), json: async () => replies.shift() };
  } });
  const { dir, journal } = await setup();
  try {
    const result = await executeInput({ transport, actorId: 'synthetic/actor', runInput: { videoUrl: url }, sourceUrl: url,
      journal, maxTotalChargeUsd: '0.30', requireChargeCap: true, sleepFn: async () => {} });
    assert.equal(result.status, 'success');
    assert.deepEqual(calls.map(({ options }) => options.method), ['POST', 'GET', 'GET']);
    assert.match(calls[0].requestUrl, /\/acts\/synthetic~actor\/runs\?maxTotalChargeUsd=0\.3&restartOnError=false$/);
    assert.match(calls[1].requestUrl, /\/actor-runs\/run-shared-transport$/);
    assert.match(calls[2].requestUrl, /\/datasets\/ds-shared-transport\/items$/);
    assert.ok(calls.every(({ options }) => options.headers.Authorization === 'Bearer synthetic-token'));
    assert.ok(calls.every(({ requestUrl }) => !requestUrl.includes('synthetic-token')));
    assert.deepEqual(JSON.parse(calls[0].options.body), { videoUrl: url });
  } finally { await cleanup(dir); }
});

test('run status GET failure retries same run without another POST', async () => {
  const { dir, journal } = await setup();
  try {
    const { result, transport } = await runOne(journal, [
      { data: { id: 'run-1', defaultDatasetId: 'ds-1' } }, new ApiError('temporary', { status: 503 }),
      { data: { id: 'run-1', status: 'SUCCEEDED', defaultDatasetId: 'ds-1' } }, (await loadFixture('transcript-success.synthetic.json')).items,
    ]);
    assert.equal(result.status, 'success'); assert.equal(transport.postCount, 1); assert.equal(transport.getCount, 3);
    assert.equal(transport.requests[0].query, null);
    assert.equal(transport.requests[1].path, '/actor-runs/run-1');
    assert.equal(transport.requests[2].path, '/actor-runs/run-1');
    assert.equal(transport.requests[3].path, '/datasets/ds-1/items');
  } finally { await cleanup(dir); }
});

test('GET 429 retries same Run while keeping POST count at one', async () => {
  const { dir, journal } = await setup();
  try {
    const { result, transport } = await runOne(journal, [
      { data: { id: 'run-429-get', defaultDatasetId: 'ds-429-get' } }, new ApiError('rate limited', { status: 429, retryAfter: 0 }),
      { data: { status: 'SUCCEEDED', defaultDatasetId: 'ds-429-get' } }, (await loadFixture('transcript-success.synthetic.json')).items,
    ]);
    assert.equal(result.status, 'success'); assert.equal(transport.postCount, 1); assert.equal(transport.getCount, 3);
  } finally { await cleanup(dir); }
});

test('resume rejects a Dataset ID that disagrees with the Run record', async () => {
  const { dir, journal } = await setup();
  try {
    const { result, transport } = await runOne(journal, [{ data: { status: 'SUCCEEDED', defaultDatasetId: 'ds-actual' } }], { runId: 'run-mismatch', datasetId: 'ds-from-journal' });
    assert.equal(result.status, 'transport_error'); assert.equal(transport.postCount, 0); assert.equal(transport.getCount, 1);
  } finally { await cleanup(dir); }
});

test('dataset timeout retries dataset GET only', async () => {
  const { dir, journal } = await setup();
  try {
    const { result, transport } = await runOne(journal, [
      { data: { id: 'run-2', defaultDatasetId: 'ds-2' } }, { data: { status: 'SUCCEEDED', defaultDatasetId: 'ds-2' } },
      new ApiError('temporary', { status: 503 }), (await loadFixture('transcript-success.synthetic.json')).items,
    ]);
    assert.equal(result.status, 'success'); assert.equal(transport.postCount, 1); assert.equal(transport.getCount, 3);
  } finally { await cleanup(dir); }
});

test('ambiguous POST response becomes creation_unknown without retry', async () => {
  const { dir, journal } = await setup();
  try {
    const { result, transport } = await runOne(journal, [new ApiError('timeout', { ambiguous: true })]);
    assert.equal(result.status, 'creation_unknown'); assert.equal(result.runId, null); assert.equal(transport.postCount, 1);
  } finally { await cleanup(dir); }
});

test('401 and 403 permanently stop creation retries', async () => {
  const { dir, journal } = await setup();
  try {
    for (const status of [401, 403]) {
      const { result, transport } = await runOne(journal, [new ApiError(`HTTP ${status}`, { status })]);
      assert.equal(result.status, 'transport_error'); assert.equal(transport.postCount, 1);
    }
  } finally { await cleanup(dir); }
});

test('429 creation is not retried while acceptance semantics are unverified', async () => {
  const { dir, journal } = await setup();
  try {
    const { result, transport } = await runOne(journal, [new ApiError('rate limited', { status: 429 })], { maxAttempts: 4, maxTotalChargeUsd: '0.30', requireChargeCap: true });
    assert.equal(result.status, 'creation_unknown'); assert.equal(transport.postCount, 1);
  } finally { await cleanup(dir); }
});

test('successful run without transcript never starts another run', async () => {
  const { dir, journal } = await setup();
  try {
    const { result, transport } = await runOne(journal, [
      { data: { id: 'run-3', defaultDatasetId: 'ds-3' } }, { data: { status: 'SUCCEEDED', defaultDatasetId: 'ds-3' } },
      (await loadFixture('metadata-no-text.synthetic.json')).items,
    ]);
    assert.equal(result.status, 'no_transcript'); assert.equal(transport.postCount, 1);
  } finally { await cleanup(dir); }
});

test('durable journal retains IDs for resume after caller output failure', async () => {
  const { dir, journal } = await setup();
  try {
    const first = await runOne(journal, [{ data: { id: 'run-4', defaultDatasetId: 'ds-4' } }, { data: { status: 'SUCCEEDED', defaultDatasetId: 'ds-4' } }, new ApiError('dataset unavailable', { status: 503 })], { maxAttempts: 1 });
    assert.equal(first.result.status, 'transport_error');
    const saved = await journal.latest('run-4'); assert.equal(saved.datasetId, 'ds-4');
    const resumed = await runOne(journal, [{ data: { status: 'SUCCEEDED', defaultDatasetId: 'ds-4' } }, (await loadFixture('transcript-success.synthetic.json')).items], { runId: saved.runId, datasetId: saved.datasetId });
    assert.equal(resumed.result.status, 'success'); assert.equal(resumed.transport.postCount, 0); assert.equal(first.transport.postCount + resumed.transport.postCount, 1);
  } finally { await cleanup(dir); }
});

test('empty Dataset reads are rechecked on the same Run before final classification', async () => {
  const { dir, journal } = await setup();
  try {
    const ready = await runOne(journal, [{ data: { id: 'run-empty-lag', defaultDatasetId: 'ds-empty-lag' } }, { data: { status: 'SUCCEEDED', defaultDatasetId: 'ds-empty-lag' } }, [], (await loadFixture('transcript-success.synthetic.json')).items]);
    assert.equal(ready.result.status, 'success'); assert.equal(ready.transport.postCount, 1);
    const empty = await runOne(journal, [{ data: { id: 'run-empty-final', defaultDatasetId: 'ds-empty-final' } }, { data: { status: 'SUCCEEDED', defaultDatasetId: 'ds-empty-final' } }, [], [], []]);
    assert.equal(empty.result.status, 'empty'); assert.equal(empty.transport.postCount, 1); assert.equal(empty.transport.getCount, 4);
  } finally { await cleanup(dir); }
});

test('resume record must match Actor, Run ID, and source association', async () => {
  const { dir, journal } = await setup();
  try {
    await journal.append({ rowId: 'row-2', sourceUrl: url, actorId: 'synthetic/actor', runId: 'run-bound', datasetId: 'ds-bound', stage: 'run_created' });
    assert.equal((await loadResumeRecord(journal, 'run-bound', 'synthetic/actor')).sourceUrl, url);
    await assert.rejects(loadResumeRecord(journal, 'run-bound', 'other/actor'), /does not match/);
    await assert.rejects(loadResumeRecord(journal, 'missing-run', 'synthetic/actor'), /No journal record/);
  } finally { await cleanup(dir); }
});

test('journal tightens existing permissions and refuses corrupted records', async () => {
  const { dir, journal } = await setup();
  try {
    await writeFile(journal.file, '{}\n', { mode: 0o644 }); await chmod(journal.file, 0o644);
    await journal.append({ runId: 'safe' });
    assert.equal((await stat(journal.file)).mode & 0o777, 0o600);
    await writeFile(journal.file, '{truncated\n', { flag: 'a' });
    await assert.rejects(journal.latest('safe'), /corrupt/);
  } finally { await cleanup(dir); }
});

test('corrupt journal prevents a new paid POST', async () => {
  const { dir, journal } = await setup();
  try {
    await writeFile(journal.file, '{truncated\n');
    const { result, transport } = await runOne(journal, [{ data: { id: 'must-not-be-created' } }]);
    assert.equal(result.status, 'transport_error'); assert.equal(transport.postCount, 0);
  } finally { await cleanup(dir); }
});

test('persisted data sanitizer removes credential fields and assignments', () => {
  const cleaned = sanitize({ session_id: 'secret-cookie', nested: { access_token: 'secret-token', note: 'Bearer abc123 token=xyz' } });
  assert.equal('session_id' in cleaned, false);
  assert.equal('access_token' in cleaned.nested, false);
  assert.equal(cleaned.nested.note.includes('abc123'), false);
  assert.equal(cleaned.nested.note.includes('xyz'), false);
});

test('private output writer restricts existing files before writing', async () => {
  const { dir } = await setup();
  try {
    const file = path.join(dir, 'result.json'); await writeFile(file, 'old'); await chmod(file, 0o644);
    await writePrivate(file, 'sanitized');
    assert.equal((await stat(file)).mode & 0o777, 0o600);
    assert.equal(await readFile(file, 'utf8'), 'sanitized');
  } finally { await cleanup(dir); }
});

test('batch summary counts mixed statuses exactly', () => {
  const statuses = ['success', 'actor_error', 'empty', 'no_transcript', 'unknown', 'transport_error', 'run_failed', 'creation_unknown'];
  const counts = summarize(statuses.map((status) => ({ status })));
  assert.equal(counts.processed, statuses.length);
  assert.equal(statuses.reduce((sum, status) => sum + counts[status], 0), statuses.length);
  assert.equal(counts.failed, statuses.length - counts.success);
});
