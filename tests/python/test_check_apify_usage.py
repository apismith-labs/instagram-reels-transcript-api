from __future__ import annotations

import io
import json
import os
import stat
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.check_apify_usage import UsageCheckError, fetch_usage, summarize_usage, write_private_json  # noqa: E402


class FakeResponse:
    status = 200

    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class UsageCheckTests(unittest.TestCase):
    def test_missing_token_fails_without_making_a_request(self):
        calls = []
        with self.assertRaisesRegex(UsageCheckError, "APIFY_TOKEN is missing"):
            fetch_usage("", opener=lambda *args, **kwargs: calls.append((args, kwargs)))
        self.assertEqual(calls, [])

    def test_success_summarizes_cycle_and_usage_without_inventing_balance(self):
        payload = {
            "data": {
                "usageCycle": {"startAt": "2026-10-01T00:00:00Z", "endAt": "2026-10-31T23:59:59Z"},
                "monthlyServiceUsage": {"ACTOR_COMPUTE_UNITS": 2.5, "DATA_TRANSFER_GB": 0},
                "monthlyUsageCreditsUsd": 12.0,
                "accountBalanceUsd": 99.0,
            }
        }
        request_data = {}

        def opener(request, timeout):
            request_data.update(method=request.method, url=request.full_url, auth=request.get_header("Authorization"), timeout=timeout)
            return FakeResponse(json.dumps(payload).encode())

        result = fetch_usage("synthetic-secret-token", opener=opener)
        self.assertEqual(request_data["method"], "GET")
        self.assertEqual(request_data["url"], "https://api.apify.com/v2/users/me/usage/monthly")
        self.assertEqual(request_data["auth"], "Bearer synthetic-secret-token")
        self.assertEqual(request_data["timeout"], 20)
        self.assertEqual(result["usageCycle"]["startAt"], "2026-10-01T00:00:00Z")
        self.assertEqual([m["reportedValue"] for m in result["monthlyServiceUsage"]], [2.5, 0])
        self.assertTrue(all(m["unit"] == "unknown" for m in result["monthlyServiceUsage"]))
        self.assertEqual(result["balance"], "unknown; this script does not infer or calculate available balance")
        encoded = json.dumps(result)
        self.assertNotIn('"reportedValue": 99.0', encoded)
        self.assertIn("monthlyUsageCreditsUsd", encoded)
        self.assertNotIn('"reportedValue": 12.0', encoded)

    def test_http_401_and_403_are_reported_without_response_body(self):
        for code in (401, 403):
            with self.subTest(status=code):
                def opener(_request, timeout, status=code):
                    raise urllib.error.HTTPError("https://api.apify.com/", status, "rejected synthetic token", {}, io.BytesIO(b"synthetic-secret-token"))
                with self.assertRaisesRegex(UsageCheckError, f"HTTP {code}") as raised:
                    fetch_usage("synthetic-secret-token", opener=opener)
                self.assertNotIn("synthetic-secret-token", str(raised.exception))

    def test_network_failure_does_not_leak_url_or_proxy_credentials(self):
        def opener(_request, timeout):
            raise urllib.error.URLError("http://user:password@127.0.0.1:7897 connection failed")
        with self.assertRaises(UsageCheckError) as raised:
            fetch_usage("synthetic-secret-token", opener=opener)
        message = str(raised.exception)
        self.assertIn("network request failed", message)
        self.assertNotIn("password", message)
        self.assertNotIn("7897", message)
        self.assertNotIn("synthetic-secret-token", message)

    def test_invalid_json_and_unexpected_shape_fail_closed(self):
        for body in (b"not json", b"[]", b'{"data": []}'):
            with self.subTest(body=body):
                def opener(_request, timeout, data=body):
                    return FakeResponse(data)
                with self.assertRaises(UsageCheckError):
                    fetch_usage("synthetic-secret-token", opener=opener)

    def test_sensitive_unknown_values_are_omitted(self):
        result = summarize_usage({
            "usageCycle": {"startAt": "not-secret", "privateToken": "synthetic-secret-token"},
            "monthlyServiceUsage": {"safeMetric": 1, "secretToken": "synthetic-secret-token"},
            "account": {"email": "person@example.invalid", "balance": 123.45},
        }, queried_at=datetime(2026, 10, 21, tzinfo=timezone.utc))
        encoded = json.dumps(result)
        self.assertNotIn("synthetic-secret-token", encoded)
        self.assertNotIn("person@example.invalid", encoded)
        self.assertNotIn("123.45", encoded)
        self.assertIn("unknownFields", result)
        self.assertEqual(result["queriedAt"], "2026-10-21T00:00:00Z")

    def test_output_is_0600_and_refuses_non_ignored_repository_path(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "usage.json"
            write_private_json(path, {"safe": True})
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(path.read_text()), {"safe": True})

        if os.name == "posix":
            with self.assertRaisesRegex(UsageCheckError, "not Git-ignored"):
                write_private_json(ROOT / "docs" / "not-ignored-usage-output.json", {"safe": True})


if __name__ == "__main__":
    unittest.main()
