import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
export const repoRoot = path.resolve(here, '../..');
export const fixtureDir = path.join(repoRoot, 'tests', 'fixtures');

export async function loadFixture(name) {
  const data = JSON.parse(await readFile(path.join(fixtureDir, name), 'utf8'));
  if (!data._fixture?.startsWith('SYNTHETIC')) throw new Error(`Fixture is not marked synthetic: ${name}`);
  return data;
}

export class FakeTransport {
  constructor(responses = []) {
    this.responses = [...responses];
    this.requests = [];
  }
  async request(method, path, body, _timeout, query = null) {
    this.requests.push({ method: method.toUpperCase(), path, body, query });
    if (!this.responses.length) throw new Error('No synthetic transport response queued');
    const response = this.responses.shift();
    if (response instanceof Error) throw response;
    return response;
  }
  get postCount() { return this.requests.filter((r) => r.method === 'POST').length; }
  get getCount() { return this.requests.filter((r) => r.method === 'GET').length; }
}

export class FakeActorClient {
  constructor({ runResponses = [], statusResponses = [], datasetResponses = [] } = {}) {
    this.runResponses = [...runResponses];
    this.statusResponses = [...statusResponses];
    this.datasetResponses = [...datasetResponses];
    this.runIds = [];
    this.polledRunIds = [];
    this.datasetIds = [];
  }
  startRun(actorId, input) {
    if (!this.runResponses.length) throw new Error('No synthetic run response queued');
    const result = this.runResponses.shift();
    if (result instanceof Error) throw result;
    this.runIds.push(result.id);
    return result;
  }
  getRun(runId) {
    this.polledRunIds.push(runId);
    if (!this.statusResponses.length) throw new Error('No synthetic run status queued');
    const result = this.statusResponses.shift();
    if (result instanceof Error) throw result;
    return result;
  }
  getDataset(datasetId) {
    this.datasetIds.push(datasetId);
    if (!this.datasetResponses.length) throw new Error('No synthetic dataset response queued');
    const result = this.datasetResponses.shift();
    if (result instanceof Error) throw result;
    return result;
  }
}
