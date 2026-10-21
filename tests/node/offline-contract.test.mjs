import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { FakeActorClient, FakeTransport, loadFixture, repoRoot } from './offline-support.mjs';

test('contract records build provenance and unresolved semantics', async () => {
  const contract = JSON.parse(await readFile(path.join(repoRoot, 'docs/audit/contracts/instagram-transcripts-scraper-0.0.50.json'), 'utf8'));
  assert.equal(contract.actor.buildNumber, '0.0.50');
  assert.equal(contract.evidenceStatus, 'normalized_from_audit_report');
  assert.equal(contract.input.fields.resultsLimit.multiAccountScope, 'unknown');
  assert.equal(contract.input.fields.videoUrl.runtimeDefault, 'unknown');
  assert.equal(contract.modes.profile_posts.output.includes('no transcript'), true);
});

test('ten fixtures are synthetic and cover required categories', async () => {
  const names = ['transcript-success','transcript-error','dataset-empty','metadata-no-text','bulk-partial','bulk-out-of-order','profile-video','profile-non-video','missing-null-fields','unknown-extra-field'].map((n) => `${n}.synthetic.json`);
  const fixtures = await Promise.all(names.map(loadFixture));
  assert.equal(fixtures.length, 10);
  assert.ok(fixtures.every((f) => f._fixture.startsWith('SYNTHETIC')));
});

test('bulk fixtures include partial failure and URL-based out-of-order mapping', async () => {
  const partial = await loadFixture('bulk-partial.synthetic.json');
  const shuffled = await loadFixture('bulk-out-of-order.synthetic.json');
  assert.ok(partial.items.some((item) => item.errMsg));
  assert.notEqual(shuffled.input.bulkUrls[0], shuffled.items[0].url);
  assert.deepEqual(new Set(shuffled.items.map((i) => i.url)), new Set(shuffled.input.bulkUrls));
});

test('profile photo may omit transcript and audio fields', async () => {
  const item = (await loadFixture('profile-non-video.synthetic.json')).items[0];
  assert.equal(item.type, 'image');
  assert.equal('text' in item, false);
  assert.equal('audioUrl' in item, false);
});

test('fake transport records POST/GET and propagates queued failures', async () => {
  const transport = new FakeTransport([{ data: { id: 'synthetic-run' } }, new Error('synthetic timeout')]);
  assert.equal((await transport.request('POST', '/runs')).data.id, 'synthetic-run');
  await assert.rejects(transport.request('GET', '/runs/synthetic-run'), /synthetic timeout/);
  assert.equal(transport.postCount, 1);
  assert.equal(transport.getCount, 1);
});

test('fake actor client exposes run ID, status, dataset ID, and errors', () => {
  const client = new FakeActorClient({ runResponses: [{ id: 'synthetic-run' }], statusResponses: [{ status: 'SUCCEEDED' }], datasetResponses: [[{ url: 'synthetic' }]] });
  const run = client.startRun('synthetic/actor', { videoUrl: 'synthetic' });
  const status = client.getRun(run.id);
  const items = client.getDataset('synthetic-dataset');
  assert.deepEqual(client.runIds, ['synthetic-run']);
  assert.deepEqual(client.polledRunIds, ['synthetic-run']);
  assert.deepEqual(client.datasetIds, ['synthetic-dataset']);
  assert.equal(status.status, 'SUCCEEDED');
  assert.equal(items.length, 1);
  const failing = new FakeActorClient({ runResponses: [new Error('synthetic POST failure')] });
  assert.throws(() => failing.startRun('synthetic/actor', {}), /synthetic POST failure/);
});
