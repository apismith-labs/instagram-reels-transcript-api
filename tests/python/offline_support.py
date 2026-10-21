"""Dependency-free synthetic support; never imports or invokes example scripts."""
from __future__ import annotations

import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def load_fixture(name: str) -> dict:
    data = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    assert data["_fixture"].startswith("SYNTHETIC")
    return data


class FakeTransport:
    """Records requests and returns queued responses/errors without network access."""

    def __init__(self, responses=()):
        self.responses = list(responses)
        self.requests = []

    def request(self, method: str, path: str, body=None, **kwargs):
        record = {"method": method.upper(), "path": path, "body": body, "query": kwargs.get("query")}
        self.requests.append(record)
        if not self.responses:
            raise AssertionError("No synthetic transport response queued")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    @property
    def post_count(self):
        return sum(r["method"] == "POST" for r in self.requests)

    @property
    def get_count(self):
        return sum(r["method"] == "GET" for r in self.requests)


class FakeActorClient:
    """Small call/run/dataset seam for later retry and status tests."""

    def __init__(self, *, run_responses=(), status_responses=(), dataset_responses=()):
        self.run_responses = list(run_responses)
        self.status_responses = list(status_responses)
        self.dataset_responses = list(dataset_responses)
        self.run_ids = []
        self.polled_run_ids = []
        self.dataset_ids = []

    def start_run(self, actor_id: str, run_input: dict):
        if not self.run_responses:
            raise AssertionError("No synthetic run response queued")
        result = self.run_responses.pop(0)
        if isinstance(result, Exception):
            raise result
        self.run_ids.append(result["id"])
        return result

    def get_run(self, run_id: str):
        self.polled_run_ids.append(run_id)
        if not self.status_responses:
            raise AssertionError("No synthetic run status queued")
        result = self.status_responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def get_dataset(self, dataset_id: str):
        if not self.dataset_responses:
            raise AssertionError("No synthetic dataset response queued")
        result = self.dataset_responses.pop(0)
        if isinstance(result, Exception):
            raise result
        self.dataset_ids.append(dataset_id)
        return result
