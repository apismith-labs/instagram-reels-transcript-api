import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { CONTROLLED_BUILD_ID, CONTROLLED_BUILD_NUMBER, DATASET_PAGE_LIMIT, profilePost, validateProfileInput } from '../../examples/nodejs/reliable-actor.mjs';
import { ClientCreationUnknownError, ClientConfigurationError, ClientTransportError, getProfilePosts, getTranscript, getTranscripts } from '../../examples/nodejs/client.mjs';
import { main as profileMain, parseArgs as parseProfileArgs } from '../../examples/nodejs/profile.mjs';
import { FakeTransport } from './offline-support.mjs';

const actorId = 'apple_yang/instagram-transcripts-scraper';
const profileUrl = 'https://www.instagram.com/p/synthetic-profile-post/';
function responseQueue(items, { status = 'SUCCEEDED', buildNumber = CONTROLLED_BUILD_NUMBER, buildId = CONTROLLED_BUILD_ID } = {}) {
  return [
    { data: { id: 'synthetic-run', defaultDatasetId: 'synthetic-dataset', buildNumber, buildId } },
    { data: { id: 'synthetic-run', status, defaultDatasetId: 'synthetic-dataset', buildNumber, buildId } },
    items, items, items,
  ];
}
const baseOptions = (transport, extra = {}) => ({ token: 'synthetic-token', actorId, transport, sleepFn: async () => {}, ...extra });

test('validateProfileInput builds single and multi-account Actor input with options', () => {
  assert.deepEqual(validateProfileInput('creator', { resultsLimit: 2 }), { usernames: ['creator'], resultsLimit: 2 });
  assert.deepEqual(validateProfileInput(['creator_a', 'creator.b'], { onlyPostsNewerThan: '7 days', skipPinnedPosts: true, includeSharesCount: false }),
    { usernames: ['creator_a', 'creator.b'], onlyPostsNewerThan: '7 days', skipPinnedPosts: true, includeSharesCount: false });
  assert.throws(() => validateProfileInput(['alice', 'ALICE']), /duplicates/);
});

test('Profile input rejects empty, invalid, duplicate, mixed-mode, and invalid option values', () => {
  for (const usernames of [[], [''], ['@alice'], ['a b'], ['.alice'], ['alice..smith'], ['alice', 'ALICE'], null]) assert.throws(() => validateProfileInput(usernames));
  for (const options of [
    { resultsLimit: 0 }, { resultsLimit: 1.2 }, { resultsLimit: true }, { onlyPostsNewerThan: '2026-02-30' },
    { onlyPostsNewerThan: '2026-10-22T00:00:00Z' }, { onlyPostsNewerThan: '0 days' },
    { skipPinnedPosts: 1 }, { includeSharesCount: 'false' }, { videoUrl: profileUrl }, { bulkUrls: [profileUrl] },
  ]) assert.throws(() => validateProfileInput('alice', options));
});

test('Profile attribution uses ownerUsername only and never guesses from userName or item order', () => {
  const matched = profilePost({ url: profileUrl, type: 'Image', ownerUsername: 'alice', userName: 'other' }, ['alice', 'bob']);
  assert.equal(matched.status, 'success'); assert.equal(matched.ownerUsername, 'alice');
  const missingOwnerSingle = profilePost({ url: profileUrl, type: 'Video' }, ['alice']);
  assert.equal(missingOwnerSingle.status, 'success');
  assert.equal(profilePost({ url: profileUrl, type: 'Image', ownerUsername: 'bob' }, ['alice']).status, 'unknown');
  for (const item of [
    { url: profileUrl, type: 'Image' },
    { url: profileUrl, type: 'Image', userName: 'alice' },
    { url: profileUrl, type: 'Image', ownerUsername: 'outside' },
  ]) assert.equal(profilePost(item, ['alice', 'bob']).status, 'unknown');
});

test('Profile post preserves raw metadata, accepts no transcript, and validates duration type', () => {
  const item = { url: profileUrl, type: 'Video', ownerUsername: 'alice', caption: 'synthetic caption', timestamp: 'opaque-time', videoDuration: 4.5, extraField: 7 };
  const post = profilePost(item, ['alice']);
  assert.equal(post.status, 'success'); assert.equal(post.raw, item); assert.equal(post.timestamp, 'opaque-time');
  assert.equal(post.videoDuration, 4.5); assert.equal(Object.hasOwn(post.raw, 'text'), false);
  assert.equal(profilePost({ ...item, videoDuration: Infinity }, ['alice']).videoDuration, null);
  assert.equal(profilePost({ ...item, errMsg: 'synthetic actor failure' }, ['alice']).status, 'actor_error');
  assert.equal(profilePost({ url: 'not-a-post', type: 'Image' }, ['alice']).status, 'unknown');
});

test('Profile CLI parses explicit usernames and rejects no usernames before credentials', async () => {
  assert.deepEqual(parseProfileArgs(['alice', 'bob', '--results-limit', '2']).runInput, { usernames: ['alice', 'bob'], resultsLimit: 2 });
  assert.throws(() => parseProfileArgs([]), /At least one explicit username/);
  assert.throws(() => parseProfileArgs(['alice', '--unexpected']), /Unknown option/);
  const transport = new FakeTransport([]); const lines = [];
  assert.equal(await profileMain(['--help'], { env: {}, transport, print: (line) => lines.push(line) }), 0);
  assert.match(lines[0], /Usage:/); assert.equal(transport.postCount, 0);
  let loadEnvCalled = false;
  const errors = [];
  assert.equal(await profileMain(['alice', '--results-limit', '0'], { env: { APIFY_TOKEN: 'synthetic' }, transport,
    loadEnv() { loadEnvCalled = true; }, error: (message) => errors.push(message) }), 2);
  assert.equal(loadEnvCalled, false); assert.equal(errors.length, 1);
  assert.equal(transport.postCount, 0);
});

test('Profile CLI rejects every missing or invalid valued option before env loading or POST', async () => {
  const invalidArgv = [
    ['alice', '--only-posts-newer-than'],
    ['alice', '--only-posts-newer-than', '--skip-pinned-posts'],
    ['alice', '--only-posts-newer-than', ''],
    ['alice', '--only-posts-newer-than', '2026-02-30'],
    ['alice', '--results-limit'],
    ['alice', '--results-limit', '--include-shares-count'],
    ['--resume'],
  ];
  for (const argv of invalidArgv) {
    let loadEnvCalled = false; const transport = new FakeTransport([]); const errors = [];
    const code = await profileMain(argv, { env: { APIFY_TOKEN: 'synthetic-token' }, transport,
      loadEnv: () => { loadEnvCalled = true; }, error: (message) => errors.push(message) });
    assert.equal(code, 2, argv.join(' ')); assert.equal(loadEnvCalled, false); assert.equal(transport.postCount, 0);
    assert.equal(errors.length, 1);
  }
  assert.deepEqual(parseProfileArgs(['alice', '--only-posts-newer-than', '2026-10-20']).runInput,
    { usernames: ['alice'], onlyPostsNewerThan: '2026-10-20' });
  assert.deepEqual(parseProfileArgs(['alice', '--only-posts-newer-than', '7 days']).runInput,
    { usernames: ['alice'], onlyPostsNewerThan: '7 days' });
});

test('Profile boolean flags reject adjacent values before env loading or POST', async () => {
  for (const argv of [
    ['alice', '--skip-pinned-posts', 'true'],
    ['alice', '--skip-pinned-posts', 'false'],
    ['alice', '--include-shares-count', '1'],
    ['alice', '--include-shares-count', '0'],
  ]) {
    let loadEnvCalled = false; const transport = new FakeTransport([]); const errors = [];
    const code = await profileMain(argv, { env: { APIFY_TOKEN: 'synthetic-token' }, transport,
      loadEnv: () => { loadEnvCalled = true; }, error: (message) => errors.push(message) });
    assert.equal(code, 2, argv.join(' ')); assert.equal(loadEnvCalled, false); assert.equal(transport.postCount, 0);
    assert.match(errors[0], /does not accept a value/);
  }
  assert.deepEqual(parseProfileArgs(['alice', '--skip-pinned-posts']).runInput,
    { usernames: ['alice'], skipPinnedPosts: true });
  assert.deepEqual(parseProfileArgs(['alice', '--include-shares-count']).runInput,
    { usernames: ['alice'], includeSharesCount: true });
  assert.deepEqual(parseProfileArgs(['alice', 'bob', '--skip-pinned-posts']).runInput,
    { usernames: ['alice', 'bob'], skipPinnedPosts: true });
  assert.deepEqual(parseProfileArgs(['true']).runInput, { usernames: ['true'] });
});

test('Profile boolean flags and multiple usernames reach one Fake Actor Input as intended', async () => {
  const transport = new FakeTransport(responseQueue([{ url: profileUrl, type: 'Image', ownerUsername: 'alice' }]));
  const code = await profileMain(['alice', 'bob', '--skip-pinned-posts', '--include-shares-count'], {
    env: { APIFY_TOKEN: 'synthetic-token' }, transport, loadEnv() {},
    journal: { append: async () => {}, latest: async () => null },
    writeOutput: async () => 'synthetic-output.json', print() {},
  });
  assert.equal(code, 0); assert.equal(transport.postCount, 1);
  assert.deepEqual(transport.requests[0].body, { usernames: ['alice', 'bob'], skipPinnedPosts: true, includeSharesCount: true });
});

test('Profile CLI persists Profile contract with real unique private-file writes', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'profile-persisted-contract-'));
  const baseOutput = path.join(directory, 'profile.json');
  const sentinel = 'keep prior output';
  await writeFile(baseOutput, sentinel, { mode: 0o600 });
  const journalRecord = {
    actualBuildNumber: CONTROLLED_BUILD_NUMBER, actualBuildId: CONTROLLED_BUILD_ID,
    buildVerification: 'verified',
  };
  const cases = [
    { items: [{ url: profileUrl, type: 'Image', ownerUsername: 'alice', caption: 'synthetic', timestamp: 'opaque', extra: 7 }], status: 'success', code: 0 },
    { items: [{ url: profileUrl, errMsg: 'synthetic actor failure' }], status: 'actor_error', code: 4 },
    { items: Array.from({ length: DATASET_PAGE_LIMIT }, (_, index) => ({ url: `https://www.instagram.com/p/synthetic-${index}/`, type: 'Image', ownerUsername: 'alice' })), status: 'unknown', code: 7 },
  ];
  try {
    const savedPaths = [];
    for (const scenario of cases) {
      const transport = new FakeTransport(responseQueue(scenario.items));
      const stdout = [];
      const code = await profileMain(['alice'], {
        env: { APIFY_TOKEN: 'synthetic-token', APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD: '1', APIFY_MAX_TOTAL_CHARGE_USD: '0.30' },
        transport, loadEnv() {}, outputFile: baseOutput,
        journal: { append: async () => {}, latest: async () => journalRecord },
        print: (line) => stdout.push(line),
      });
      assert.equal(code, scenario.code);
      assert.equal(transport.postCount, 1);
      const summary = JSON.parse(stdout[0]);
      assert.equal(summary.status, scenario.status);
      assert.equal(summary.runStatus, 'SUCCEEDED');
      assert.equal(summary.buildNumber, CONTROLLED_BUILD_NUMBER);
      assert.equal(summary.buildId, CONTROLLED_BUILD_ID);
      assert.equal(summary.buildVerification, 'verified');
      assert.equal(summary.usernames[0], 'alice');
      assert.deepEqual(Object.keys(summary).sort(), ['mode', 'status', 'runStatus', 'runId', 'datasetId', 'buildNumber', 'buildId', 'buildVerification', 'usernames', 'datasetComplete', 'postCount', 'posts', 'error', 'outputFile'].sort());
      const outputPath = summary.outputFile;
      savedPaths.push(outputPath);
      const persisted = JSON.parse(await readFile(outputPath, 'utf8'));
      assert.equal(persisted.status, scenario.status);
      assert.equal(persisted.runStatus, 'SUCCEEDED');
      assert.equal(Object.hasOwn(persisted, 'executionStatus'), false);
      assert.equal(persisted.buildNumber, CONTROLLED_BUILD_NUMBER);
      assert.equal(persisted.buildId, CONTROLLED_BUILD_ID);
      assert.equal(persisted.buildVerification, 'verified');
      assert.deepEqual(persisted.usernames, ['alice']);
      assert.equal(persisted.runId, 'synthetic-run');
      assert.equal(persisted.datasetId, 'synthetic-dataset');
      assert.ok(Array.isArray(persisted.posts));
      assert.ok(Array.isArray(persisted.rawItems));
      assert.equal(persisted.rawItems.length, scenario.items.length);
      assert.deepEqual(persisted.rawItems[0], scenario.items[0]);
      assert.equal(persisted.datasetComplete, scenario.status !== 'unknown');
      if (scenario.status === 'success') {
        assert.equal(persisted.posts[0].status, 'success');
        assert.equal(Object.hasOwn(persisted.rawItems[0], 'text'), false);
        assert.equal(Object.hasOwn(persisted.rawItems[0], 'segments'), false);
        assert.equal(persisted.counts.success, 1);
      }
      if (scenario.status === 'actor_error') {
        assert.equal(persisted.posts[0].status, 'actor_error');
        assert.match(persisted.rawItems[0].errMsg, /synthetic actor failure/);
      }
      if (scenario.status === 'unknown') assert.equal(persisted.datasetComplete, false);
      if (process.platform !== 'win32') assert.equal((await stat(outputPath)).mode & 0o777, 0o600);
    }
    assert.equal(new Set(savedPaths).size, savedPaths.length);
    assert.equal(await readFile(baseOutput, 'utf8'), sentinel);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test('Profile CLI preserves creation-unknown and never retries its POST', async () => {
  const transport = new FakeTransport([new Error('synthetic timeout')]);
  const output = [];
  const code = await profileMain(['alice'], {
    env: { APIFY_TOKEN: 'synthetic-token' }, transport, loadEnv() {},
    journal: { append: async () => {}, latest: async () => null },
    writeOutput: async (_file, content) => { output.push(content); return 'synthetic-output.json'; },
    print() {},
  });
  assert.equal(code, 10);
  assert.equal(transport.postCount, 1);
  const persisted = JSON.parse(output[0]);
  assert.equal(persisted.status, 'creation_unknown');
  assert.equal(Object.hasOwn(persisted, 'executionStatus'), false);
});

test('Profile Resume is always rejected with the precise unsupported message before env or POST', async () => {
  for (const argv of [['--resume'], ['--resume', 'synthetic-run']]) {
    let loadEnvCalled = false; const transport = new FakeTransport([]); const errors = [];
    const code = await profileMain(argv, { env: { APIFY_TOKEN: 'synthetic-token' }, transport,
      loadEnv: () => { loadEnvCalled = true; }, error: (message) => errors.push(message) });
    assert.equal(code, 2); assert.equal(errors[0], 'Profile Resume is not supported');
    assert.equal(loadEnvCalled, false); assert.equal(transport.postCount, 0);
  }
});

test('Profile client makes one safe Run and returns metadata without transcript fields', async () => {
  const item = { url: profileUrl, type: 'Video', ownerUsername: 'alice', caption: 'synthetic', timestamp: 1234, videoDuration: 9, extra: 'kept' };
  const transport = new FakeTransport(responseQueue([item]));
  const result = await getProfilePosts('alice', baseOptions(transport, { resultsLimit: 1, maxTotalChargeUsd: '0.30', requireChargeCap: true }));
  assert.equal(transport.postCount, 1); assert.equal(result.status, 'success'); assert.equal(result.posts[0].status, 'success');
  assert.equal(Object.hasOwn(transport.requests[0].body, 'videoUrl'), false);
  assert.deepEqual(transport.requests[0].body, { usernames: ['alice'], resultsLimit: 1 });
  assert.deepEqual(transport.requests[0].query, { restartOnError: false, maxTotalChargeUsd: 0.3, build: CONTROLLED_BUILD_NUMBER });
  assert.equal(result.buildId, CONTROLLED_BUILD_ID); assert.equal(result.buildVerification, 'verified');
  assert.equal(result.runStatus, 'SUCCEEDED'); assert.equal(Object.hasOwn(result, 'executionStatus'), false);
  assert.equal(result.posts[0].raw.extra, 'kept'); assert.equal(Object.hasOwn(result.posts[0].raw, 'text'), false);
});

test('Profile client classifies empty, actor_error, and incomplete datasets distinctly', async () => {
  for (const [items, expected, complete] of [[[], 'empty', true], [[{ url: profileUrl, errMsg: 'synthetic failure' }], 'actor_error', true], [[{ url: profileUrl, type: 'Image' }], 'unknown', false]]) {
    const transport = new FakeTransport(responseQueue(items));
    if (!complete) {
      // The runner marks a full page incomplete; configure the page limit to match this one-item response.
      const result = await getProfilePosts('alice', baseOptions(transport, { datasetPageLimit: 1 }));
      assert.equal(result.status, expected); assert.equal(result.datasetComplete, false); continue;
    }
    const result = await getProfilePosts('alice', baseOptions(transport));
    assert.equal(result.status, expected); assert.equal(result.datasetComplete, true);
    if (expected === 'actor_error') assert.equal(result.posts[0].status, 'actor_error');
  }
});

test('Reusable client validates before credentials or POST and honors configuration gates', async () => {
  const transport = new FakeTransport([]);
  await assert.rejects(getTranscript('[bad](https://www.instagram.com/reel/x/)', baseOptions(transport)));
  await assert.rejects(getProfilePosts([], baseOptions(transport)));
  await assert.rejects(getTranscripts([], baseOptions(transport)));
  await assert.rejects(getTranscript('https://www.instagram.com/reel/synthetic/', { ...baseOptions(transport), token: '' }), ClientConfigurationError);
  await assert.rejects(getTranscript('https://www.instagram.com/reel/synthetic/', { ...baseOptions(transport), build: 'latest' }), ClientConfigurationError);
  await assert.rejects(getTranscript('https://www.instagram.com/reel/synthetic/', { ...baseOptions(transport), requireChargeCap: true }), ClientConfigurationError);
  await assert.rejects(getProfilePosts('alice', { ...baseOptions(transport), bulkUrls: ['https://www.instagram.com/reel/synthetic/'] }), ClientConfigurationError);
  await assert.rejects(getTranscript('https://www.instagram.com/reel/synthetic/', { ...baseOptions(transport), usernames: ['alice'] }), ClientConfigurationError);
  assert.equal(transport.postCount, 0);
});

test('getTranscript returns stable transcript fields with Build evidence', async () => {
  const item = { text: 'synthetic transcript', segments: [{ start: 0, end: 1, text: 'synthetic' }], title: 'kept' };
  const transport = new FakeTransport(responseQueue([item]));
  const result = await getTranscript('https://www.instagram.com/reel/synthetic/', baseOptions(transport));
  assert.equal(transport.postCount, 1); assert.equal(result.status, 'success');
  assert.equal(result.text, item.text); assert.deepEqual(result.segments, item.segments); assert.equal(result.items[0].title, 'kept');
  assert.deepEqual(transport.requests[0].body, { videoUrl: 'https://www.instagram.com/reel/synthetic/' });
  assert.equal(transport.requests[0].query.restartOnError, false); assert.equal(result.buildVerification, 'verified');
});

test('getTranscripts performs one Native Bulk POST and exposes aggregate attribution', async () => {
  const urls = ['https://www.instagram.com/reel/one/', 'https://www.instagram.com/reel/two/'];
  const items = [{ url: urls[1], text: 'second transcript' }, { url: urls[0], text: 'first transcript' }];
  const transport = new FakeTransport(responseQueue(items));
  const result = await getTranscripts(urls, baseOptions(transport, { resultsLimit: 2 }));
  assert.equal(transport.postCount, 1); assert.equal(result.status, 'all_success');
  assert.deepEqual(transport.requests[0].body, { bulkUrls: urls, resultsLimit: 2 });
  assert.deepEqual(result.results.map((row) => row.status), ['success_transcript', 'success_transcript']);
});

test('Profile business metadata with no text is independent from Transcript status', async () => {
  const transport = new FakeTransport(responseQueue([{ url: profileUrl, type: 'Image', ownerUsername: 'alice' }]));
  const result = await getProfilePosts('alice', baseOptions(transport));
  assert.equal(result.status, 'success'); assert.equal(result.posts[0].status, 'success');
  assert.equal(result.runStatus, 'SUCCEEDED'); assert.notEqual(result.executionStatus, 'no_transcript');
  assert.equal(Object.hasOwn(result, 'executionStatus'), false);
});

test('Transcript API retains its existing no_transcript status semantics', async () => {
  const transport = new FakeTransport(responseQueue([{ title: 'metadata only' }]));
  const result = await getTranscript('https://www.instagram.com/reel/synthetic/', baseOptions(transport));
  assert.equal(result.status, 'no_transcript'); assert.equal(result.executionStatus, 'no_transcript');
});

test('POST outcome unknown is surfaced as a typed non-retryable error', async () => {
  const transport = new FakeTransport([new Error('synthetic timeout')]);
  await assert.rejects(getTranscript('https://www.instagram.com/reel/synthetic/', baseOptions(transport)), ClientCreationUnknownError);
  assert.equal(transport.postCount, 1);
});

test('known Run GET failure maps to a typed transport error and never repeats POST', async () => {
  const transport = new FakeTransport([
    { data: { id: 'synthetic-run', defaultDatasetId: 'synthetic-dataset', buildNumber: CONTROLLED_BUILD_NUMBER, buildId: CONTROLLED_BUILD_ID } },
    new Error('synthetic GET failure'),
  ]);
  await assert.rejects(getTranscripts(['https://www.instagram.com/reel/synthetic/'],
    baseOptions(transport, { maxAttempts: 1 })), (error) => {
      assert.ok(error instanceof ClientTransportError);
      assert.equal(error.result.runId, 'synthetic-run');
      assert.equal(error.result.datasetId, 'synthetic-dataset');
      return true;
    });
  assert.equal(transport.postCount, 1);
});

test('Client module import does not call fetch', async () => {
  const originalFetch = globalThis.fetch; let calls = 0;
  globalThis.fetch = async () => { calls += 1; throw new Error('unexpected fetch'); };
  try { await import(`../../examples/nodejs/client.mjs?offline=${Date.now()}`); assert.equal(calls, 0); }
  finally { globalThis.fetch = originalFetch; }
});

test('Profile CLI module import does not load credentials or make a network request', async () => {
  const originalFetch = globalThis.fetch; let calls = 0;
  globalThis.fetch = async () => { calls += 1; throw new Error('unexpected fetch'); };
  try {
    const imported = await import(`../../examples/nodejs/profile.mjs?offline=${Date.now()}`);
    assert.equal(typeof imported.main, 'function');
    assert.equal(calls, 0);
  } finally { globalThis.fetch = originalFetch; }
});
