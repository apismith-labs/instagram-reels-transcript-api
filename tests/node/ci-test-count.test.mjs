import test from 'node:test';
import assert from 'node:assert/strict';
import { createIsolatedEnvironment, decideExitCode, parseTapSummary } from '../../scripts/run_node_ci_tests.mjs';

test('parses the Node TAP totals used by the CI gate', () => {
  const summary = parseTapSummary('# tests 77\n# pass 77\n# fail 0\n# skipped 0\n');
  assert.deepEqual(summary, { tests: 77, passed: 77, failed: 0, skipped: 0 });
  assert.equal(decideExitCode(0, summary), 0);
});

test('fails closed when fewer than 73 tests pass, even when Node exits zero', () => {
  const summary = parseTapSummary('# tests 72\n# pass 72\n# fail 0\n# skipped 0\n');
  assert.equal(decideExitCode(0, summary), 1);
});

test('allows future test totals above the current minimum', () => {
  const summary = parseTapSummary('# tests 90\n# pass 90\n# fail 0\n# skipped 0\n');
  assert.equal(decideExitCode(0, summary), 0);
});

test('preserves a failing Node test process exit code', () => {
  const summary = parseTapSummary('# tests 73\n# pass 72\n# fail 1\n# skipped 0\n');
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
