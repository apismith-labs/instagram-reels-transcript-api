import { spawn } from 'node:child_process';
import { readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const MINIMUM_PASSES = 96;

// Keep the CI test set explicit so runtime-specific discovery cannot omit test files.
export const TEST_FILES = [
  'tests/node/cli-safety.test.mjs',
  'tests/node/native-bulk.test.mjs',
  'tests/node/profile-client.test.mjs',
  'tests/node/offline-contract.test.mjs',
  'tests/node/reliable-actor.test.mjs',
  'tests/node/ci-test-count.test.mjs',
];

function normalizeTestPath(file) { return String(file).replaceAll('\\', '/'); }
export function compareTestFileLists(discoveredFiles, listedFiles = TEST_FILES) {
  const discovered = new Set(discoveredFiles.map(normalizeTestPath));
  const listed = new Set(listedFiles.map(normalizeTestPath));
  return {
    missing: [...discovered].filter((file) => !listed.has(file)).sort(),
    stale: [...listed].filter((file) => !discovered.has(file)).sort(),
  };
}
export function discoverNodeTestFiles(repositoryRoot) {
  return readdirSync(path.join(repositoryRoot, 'tests', 'node'), { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith('.test.mjs'))
    .map((entry) => `tests/node/${entry.name}`).sort();
}

const PASSTHROUGH_ENVIRONMENT_NAMES = new Set([
  'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR', 'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA',
]);

export function createIsolatedEnvironment(source = process.env) {
  const environment = {};
  for (const name of Object.keys(source)) {
    if (PASSTHROUGH_ENVIRONMENT_NAMES.has(name.toUpperCase())) environment[name] = source[name];
  }
  environment.APIFY_TOKEN = '';
  environment.INSTAGRAM_SESSIONID = '';
  environment.APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD = '';
  environment.NO_COLOR = '1';
  return environment;
}

export function parseTapSummary(output) {
  const read = (field) => {
    const match = output.match(new RegExp(`^# ${field} (\\d+)\\s*$`, 'm'));
    return match ? Number(match[1]) : null;
  };
  const tests = read('tests');
  const passed = read('pass');
  const failed = read('fail');
  const skipped = read('skipped') ?? 0;
  const cancelled = read('cancelled') ?? 0;
  const todo = read('todo') ?? 0;
  if (tests === null || passed === null || failed === null) return null;
  return { tests, passed, failed, skipped, cancelled, todo };
}

export function decideExitCode(childExitCode, summary, minimumPasses = MINIMUM_PASSES) {
  if (childExitCode !== 0) return Number.isInteger(childExitCode) ? childExitCode : 1;
  if (!summary || summary.failed !== 0 || summary.passed < minimumPasses || summary.skipped !== 0 ||
      (summary.cancelled ?? 0) !== 0 || (summary.todo ?? 0) !== 0 ||
      summary.tests !== summary.passed + summary.failed + summary.skipped + (summary.cancelled ?? 0)) return 1;
  return 0;
}

export function runNodeTests({
  spawnProcess = spawn,
  write = (chunk) => process.stdout.write(chunk),
  report = console.log,
  error = console.error,
} = {}) {
  const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
  const repositoryRoot = path.resolve(scriptDirectory, '..');
  const drift = compareTestFileLists(discoverNodeTestFiles(repositoryRoot));
  if (drift.missing.length || drift.stale.length) {
    error(`Node.js test file list mismatch; unregistered: ${drift.missing.join(', ') || '(none)'}; missing files: ${drift.stale.join(', ') || '(none)'}`);
    process.exitCode = 1;
    return;
  }
  const testPaths = TEST_FILES.map((file) => path.join(repositoryRoot, file));
  const child = spawnProcess(process.execPath, ['--test', '--test-reporter=tap', ...testPaths], {
    cwd: repositoryRoot,
    env: createIsolatedEnvironment(),
    stdio: ['ignore', 'pipe', 'inherit'],
  });

  let output = '';
  child.stdout.setEncoding('utf8');
  child.stdout.on('data', (chunk) => {
    output += chunk;
    write(chunk);
  });
  child.on('error', (cause) => {
    error(`Could not start Node.js tests: ${cause.message}`);
    process.exitCode = 1;
  });
  child.on('close', (code) => {
    const summary = parseTapSummary(output);
    if (!summary) {
      error('Node.js test output did not contain a complete TAP summary; failing closed.');
    } else {
      report(`Node.js tests: ${summary.passed}/${summary.tests} passed; ${summary.failed} failed; ${summary.skipped} skipped; ${summary.todo} todo (minimum passes: ${MINIMUM_PASSES}).`);
    }
    process.exitCode = decideExitCode(code, summary);
    if (process.exitCode !== 0 && code === 0) {
      error(`Node.js CI test gate failed: at least ${MINIMUM_PASSES} tests must pass, with no failures, skips, cancellations, or TODOs.`);
    }
  });
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : '';
if (invokedPath === import.meta.url) runNodeTests();
