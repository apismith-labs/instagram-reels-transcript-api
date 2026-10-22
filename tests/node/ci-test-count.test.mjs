import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { compareTestFileLists, createIsolatedEnvironment, decideExitCode, discoverNodeTestFiles, MINIMUM_PASSES, parseTapSummary, TEST_FILES } from '../../scripts/run_node_ci_tests.mjs';

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

test('parses the Node TAP totals used by the CI gate', () => {
  const summary = parseTapSummary('# tests 97\n# pass 97\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n');
  assert.deepEqual(summary, { tests: 97, passed: 97, failed: 0, skipped: 0, cancelled: 0, todo: 0 });
  assert.equal(decideExitCode(0, summary), 0);
});

test('requires the 96-test minimum and accepts equal or larger passing suites', () => {
  assert.equal(MINIMUM_PASSES, 96);
  const low = parseTapSummary('# tests 95\n# pass 95\n# fail 0\n# skipped 0\n');
  assert.equal(decideExitCode(0, low), 1);
  const equal = parseTapSummary('# tests 96\n# pass 96\n# fail 0\n# skipped 0\n');
  assert.equal(decideExitCode(0, equal), 0);
});

test('allows future test totals above the current minimum', () => {
  const summary = parseTapSummary('# tests 120\n# pass 120\n# fail 0\n# skipped 0\n');
  assert.equal(decideExitCode(0, summary), 0);
});

test('rejects skipped, cancelled, TODO, or inconsistent TAP counts', () => {
  assert.equal(decideExitCode(0, parseTapSummary('# tests 97\n# pass 96\n# fail 0\n# skipped 1\n')), 1);
  assert.equal(decideExitCode(0, parseTapSummary('# tests 97\n# pass 96\n# fail 0\n# cancelled 1\n')), 1);
  assert.equal(decideExitCode(0, parseTapSummary('# tests 97\n# pass 97\n# fail 0\n# todo 1\n')), 1);
  assert.equal(decideExitCode(0, parseTapSummary('# tests 100\n# pass 96\n# fail 0\n# skipped 0\n')), 1);
});

test('fails closed when fewer than the minimum pass even if Node exits zero', () => {
  const summary = parseTapSummary('# tests 72\n# pass 72\n# fail 0\n# skipped 0\n');
  assert.equal(decideExitCode(0, summary), 1);
});

test('test discovery and explicit whitelist must match exactly', () => {
  const actual = discoverNodeTestFiles(repositoryRoot);
  assert.deepEqual(compareTestFileLists(actual, TEST_FILES), { missing: [], stale: [] });
  const drift = compareTestFileLists(['tests/node/one.test.mjs', 'tests/node/new.test.mjs'], ['tests/node/one.test.mjs']);
  assert.deepEqual(drift, { missing: ['tests/node/new.test.mjs'], stale: [] });
  assert.deepEqual(compareTestFileLists(['tests/node/one.test.mjs'], ['tests/node/one.test.mjs', 'tests/node/deleted.test.mjs']),
    { missing: [], stale: ['tests/node/deleted.test.mjs'] });
});

test('preserves a failing Node test process exit code', () => {
  const summary = parseTapSummary('# tests 97\n# pass 96\n# fail 1\n# skipped 0\n');
  assert.equal(decideExitCode(1, summary), 1);
});

test('rejects incomplete TAP summaries', () => {
  assert.equal(parseTapSummary('# pass 73\n# fail 0\n'), null);
  assert.equal(decideExitCode(0, null), 1);
});

test('passes only the minimal platform environment and never forwards credentials', () => {
  const env = createIsolatedEnvironment({ PATH: '/usr/bin', APIFY_TOKEN: 'synthetic-secret', INSTAGRAM_SESSIONID: 'synthetic-session' });
  assert.deepEqual(env, {
    PATH: '/usr/bin',
    APIFY_TOKEN: '',
    INSTAGRAM_SESSIONID: '',
    APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD: '',
    NO_COLOR: '1',
  });
});
