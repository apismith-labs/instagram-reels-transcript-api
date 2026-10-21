import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "examples/python"))
from reliable_actor import APPROVED_BUILD_ID, ApiError, EXIT_CODES, RestTransport, RunJournal, build_run_input, classify_items, execute_input, load_resume_record, sanitize, summarize, validate_build, validate_run_charge_cap, write_private  # noqa: E402
from offline_support import FakeTransport, load_fixture  # noqa: E402

URL = "https://www.instagram.com/reel/synthetic-test/"


class ReliableActorTests(unittest.TestCase):
    def test_build_selection_is_query_only_and_approved_identity_is_verified(self):
        result, transport = self.run_one([
            {"data": {"id": "run-build", "defaultDatasetId": "ds-build", "buildNumber": "0.0.50", "buildId": APPROVED_BUILD_ID}},
            {"data": {"status": "SUCCEEDED", "defaultDatasetId": "ds-build"}},
            load_fixture("transcript-success.synthetic.json")["items"],
        ], build="0.0.50", require_build=True, max_total_charge_usd="0.30", require_charge_cap=True, dataset_limit=50)
        self.assertEqual(result["status"], "success")
        self.assertEqual((result["buildNumber"], result["buildId"], result["buildVerification"]), ("0.0.50", APPROVED_BUILD_ID, "response"))
        post = transport.requests[0]
        self.assertEqual(post["query"], {"maxTotalChargeUsd": 0.3, "restartOnError": "false", "build": "0.0.50"})
        self.assertEqual(post["body"], {"videoUrl": URL})
        self.assertEqual(transport.requests[-1]["path"], "/datasets/ds-build/items?limit=50&offset=0")
        self.assertTrue(result["datasetComplete"])

    def test_required_build_missing_or_wrong_is_rejected_before_post(self):
        for build in (None, "latest", "0.0.51"):
            with self.subTest(build=build):
                transport = FakeTransport([])
                result = execute_input(transport=transport, actor_id="synthetic/actor", run_input={"videoUrl": URL}, source_url=URL,
                    journal=self.journal, build=build, require_build=True, sleep=self.sleep)
                self.assertEqual(result["status"], "transport_error")
                self.assertEqual(transport.post_count, 0)
        self.assertEqual(validate_build("0.0.50", required=True), "0.0.50")

    def test_build_mismatch_preserves_run_identity_and_stops_before_dataset(self):
        transport = FakeTransport([
            {"data": {"id": "run-wrong-build", "defaultDatasetId": "ds-wrong-build", "buildNumber": "0.0.51", "buildId": "synthetic-other-build"}},
        ])
        result = execute_input(transport=transport, actor_id="synthetic/actor", run_input={"videoUrl": URL}, source_url=URL,
            journal=self.journal, build="0.0.50", require_build=True, sleep=self.sleep)
        self.assertEqual(result["status"], "transport_error")
        self.assertEqual(result["stage"], "build_mismatch")
        self.assertEqual((result["runId"], result["datasetId"]), ("run-wrong-build", "ds-wrong-build"))
        self.assertEqual(transport.post_count, 1)
        self.assertEqual(transport.get_count, 0)
        self.assertEqual(self.journal.latest("run-wrong-build")["buildId"], "synthetic-other-build")

    def test_missing_build_identity_uses_same_run_get_and_fails_closed(self):
        transport = FakeTransport([
            {"data": {"id": "run-no-build", "defaultDatasetId": "ds-no-build"}},
            {"data": {"status": "RUNNING", "buildNumber": "0.0.50"}},
        ])
        result = execute_input(transport=transport, actor_id="synthetic/actor", run_input={"videoUrl": URL}, source_url=URL,
            journal=self.journal, build="0.0.50", require_build=True, sleep=self.sleep)
        self.assertEqual(result["status"], "transport_error")
        self.assertEqual(result["stage"], "build_mismatch")
        self.assertEqual(transport.post_count, 1)
        self.assertEqual(transport.get_count, 1)

    def test_missing_creation_build_fields_can_be_verified_by_same_run_get(self):
        result, transport = self.run_one([
            {"data": {"id": "run-build-get", "defaultDatasetId": "ds-build-get"}},
            {"data": {"buildNumber": "0.0.50", "buildId": APPROVED_BUILD_ID, "status": "RUNNING"}},
            {"data": {"status": "SUCCEEDED", "defaultDatasetId": "ds-build-get"}},
            load_fixture("transcript-success.synthetic.json")["items"],
        ], build="0.0.50", require_build=True)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["buildVerification"], "run_get")
        self.assertEqual(transport.post_count, 1)
        self.assertEqual(transport.get_count, 3)

    def test_invalid_dataset_limit_is_rejected_before_post(self):
        transport = FakeTransport([])
        result = execute_input(transport=transport, actor_id="synthetic/actor", run_input={"videoUrl": URL}, source_url=URL,
            journal=self.journal, dataset_limit=0, sleep=self.sleep)
        self.assertEqual(result["status"], "transport_error")
        self.assertEqual(transport.post_count, 0)

    def test_dataset_limit_hit_is_marked_incomplete_unknown(self):
        result, transport = self.run_one([
            {"data": {"id": "run-limit", "defaultDatasetId": "ds-limit"}},
            {"data": {"status": "SUCCEEDED", "defaultDatasetId": "ds-limit"}},
            [{"text": "one"}, {"text": "two"}],
        ], dataset_limit=2)
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["datasetComplete"])
        self.assertIn("page limit", result["error"])
        self.assertEqual(transport.requests[-1]["path"], "/datasets/ds-limit/items?limit=2&offset=0")
        self.assertEqual(transport.post_count, 1)

    def test_optional_sessionid_is_omitted_unless_explicitly_set(self):
        self.assertEqual(build_run_input(URL), {"videoUrl": URL})
        self.assertEqual(build_run_input(URL, "synthetic-session"), {"videoUrl": URL, "sessionid": "synthetic-session"})

    def test_run_charge_cap_is_query_option_and_does_not_pollute_actor_input(self):
        transport = FakeTransport([{"data": {"id": "run-capped", "defaultDatasetId": "ds-capped"}}, {"data": {"status": "SUCCEEDED", "defaultDatasetId": "ds-capped"}}, [{"text": "synthetic transcript"}]])
        result = execute_input(transport=transport, actor_id="synthetic/actor", run_input={"videoUrl": URL}, source_url=URL,
            journal=self.journal, max_total_charge_usd="0.30", require_charge_cap=True, sleep=self.sleep)
        post = next(request for request in transport.requests if request["method"] == "POST")
        self.assertEqual(result["status"], "success")
        self.assertEqual(post["query"], {"maxTotalChargeUsd": 0.3, "restartOnError": "false"})
        self.assertEqual(post["body"], {"videoUrl": URL})

    def test_capped_test_mode_missing_or_invalid_amount_never_posts(self):
        for amount in (None, "", "NaN", "Infinity", "0", "-0.30", "not-money"):
            with self.subTest(amount=amount):
                transport = FakeTransport([])
                result = execute_input(transport=transport, actor_id="synthetic/actor", run_input={"videoUrl": URL}, source_url=URL,
                    journal=self.journal, max_total_charge_usd=amount, require_charge_cap=True, sleep=self.sleep)
                self.assertEqual(result["status"], "transport_error")
                self.assertEqual(transport.post_count, 0)

    def test_api_rejecting_run_cap_does_not_retry_post(self):
        transport = FakeTransport([ApiError("HTTP 400", status=400)])
        result = execute_input(transport=transport, actor_id="synthetic/actor", run_input={"videoUrl": URL}, source_url=URL,
            journal=self.journal, max_total_charge_usd="0.30", require_charge_cap=True, sleep=self.sleep)
        self.assertEqual(result["status"], "transport_error")
        self.assertEqual(transport.post_count, 1)

    def test_resume_does_not_need_creation_cap_or_post_again(self):
        self.journal.append({"rowId": "row-1", "sourceUrl": URL, "actorId": "synthetic/actor", "runId": "run-capped", "datasetId": "ds-capped", "stage": "run_created", "status": "unknown"})
        transport = FakeTransport([{"data": {"status": "SUCCEEDED", "defaultDatasetId": "ds-capped"}}, [{"text": "synthetic transcript"}]])
        result = execute_input(transport=transport, actor_id="synthetic/actor", run_input={"videoUrl": URL}, source_url=URL,
            journal=self.journal, run_id="run-capped", dataset_id="ds-capped", row_id="row-1", require_charge_cap=True, sleep=self.sleep)
        self.assertEqual(result["status"], "success")
        self.assertEqual(transport.post_count, 0)

    def test_authorized_live_resume_identity_and_get_failure_never_post(self):
        run_id = "synthetic-resume-run-001"
        dataset_id = "synthetic-resume-dataset-001"
        actor_id = "apple_yang/instagram-transcripts-scraper"
        source_url = "https://www.instagram.com/reels/DeKRjqRFQuJ/"
        row_id = "1de58775-a950-4e19-8e45-c066fdd691df"
        self.journal.append({"rowId": row_id, "sourceUrl": source_url, "actorId": actor_id,
            "runId": run_id, "datasetId": dataset_id, "stage": "complete", "status": "success"})
        record = load_resume_record(self.journal, run_id, actor_id)
        self.assertEqual((record["runId"], record["datasetId"], record["sourceUrl"]),
            (run_id, dataset_id, source_url))

        transport = FakeTransport([{"data": {"status": "SUCCEEDED", "defaultDatasetId": dataset_id}}, [{"text": "synthetic transcript"}]])
        result = execute_input(transport=transport, actor_id=actor_id, run_input={"videoUrl": source_url},
            source_url=source_url, journal=self.journal, run_id=record["runId"], dataset_id=record["datasetId"],
            row_id=record["rowId"], sleep=self.sleep)
        self.assertEqual(result["status"], "success")
        self.assertEqual(transport.post_count, 0)
        self.assertEqual([request["path"] for request in transport.requests],
            ["/actor-runs/" + run_id, "/datasets/" + dataset_id + "/items"])

        failed_get = FakeTransport([ApiError("synthetic 503", status=503)])
        failed = execute_input(transport=failed_get, actor_id=actor_id, run_input={"videoUrl": source_url},
            source_url=source_url, journal=self.journal, run_id=record["runId"], dataset_id=record["datasetId"],
            row_id=record["rowId"], max_attempts=1, sleep=self.sleep)
        self.assertEqual(failed["status"], "transport_error")
        self.assertEqual(failed_get.post_count, 0)
        self.assertEqual(failed_get.requests[0]["path"], "/actor-runs/" + run_id)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.journal = RunJournal(Path(self.temp.name) / "runs.jsonl")
        self.sleep = lambda _seconds: None

    def tearDown(self):
        self.temp.cleanup()

    def run_one(self, responses, **options):
        transport = FakeTransport(responses)
        result = execute_input(transport=transport, actor_id="synthetic/actor", run_input={"videoUrl": URL}, source_url=URL,
            journal=self.journal, max_attempts=options.pop("max_attempts", 4), sleep=self.sleep, **options)
        return result, transport

    def test_transcript_success_error_empty_and_metadata(self):
        self.assertEqual(classify_items(load_fixture("transcript-success.synthetic.json")["items"])[0], "success")
        self.assertEqual(classify_items(load_fixture("transcript-error.synthetic.json")["items"])[0], "actor_error")
        self.assertEqual(classify_items(load_fixture("dataset-empty.synthetic.json")["items"])[0], "empty")
        self.assertEqual(classify_items(load_fixture("metadata-no-text.synthetic.json")["items"])[0], "no_transcript")
        self.assertEqual(EXIT_CODES["success"], 0)
        self.assertNotEqual(EXIT_CODES["actor_error"], 0)
        self.assertNotEqual(EXIT_CODES["no_transcript"], 0)

    def test_missing_null_empty_and_numeric_zero_are_not_success(self):
        self.assertEqual(classify_items([{"text": None}])[0], "no_transcript")
        self.assertEqual(classify_items([{}])[0], "no_transcript")
        self.assertEqual(classify_items([{"text": ""}])[0], "no_transcript")
        self.assertEqual(classify_items([{"text": 0}])[0], "unknown")

    def test_rest_transport_builds_authorized_actor_path_and_json_body(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self): return b'{"data":{"id":"run-http","defaultDatasetId":"ds-http"}}'
        captured = {}
        def opener(request, timeout):
            captured.update(method=request.method, url=request.full_url, authorization=request.get_header("Authorization"), body=json.loads(request.data), timeout=timeout)
            return Response()
        result = RestTransport("synthetic-token", opener=opener).request("POST", "/acts/synthetic~actor/runs", {"videoUrl": URL}, timeout=7,
            query={"maxTotalChargeUsd": validate_run_charge_cap("0.30"), "restartOnError": "false"})
        self.assertEqual(result["data"]["id"], "run-http")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["url"], "https://api.apify.com/v2/acts/synthetic~actor/runs?maxTotalChargeUsd=0.3&restartOnError=false")
        self.assertEqual(captured["authorization"], "Bearer synthetic-token")
        self.assertEqual(captured["body"], {"videoUrl": URL})
        self.assertEqual(captured["timeout"], 7)

    def test_create_then_run_query_failure_retries_same_run_once(self):
        result, transport = self.run_one([
            {"data": {"id": "run-1", "defaultDatasetId": "ds-1"}},
            ApiError("temporary", status=503), {"data": {"id": "run-1", "status": "SUCCEEDED", "defaultDatasetId": "ds-1"}},
            load_fixture("transcript-success.synthetic.json")["items"],
        ])
        self.assertEqual(result["status"], "success")
        self.assertEqual((transport.post_count, transport.get_count), (1, 3))
        self.assertIsNone(transport.requests[0]["query"])
        self.assertEqual(transport.requests[1]["path"], "/actor-runs/run-1")
        self.assertEqual(transport.requests[2]["path"], "/actor-runs/run-1")
        self.assertEqual(transport.requests[3]["path"], "/datasets/ds-1/items")

    def test_get_429_retries_same_run_without_reposting(self):
        result, transport = self.run_one([
            {"data": {"id": "run-429-get", "defaultDatasetId": "ds-429-get"}},
            ApiError("rate limited", status=429, retry_after=0),
            {"data": {"status": "SUCCEEDED", "defaultDatasetId": "ds-429-get"}},
            load_fixture("transcript-success.synthetic.json")["items"],
        ])
        self.assertEqual(result["status"], "success")
        self.assertEqual(transport.post_count, 1)
        self.assertEqual(transport.get_count, 3)

    def test_resume_rejects_dataset_id_that_disagrees_with_run(self):
        result, transport = self.run_one([
            {"data": {"status": "SUCCEEDED", "defaultDatasetId": "ds-actual"}},
        ], run_id="run-mismatch", dataset_id="ds-from-journal")
        self.assertEqual(result["status"], "transport_error")
        self.assertEqual(transport.post_count, 0)
        self.assertEqual(transport.get_count, 1)

    def test_dataset_retry_does_not_create_another_run(self):
        result, transport = self.run_one([
            {"data": {"id": "run-2", "defaultDatasetId": "ds-2"}},
            {"data": {"status": "SUCCEEDED", "defaultDatasetId": "ds-2"}},
            ApiError("temporary", status=503), load_fixture("transcript-success.synthetic.json")["items"],
        ])
        self.assertEqual(result["status"], "success")
        self.assertEqual((transport.post_count, transport.get_count), (1, 3))

    def test_ambiguous_post_is_creation_unknown_and_never_reposted(self):
        result, transport = self.run_one([ApiError("timeout", ambiguous=True)])
        self.assertEqual(result["status"], "creation_unknown")
        self.assertIsNone(result["runId"])
        self.assertEqual(transport.post_count, 1)

    def test_401_and_403_are_not_retried(self):
        for code in (401, 403):
            with self.subTest(code=code):
                result, transport = self.run_one([ApiError(f"HTTP {code}", status=code)])
                self.assertEqual(result["status"], "transport_error")
                self.assertEqual(transport.post_count, 1)

    def test_429_creation_is_not_retried_when_acceptance_semantics_are_unverified(self):
        result, transport = self.run_one([ApiError("rate limited", status=429)], max_attempts=4, max_total_charge_usd="0.30", require_charge_cap=True)
        self.assertEqual(result["status"], "creation_unknown")
        self.assertEqual(transport.post_count, 1)

    def test_successful_run_with_no_transcript_does_not_restart(self):
        result, transport = self.run_one([
            {"data": {"id": "run-3", "defaultDatasetId": "ds-3"}},
            {"data": {"status": "SUCCEEDED", "defaultDatasetId": "ds-3"}},
            load_fixture("metadata-no-text.synthetic.json")["items"],
        ])
        self.assertEqual(result["status"], "no_transcript")
        self.assertEqual(transport.post_count, 1)

    def test_journal_keeps_run_and_dataset_for_resume_after_output_failure(self):
        first, initial = self.run_one([
            {"data": {"id": "run-4", "defaultDatasetId": "ds-4"}},
            {"data": {"status": "SUCCEEDED", "defaultDatasetId": "ds-4"}}, ApiError("dataset unavailable", status=503),
        ], max_attempts=1)
        self.assertEqual(first["status"], "transport_error")
        saved = self.journal.latest("run-4")
        self.assertEqual((saved["runId"], saved["datasetId"]), ("run-4", "ds-4"))
        # Simulate recovery after the caller's result-file write failed: resume from durable IDs.
        resumed, recovery = self.run_one([
            {"data": {"status": "SUCCEEDED", "defaultDatasetId": "ds-4"}},
            load_fixture("transcript-success.synthetic.json")["items"],
        ], run_id=saved["runId"], dataset_id=saved["datasetId"])
        self.assertEqual(resumed["status"], "success")
        self.assertEqual(recovery.post_count, 0)
        self.assertEqual(initial.post_count + recovery.post_count, 1)
        records = [json.loads(x) for x in (Path(self.temp.name) / "runs.jsonl").read_text().splitlines()]
        self.assertTrue(records)

    def test_empty_dataset_is_rechecked_on_same_run_before_final_classification(self):
        successful, first = self.run_one([
            {"data": {"id": "run-empty-lag", "defaultDatasetId": "ds-empty-lag"}},
            {"data": {"status": "SUCCEEDED", "defaultDatasetId": "ds-empty-lag"}}, [],
            load_fixture("transcript-success.synthetic.json")["items"],
        ])
        self.assertEqual(successful["status"], "success")
        self.assertEqual(first.post_count, 1)
        final, second = self.run_one([
            {"data": {"id": "run-empty-final", "defaultDatasetId": "ds-empty-final"}},
            {"data": {"status": "SUCCEEDED", "defaultDatasetId": "ds-empty-final"}}, [], [], [],
        ])
        self.assertEqual(final["status"], "empty")
        self.assertEqual(second.post_count, 1)
        self.assertEqual(second.get_count, 4)

    def test_resume_requires_matching_actor_run_and_input_association(self):
        self.journal.append({"rowId": "row-2", "sourceUrl": URL, "actorId": "synthetic/actor", "runId": "run-bound", "datasetId": "ds-bound", "stage": "run_created"})
        self.assertEqual(load_resume_record(self.journal, "run-bound", "synthetic/actor")["sourceUrl"], URL)
        with self.assertRaises(ValueError): load_resume_record(self.journal, "run-bound", "other/actor")
        with self.assertRaises(ValueError): load_resume_record(self.journal, "missing-run", "synthetic/actor")

    def test_journal_corruption_fails_closed_and_permissions_are_restricted(self):
        path = Path(self.temp.name) / "existing.jsonl"
        path.write_text("{}\n", encoding="utf-8")
        path.chmod(0o644)
        journal = RunJournal(path)
        journal.append({"runId": "safe"})
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        with path.open("a", encoding="utf-8") as stream: stream.write("{truncated\n")
        with self.assertRaisesRegex(ValueError, "corrupt"):
            journal.latest("safe")

    def test_corrupt_journal_prevents_a_new_paid_post(self):
        self.journal.path.write_text("{truncated\n", encoding="utf-8")
        transport = FakeTransport([{"data": {"id": "must-not-be-created"}}])
        result = execute_input(transport=transport, actor_id="synthetic/actor", run_input={"videoUrl": URL}, source_url=URL,
            journal=self.journal, sleep=self.sleep)
        self.assertEqual(result["status"], "transport_error")
        self.assertEqual(transport.post_count, 0)

    def test_persisted_data_sanitizer_removes_credential_fields_and_assignments(self):
        cleaned = sanitize({"session_id": "secret-cookie", "nested": {"access_token": "secret-token", "note": "Bearer abc123 token=xyz"}})
        self.assertNotIn("session_id", cleaned)
        self.assertNotIn("access_token", cleaned["nested"])
        self.assertNotIn("abc123", cleaned["nested"]["note"])
        self.assertNotIn("xyz", cleaned["nested"]["note"])
        private_path = Path(self.temp.name) / "private-output.json"
        private_path.write_text("old", encoding="utf-8")
        private_path.chmod(0o644)
        write_private(private_path, "sanitized")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(private_path.stat().st_mode), 0o600)

    def test_private_writers_work_when_fchmod_is_unavailable(self):
        with patch.object(os, "fchmod", None, create=True):
            path = Path(self.temp.name) / "portable.jsonl"
            journal = RunJournal(path)
            journal.append({"runId": "synthetic-run"})
            self.assertEqual(journal.latest("synthetic-run")["runId"], "synthetic-run")
            output = Path(self.temp.name) / "portable-output.json"
            write_private(output, "synthetic result")
            self.assertEqual(output.read_text(encoding="utf-8"), "synthetic result")

    def test_mixed_batch_summary_counts_every_row_and_failed_outputs(self):
        statuses = ["success", "actor_error", "empty", "no_transcript", "unknown", "transport_error", "run_failed", "creation_unknown"]
        counts = summarize([{"status": status} for status in statuses])
        self.assertEqual(counts["processed"], len(statuses))
        self.assertEqual(sum(counts[s] for s in ("success", "actor_error", "empty", "no_transcript", "unknown", "transport_error", "run_failed", "creation_unknown")), len(statuses))
        self.assertEqual(counts["failed"], len(statuses) - counts["success"])


if __name__ == "__main__":
    unittest.main()
