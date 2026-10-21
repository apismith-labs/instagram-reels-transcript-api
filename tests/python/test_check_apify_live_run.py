from __future__ import annotations

import io
import json
import sys
import urllib.error
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.check_apify_live_run import (  # noqa: E402
    LiveAuditError,
    build_parser,
    collect_live_audit,
)

RUN_ID = "synthetic-run-001"
DATASET_ID = "synthetic-dataset-001"
ACTOR_ID = "synthetic-actor-001"


class Response:
    status = 200
    headers = {}

    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def read(self): return json.dumps(self.payload).encode()


def run_payload(**overrides):
    data = {
        "id": RUN_ID,
        "actId": ACTOR_ID,
        "status": "SUCCEEDED",
        "defaultDatasetId": DATASET_ID,
        "buildId": "aJLRmMdQapLQRT4sJ",
        "buildNumber": "0.0.50",
        "usageTotalUsd": 0.012,
        "chargedEventCounts": {"Result Primary": 1},
    }
    data.update(overrides)
    return {"data": data}


def audit(token, *, opener):
    return collect_live_audit(
        token, run_id=RUN_ID, dataset_id=DATASET_ID, actor_id=ACTOR_ID, opener=opener
    )


class LiveRunAuditTests(unittest.TestCase):
    def test_success_uses_explicit_synthetic_identity_and_get_requests_only(self):
        requests = []
        dataset_item = {
            "text": "SYNTHETIC TRANSCRIPT MUST NEVER BE RETURNED",
            "segments": [{"text": "synthetic"}, {"text": "segment"}],
            "errMsg": "",
            "unknownField": "private synthetic data",
        }
        payloads = [
            run_payload(),
            [dataset_item],
            {"data": {"usageCycle": {"startAt": "2026-10-01", "endAt": "2026-10-31"}, "monthlyServiceUsage": {"PPE_SYNTHETIC": 1.25}}},
        ]

        def opener(request, timeout):
            requests.append((request.method, request.full_url, request.get_header("Authorization"), timeout))
            return Response(payloads.pop(0))

        result = audit("synthetic-secret", opener=opener)
        self.assertEqual([r[0] for r in requests], ["GET", "GET", "GET"])
        self.assertIn(RUN_ID, requests[0][1])
        self.assertIn(DATASET_ID, requests[1][1])
        self.assertIn("/users/me/usage/monthly", requests[2][1])
        self.assertTrue(all(r[2] == "Bearer synthetic-secret" for r in requests))
        self.assertEqual(result["run"]["runId"], RUN_ID)
        self.assertEqual(result["run"]["datasetId"], DATASET_ID)
        item = result["dataset"]["items"][0]
        self.assertEqual(result["dataset"]["itemsReturned"], 1)
        self.assertTrue(item["text"]["nonEmpty"])
        self.assertEqual(item["segments"]["count"], 2)
        self.assertFalse(item["errMsg"]["nonEmpty"])
        serialized = json.dumps(result)
        self.assertNotIn("SYNTHETIC TRANSCRIPT MUST NEVER BE RETURNED", serialized)
        self.assertNotIn("private synthetic data", serialized)

    def test_wrong_run_actor_or_dataset_stops_before_followup_gets(self):
        cases = (
            {"id": "different-run"},
            {"actId": "different-actor"},
            {"defaultDatasetId": "different-dataset"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                calls = []
                def opener(request, timeout):
                    calls.append(request.method)
                    return Response(run_payload(**overrides))
                with self.assertRaises(LiveAuditError):
                    audit("synthetic-secret", opener=opener)
                self.assertEqual(calls, ["GET"])

    def test_non_successful_run_does_not_read_dataset(self):
        calls=[]
        payloads=[run_payload(status="FAILED"),{"data":{"usageCycle":{},"monthlyServiceUsage":{}}}]
        def opener(request, timeout):
            calls.append(request.full_url)
            return Response(payloads.pop(0))
        result=audit("synthetic-secret",opener=opener)
        self.assertEqual(len(calls),2)
        self.assertNotIn("/datasets/",calls[1])
        self.assertEqual(result["dataset"]["itemsReturned"],None)

    def test_missing_null_costs_remain_unknown_not_zero(self):
        calls=[]
        payloads=[run_payload(usageTotalUsd=None,chargedEventCounts=None),[],{"data":{}}]
        def opener(request,timeout):
            calls.append(request.method)
            return Response(payloads.pop(0))
        result=audit("synthetic-secret",opener=opener)
        self.assertEqual(result["run"]["charges"]["usageTotalUsd"]["state"],"null; not treated as zero")
        self.assertEqual(result["run"]["charges"]["chargedEventCounts"]["state"],"null; not treated as zero")

    def test_http_failure_does_not_echo_body(self):
        def opener(_request,timeout):
            raise urllib.error.HTTPError("https://api.apify.com/",403,"secret response body",{},io.BytesIO(b"secret response body"))
        with self.assertRaisesRegex(LiveAuditError,"HTTP 403") as caught:
            audit("synthetic-secret",opener=opener)
        self.assertNotIn("secret response body",str(caught.exception))

    def test_cli_requires_explicit_run_dataset_and_actor_ids(self):
        parser = build_parser()
        with self.assertRaises(SystemExit) as caught:
            parser.parse_args([])
        self.assertEqual(caught.exception.code, 2)

    def test_invalid_path_identifiers_are_rejected_before_get(self):
        calls = []
        with self.assertRaisesRegex(LiveAuditError, "Run ID has an invalid format"):
            collect_live_audit(
                "synthetic-secret", run_id="../synthetic", dataset_id=DATASET_ID,
                actor_id=ACTOR_ID, opener=lambda *args, **kwargs: calls.append(args),
            )
        self.assertEqual(calls, [])


if __name__ == "__main__": unittest.main()
