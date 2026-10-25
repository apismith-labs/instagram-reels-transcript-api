"""Focused offline regression coverage for the W3 P2 findings."""

import json
import unittest
from dataclasses import replace
from pathlib import Path

from tools import mcp_parse


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "tests/fixtures/dx2-native-mcp-record.redacted.json").read_text())
RUN_ID = "JyaFWeQ1SrLXIteIK"
DATASET_ID = "MHT7DmSNRX0kmcsKg"
EXPECTED = FIXTURE["expectedShortcodes"]


def expect_error(test, code, callback):
    with test.assertRaises(mcp_parse.MCPParseError) as caught:
        callback()
    test.assertEqual(caught.exception.code, code)


class BuildVerificationTests(unittest.TestCase):
    def parse_build(self, number=None, build_id=None):
        sc = {"runId": RUN_ID, "status": "SUCCEEDED",
              "storages": {"datasets": {"default": {"id": DATASET_ID, "itemCount": 2}}}}
        if number is not None:
            sc["buildNumber"] = number
        if build_id is not None:
            sc["buildId"] = build_id
        return mcp_parse.run_metadata(
            {"structuredContent": sc}, expected_run_id=RUN_ID,
            expected_build_number="0.0.50", expected_build_id="aJLRmMdQapLQRT4sJ",
        )

    def test_p2f1_pinned_number_and_id_verify(self):
        self.assertEqual(self.parse_build("0.0.50", "aJLRmMdQapLQRT4sJ").build_verified, "VERIFIED")

    def test_p2f1_drifted_number_and_id_report_drift(self):
        self.assertEqual(self.parse_build("0.0.49", "wrongBuildId123456").build_verified, "BUILD_DRIFT")

    def test_p3_w4_01_single_number_pin_detects_number_drift(self):
        run = mcp_parse.run_metadata(
            {"structuredContent": {"runId": RUN_ID, "status": "SUCCEEDED",
                                   "buildNumber": "0.0.49", "buildId": "aJLRmMdQapLQRT4sJ"}},
            expected_run_id=RUN_ID, require_dataset_id=False,
            expected_build_number="0.0.50", expected_build_id=None,
        )
        self.assertEqual(run.build_verified, "BUILD_DRIFT")

    def test_p3_w4_01_single_id_pin_detects_id_drift(self):
        run = mcp_parse.run_metadata(
            {"structuredContent": {"runId": RUN_ID, "status": "SUCCEEDED",
                                   "buildNumber": "0.0.50", "buildId": "wrongBuildId123456"}},
            expected_run_id=RUN_ID, require_dataset_id=False,
            expected_build_number=None, expected_build_id="aJLRmMdQapLQRT4sJ",
        )
        self.assertEqual(run.build_verified, "BUILD_DRIFT")

    def test_p3_w4_01_acceptance_preserves_confirmed_drift_with_one_pin(self):
        payload = {"structuredContent": {"runId": RUN_ID, "status": "SUCCEEDED",
                    "buildNumber": "0.0.49", "buildId": "wrongBuildId123456",
                    "storages": {"datasets": {"default": {"id": DATASET_ID, "itemCount": 2}}}}}
        run = mcp_parse.run_metadata(payload, expected_run_id=RUN_ID,
                                     expected_build_number="0.0.50", expected_build_id="aJLRmMdQapLQRT4sJ")
        page = mcp_parse.dataset_items(FIXTURE["dataset"], expected_dataset_id=DATASET_ID,
                                       expected_run_item_count=2)
        result = mcp_parse.acceptance(run, page, EXPECTED, expected_build_number="0.0.50")
        self.assertEqual(result["functionalVerdict"], "PASS")
        self.assertEqual(result["buildVerified"], "BUILD_DRIFT")
        self.assertEqual(result["verdict"], "BUILD_DRIFT")

    def test_p2f1_partial_metadata_is_unverified(self):
        self.assertEqual(self.parse_build("0.0.50").build_verified, "UNVERIFIED_INCOMPLETE_METADATA")

    def test_p3_w4_01_no_expected_pins_are_explicitly_unverified(self):
        run = self.parse_build("0.0.50", "aJLRmMdQapLQRT4sJ")
        result = mcp_parse.acceptance(
            run, mcp_parse.dataset_items(FIXTURE["dataset"], expected_dataset_id=DATASET_ID,
                                         expected_run_item_count=2), EXPECTED,
        )
        self.assertEqual(result["buildVerified"], "UNVERIFIED_EXPECTATION_ABSENT")
        self.assertEqual(result["functionalVerdict"], "PASS")
        self.assertEqual(result["verdict"], "PASS")

    def test_p3_w4_01_matching_single_pin_without_second_expectation_is_incomplete(self):
        run = self.parse_build("0.0.50", "aJLRmMdQapLQRT4sJ")
        page = mcp_parse.dataset_items(FIXTURE["dataset"], expected_dataset_id=DATASET_ID,
                                       expected_run_item_count=2)
        result = mcp_parse.acceptance(run, page, EXPECTED, expected_build_number="0.0.50")
        self.assertEqual(result["buildVerified"], "UNVERIFIED_INCOMPLETE_METADATA")
        self.assertEqual(result["functionalVerdict"], "PASS")
        self.assertEqual(result["verdict"], "PASS")

    def test_p2f1_absent_metadata_keeps_functional_pass_but_build_unverified(self):
        run = mcp_parse.run_metadata(FIXTURE["run"], expected_run_id=RUN_ID,
                                     expected_build_number="0.0.50",
                                     expected_build_id="aJLRmMdQapLQRT4sJ")
        page = mcp_parse.dataset_items(FIXTURE["dataset"], expected_dataset_id=DATASET_ID,
                                       expected_run_item_count=2)
        result = mcp_parse.acceptance(run, page, EXPECTED,
                                      expected_build_number="0.0.50",
                                      expected_build_id="aJLRmMdQapLQRT4sJ")
        self.assertEqual(result["functionalVerdict"], "PASS")
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["buildVerified"], "UNVERIFIED_SOURCE_ABSENT")

    def test_p2f1_drift_blocks_unconditional_overall_pass(self):
        payload = json.loads(json.dumps(FIXTURE["run"]))
        payload["structuredContent"]["buildNumber"] = "0.0.49"
        payload["structuredContent"]["buildId"] = "wrongBuildId123456"
        run = mcp_parse.run_metadata(payload, expected_run_id=RUN_ID,
                                    expected_build_number="0.0.50",
                                    expected_build_id="aJLRmMdQapLQRT4sJ")
        page = mcp_parse.dataset_items(FIXTURE["dataset"], expected_dataset_id=DATASET_ID,
                                       expected_run_item_count=2)
        result = mcp_parse.acceptance(run, page, EXPECTED,
                                      expected_build_number="0.0.50",
                                      expected_build_id="aJLRmMdQapLQRT4sJ")
        self.assertEqual(result["functionalVerdict"], "PASS")
        self.assertEqual(result["buildVerified"], "BUILD_DRIFT")
        self.assertEqual(result["verdict"], "BUILD_DRIFT")


class RestFallbackGateTests(unittest.TestCase):
    def payload(self, *, dataset_id=None, rest_id=DATASET_ID, include_kv=False):
        storage = {}
        if dataset_id is not None:
            storage["datasets"] = {"default": {"id": dataset_id, "itemCount": 2}}
        if include_kv:
            storage["keyValueStores"] = {"default": {"id": "KV_STORE_ID_1234567"}}
        sc = {"runId": RUN_ID, "status": "SUCCEEDED", "storages": storage}
        data = {"structuredContent": sc}
        if rest_id is not None:
            data["restFallback"] = {"defaultDatasetId": rest_id}
        return data

    def test_p2f2_disabled_fallback_is_not_read_or_accepted(self):
        expect_error(self, "DATASET_ID_UNAVAILABLE", lambda: mcp_parse.run_metadata(
            self.payload(), expected_run_id=RUN_ID, allow_rest_fallback=False))

    def test_p2f2_enabled_fallback_has_explicit_provenance(self):
        run = mcp_parse.run_metadata(self.payload(), expected_run_id=RUN_ID,
                                     allow_rest_fallback=True)
        self.assertEqual(run.dataset_id, DATASET_ID)
        self.assertEqual(run.dataset_id_path, "restFallback.defaultDatasetId")
        self.assertEqual(run.run_source, "MCP + REST diagnostic fallback")

    def test_p2f2_mcp_rest_disagreement_fails_closed(self):
        expect_error(self, "DATASET_ID_CONFLICT", lambda: mcp_parse.run_metadata(
            self.payload(dataset_id="MCP_DATASET_ID", rest_id="REST_DATASET_ID"),
            expected_run_id=RUN_ID, allow_rest_fallback=True))

    def test_p2f2_key_value_store_id_is_not_a_dataset_id(self):
        expect_error(self, "DATASET_ID_UNAVAILABLE", lambda: mcp_parse.run_metadata(
            self.payload(rest_id=None, include_kv=True), expected_run_id=RUN_ID))


class RunAndDatasetBindingTests(unittest.TestCase):
    def test_p2f3_dataset_id_alone_is_not_run_identity(self):
        expect_error(self, "RUN_IDENTITY_UNAVAILABLE", lambda: mcp_parse.extract_run_identity(
            {"structuredContent": {"storages": {"datasets": {"default": {"id": RUN_ID}}}}}))

    def test_p2f3_key_value_store_id_alone_is_not_run_identity(self):
        expect_error(self, "RUN_IDENTITY_UNAVAILABLE", lambda: mcp_parse.extract_run_identity(
            {"structuredContent": {"storages": {"keyValueStores": {"default": {"id": RUN_ID}}}}}))

    def test_p2f3_unrelated_17_character_id_is_not_run_identity(self):
        expect_error(self, "RUN_IDENTITY_UNAVAILABLE", lambda: mcp_parse.extract_run_identity(
            {"id": "A1234567890123456", "datasetId": DATASET_ID}))

    def test_p2f3_conflicting_semantic_run_ids_fail_closed(self):
        expect_error(self, "RUN_IDENTITY_CONFLICT", lambda: mcp_parse.extract_run_identity(
            {"runId": RUN_ID, "actorRunId": "OTHER_RUN_12345678"}))

    def test_p2f3_semantic_run_id_is_accepted(self):
        self.assertEqual(mcp_parse.extract_run_identity({"structuredContent": {"runId": RUN_ID}}), RUN_ID)

    def test_p2f4_run_identity_mismatch(self):
        expect_error(self, "RUN_IDENTITY_MISMATCH", lambda: mcp_parse.run_metadata(
            {"structuredContent": {"runId": "OTHER_RUN_12345678", "status": "SUCCEEDED"}},
            expected_run_id=RUN_ID, require_dataset_id=False))

    def test_p2f4_run_identity_unavailable_precedes_expected_mismatch(self):
        expect_error(self, "RUN_IDENTITY_UNAVAILABLE", lambda: mcp_parse.run_metadata(
            {"structuredContent": {"status": "SUCCEEDED"}}, expected_run_id=RUN_ID,
            require_dataset_id=False))

    def test_p2f4_run_identity_conflict(self):
        expect_error(self, "RUN_IDENTITY_CONFLICT", lambda: mcp_parse.run_metadata(
            {"structuredContent": {"runId": RUN_ID, "actorRunId": "OTHER_RUN_12345678",
                                   "status": "SUCCEEDED"}}, expected_run_id=RUN_ID,
            require_dataset_id=False))

    def test_p2f4_nonterminal_or_missing_run_status(self):
        for status in ("RUNNING", None):
            payload = {"structuredContent": {"runId": RUN_ID}}
            if status:
                payload["structuredContent"]["status"] = status
            expect_error(self, "RUN_NOT_TERMINAL", lambda p=payload: mcp_parse.run_metadata(
                p, expected_run_id=RUN_ID, require_dataset_id=False))

    def test_p2f4_dataset_item_count_mismatch(self):
        payload = json.loads(json.dumps(FIXTURE["dataset"]))
        payload["structuredContent"]["itemCount"] = 3
        expect_error(self, "DATASET_COUNT_MISMATCH", lambda: mcp_parse.dataset_items(
            payload, expected_dataset_id=DATASET_ID, expected_run_item_count=2))

    def test_p2f4_dataset_run_binding_mismatch_echo(self):
        payload = json.loads(json.dumps(FIXTURE["dataset"]))
        payload["structuredContent"]["datasetId"] = "OTHER_DATASET_ID"
        expect_error(self, "DATASET_RUN_BINDING_MISMATCH", lambda: mcp_parse.dataset_items(
            payload, expected_dataset_id=DATASET_ID, expected_run_item_count=2))

    def test_p2f4_dataset_run_binding_mismatch_total_count(self):
        payload = json.loads(json.dumps(FIXTURE["dataset"]))
        payload["structuredContent"]["totalItemCount"] = 3
        expect_error(self, "DATASET_RUN_BINDING_MISMATCH", lambda: mcp_parse.dataset_items(
            payload, expected_dataset_id=DATASET_ID, expected_run_item_count=2))

    def test_p2f4_missing_or_malformed_dataset_tool_result(self):
        for payload in ({}, {"structuredContent": None}, {"content": []},
                        {"structuredContent": {"items": "not-an-array"}}):
            expect_error(self, "ITEMS_NOT_FOUND", lambda p=payload: mcp_parse.dataset_items(p))


class AcceptanceDatasetIdentityTests(unittest.TestCase):
    def run_without_dataset_identity(self):
        return mcp_parse.run_metadata(
            {"structuredContent": {"runId": RUN_ID, "status": "SUCCEEDED"}},
            expected_run_id=RUN_ID, require_dataset_id=False,
        )

    def page_without_dataset_identity(self):
        payload = json.loads(json.dumps(FIXTURE["dataset"]))
        payload["structuredContent"].pop("datasetId")
        return mcp_parse.dataset_items(payload)

    def test_p3_w4_02_both_dataset_ids_missing_fail_closed(self):
        expect_error(self, "DATASET_RUN_BINDING_MISMATCH", lambda: mcp_parse.acceptance(
            self.run_without_dataset_identity(), self.page_without_dataset_identity(), EXPECTED))

    def test_p3_w4_02_missing_run_identity_fails_closed(self):
        run = mcp_parse.run_metadata(FIXTURE["run"], expected_run_id=RUN_ID)
        page = mcp_parse.dataset_items(FIXTURE["dataset"], expected_dataset_id=DATASET_ID,
                                       expected_run_item_count=2)
        expect_error(self, "RUN_IDENTITY_UNAVAILABLE", lambda: mcp_parse.acceptance(
            replace(run, run_id=None), page, EXPECTED))

    def test_p3_w4_02_only_run_dataset_id_missing_fails_closed(self):
        page = mcp_parse.dataset_items(FIXTURE["dataset"], expected_dataset_id=DATASET_ID,
                                       expected_run_item_count=2)
        expect_error(self, "DATASET_RUN_BINDING_MISMATCH", lambda: mcp_parse.acceptance(
            self.run_without_dataset_identity(), page, EXPECTED))

    def test_p3_w4_02_only_dataset_echo_missing_fails_closed(self):
        payload = json.loads(json.dumps(FIXTURE["dataset"]))
        payload["structuredContent"].pop("datasetId")
        page = mcp_parse.dataset_items(payload)
        run = mcp_parse.run_metadata(FIXTURE["run"], expected_run_id=RUN_ID)
        expect_error(self, "DATASET_RUN_BINDING_MISMATCH", lambda: mcp_parse.acceptance(run, page, EXPECTED))

    def test_p3_w4_02_conflicting_dataset_ids_fail_closed(self):
        payload = json.loads(json.dumps(FIXTURE["dataset"]))
        payload["structuredContent"]["datasetId"] = "OTHER_DATASET_ID"
        page = mcp_parse.dataset_items(payload)
        run = mcp_parse.run_metadata(FIXTURE["run"], expected_run_id=RUN_ID)
        expect_error(self, "DATASET_RUN_BINDING_MISMATCH", lambda: mcp_parse.acceptance(run, page, EXPECTED))

    def test_p3_w4_02_matching_dataset_identity_passes(self):
        run = mcp_parse.run_metadata(FIXTURE["run"], expected_run_id=RUN_ID,
                                     expected_build_number="0.0.50",
                                     expected_build_id="aJLRmMdQapLQRT4sJ")
        page = mcp_parse.dataset_items(FIXTURE["dataset"], expected_dataset_id=DATASET_ID,
                                       expected_run_item_count=2)
        result = mcp_parse.acceptance(run, page, EXPECTED,
                                      expected_build_number="0.0.50",
                                      expected_build_id="aJLRmMdQapLQRT4sJ")
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["functionalVerdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
