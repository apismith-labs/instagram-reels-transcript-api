"""Offline tests for the pure L3-B Profile MCP payload adapter."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import mcp_adapters, mcp_parse

FIXTURE = json.loads((ROOT / "tests/fixtures/dx2-profile-synthetic.json").read_text())
RUN_ID = "synthetic-profile-run-001"
DATASET_ID = "synthetic-profile-dataset-001"


class ProfileAdapterTests(unittest.TestCase):
    def test_end_to_end_synthetic_profile_adapter_uses_shared_run_and_dataset_parser(self):
        run = mcp_adapters.l3b_profile_run(FIXTURE["run"], RUN_ID)
        dataset = mcp_adapters.l3b_profile_dataset(FIXTURE["dataset"], DATASET_ID, 1)
        result = mcp_adapters.l3b_profile_accept(run, [dataset], FIXTURE["input"]["usernames"],
                                                 results_limit=1, skip_pinned_posts=False)
        self.assertEqual(result["functionalVerdict"], "PASS")
        self.assertEqual(result["datasetSource"], "MCP")
        self.assertEqual(result["itemsSource"], "structuredContent.items")
        self.assertEqual(result["datasetIdPath"], "storages.datasets.default.id")
        self.assertEqual(result["datasetCompleteness"], "COMPLETE")
        self.assertEqual(result["buildVerified"], "UNVERIFIED_SOURCE_ABSENT")
        self.assertEqual(result["items"][0]["attribution"], "MATCHED_OWNER")
        self.assertEqual(result["items"][0]["segments_count"], 1)
        self.assertEqual(mcp_adapters.mcp_parse, mcp_parse)

    def test_build_drift_is_separate_from_profile_functional_verdict(self):
        run_payload = json.loads(json.dumps(FIXTURE["run"]))
        run_payload["structuredContent"]["buildNumber"] = "0.0.49"
        run_payload["structuredContent"]["buildId"] = "synthetic-wrong-build-id"
        run = mcp_adapters.l3b_profile_run(run_payload, RUN_ID)
        page = mcp_adapters.l3b_profile_dataset(FIXTURE["dataset"], DATASET_ID, 1)
        result = mcp_adapters.l3b_profile_accept(run, [page], ["synthetic_creator"])
        self.assertEqual(result["functionalVerdict"], "PASS")
        self.assertEqual(result["buildVerified"], "BUILD_DRIFT")
        self.assertEqual(result["verdict"], "BUILD_DRIFT")

    def test_adapter_accepts_multiple_pages_but_does_not_claim_missing_total(self):
        first = {"structuredContent": {"datasetId": DATASET_ID, "itemCount": 1,
            "totalItemCount": 2, "offset": 0, "limit": 1,
            "items": [{"ownerUsername": "creator", "type": "Video", "code": "first"}]}}
        second = {"structuredContent": {"datasetId": DATASET_ID, "itemCount": 1,
            "totalItemCount": 2, "offset": 1, "limit": 1,
            "items": [{"ownerUsername": "creator", "type": "Video", "code": "second"}]}}
        pages = [mcp_adapters.l3b_profile_dataset(first, DATASET_ID),
                 mcp_adapters.l3b_profile_dataset(second, DATASET_ID)]
        multi_run_payload = json.loads(json.dumps(FIXTURE["run"]))
        multi_run_payload["structuredContent"]["storages"]["datasets"]["default"]["itemCount"] = 2
        result = mcp_adapters.l3b_profile_accept(mcp_adapters.l3b_profile_run(multi_run_payload, RUN_ID),
                                                  pages, ["creator"])
        self.assertEqual(result["datasetCompleteness"], "COMPLETE")
        no_total = {"structuredContent": {"datasetId": DATASET_ID, "itemCount": 1, "offset": 0,
            "items": [{"ownerUsername": "creator", "type": "Video", "code": "first"}]}}
        unknown = mcp_adapters.l3b_profile_dataset(no_total, DATASET_ID)
        result = mcp_adapters.l3b_profile_accept(mcp_adapters.l3b_profile_run(FIXTURE["run"], RUN_ID),
                                                  [unknown], ["creator"])
        self.assertEqual(result["functionalVerdict"], "COMPLETENESS_UNKNOWN")

    def test_mismatched_dataset_echo_and_mcp_error_are_typed(self):
        mismatched = {"structuredContent": {"datasetId": "other-dataset", "itemCount": 0,
            "totalItemCount": 0, "offset": 0, "items": []}}
        self.assertEqual(mcp_adapters.l3b_profile_dataset_response(mismatched, DATASET_ID)["status"],
                         "DATASET_RUN_BINDING_MISMATCH")
        errored = {"isError": True, "structuredContent": {"items": []}}
        self.assertEqual(mcp_adapters.l3b_profile_dataset_response(errored, DATASET_ID)["status"],
                         "MCP_RESPONSE_ERROR")
        self.assertEqual(mcp_adapters.l3b_profile_dataset_response(
            {"structuredContent": {"items": "bad"}}, DATASET_ID)["status"], "ITEMS_UNAVAILABLE")
        run_error = mcp_adapters.l3b_profile_run_response({"isError": True}, RUN_ID)
        self.assertEqual(run_error["status"], "MCP_RESPONSE_ERROR")
        missing_run = mcp_adapters.l3b_profile_run_response({"structuredContent": {}}, RUN_ID)
        self.assertEqual(missing_run["status"], "MCP_RESPONSE_ERROR")
        self.assertEqual(missing_run["items"], [])
        self.assertEqual(missing_run["datasetCompleteness"], "UNKNOWN")
        self.assertEqual(missing_run["itemsSource"], "UNKNOWN")
        self.assertIsNone(missing_run["totalItemCount"])

    def test_run_dataset_id_absent_and_conflicting_paths_are_typed(self):
        absent = mcp_adapters.l3b_profile_run_response(
            {"structuredContent": {"runId": RUN_ID, "status": "SUCCEEDED"}}, RUN_ID)
        self.assertEqual(absent["status"], "MCP_RESPONSE_ERROR")
        conflict = json.loads(json.dumps(FIXTURE["run"]))
        conflict["structuredContent"]["defaultDatasetId"] = "different-dataset-id"
        parsed = mcp_adapters.l3b_profile_run_response(conflict, RUN_ID)
        self.assertEqual(parsed["status"], "DATASET_ID_CONFLICT")

    def test_content_json_source_propagates_to_profile_acceptance(self):
        run_content = {"content": [{"type": "text", "text": json.dumps({
            "runId": RUN_ID, "status": "SUCCEEDED",
            "storages": {"datasets": {"default": {"id": DATASET_ID, "itemCount": 1}}},
        })}]}
        dataset_content = {"content": [{"type": "text", "text": json.dumps({
            "datasetId": DATASET_ID, "itemCount": 1, "totalItemCount": 1, "offset": 0,
            "items": [{"ownerUsername": "creator", "type": "Video", "code": "content-only"}],
        })}]}
        run = mcp_adapters.l3b_profile_run(run_content, RUN_ID)
        page = mcp_adapters.l3b_profile_dataset(dataset_content, DATASET_ID, 1)
        accepted = mcp_adapters.l3b_profile_accept(run, [page], ["creator"])
        self.assertEqual(accepted["itemsSource"], "content[0].text.items")
        self.assertEqual(accepted["datasetSource"], "MCP")
        self.assertEqual(accepted["datasetIdPath"], "content[0].text.storages.datasets.default.id")
        self.assertEqual((accepted["itemCount"], accepted["totalItemCount"], accepted["parsedItemCount"]),
                         (1, 1, 1))

    def test_unobserved_dataset_source_is_unknown_not_a_fabricated_mcp_path(self):
        run = mcp_adapters.l3b_profile_run(FIXTURE["run"], RUN_ID)
        page = mcp_parse.DatasetPage(DATASET_ID,
            ({"ownerUsername": "synthetic_creator", "type": "Video", "code": "synthetic"},),
            1, 1, 0, 1, "", True, ())
        accepted = mcp_adapters.l3b_profile_accept(run, [page], ["synthetic_creator"])
        self.assertEqual(accepted["itemsSource"], "UNKNOWN")
        self.assertEqual(accepted["datasetSource"], "UNKNOWN")

    def test_adapter_exports_no_transport_or_creation_path(self):
        forbidden = ("call_actor", "create_actor_run", "rest_get", "transport", "fetch")
        self.assertFalse(any(hasattr(mcp_adapters, name) for name in forbidden))
        self.assertTrue(callable(mcp_adapters.l3b_profile_run))
        self.assertTrue(callable(mcp_adapters.l3b_profile_run_response))
        self.assertTrue(callable(mcp_adapters.l3b_profile_dataset))
        self.assertTrue(callable(mcp_adapters.l3b_profile_accept))


if __name__ == "__main__":
    unittest.main()
