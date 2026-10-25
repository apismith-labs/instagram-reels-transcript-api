"""Hermetic replay through the four minimal, repository-managed MCP adapters."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import mcp_adapters, mcp_parse

FIXTURE = json.loads((ROOT / "tests/fixtures/dx2-native-mcp-record.redacted.json").read_text())
RUN_ID = "JyaFWeQ1SrLXIteIK"
DATASET_ID = "MHT7DmSNRX0kmcsKg"


class SharedParserAdapterIntegrationTests(unittest.TestCase):
    def test_captured_fixture_replays_across_all_repository_adapters(self):
        run_payload = FIXTURE["run"]
        dataset_payload = FIXTURE["dataset"]
        shortcodes = FIXTURE["expectedShortcodes"]
        adapter_calls = (
            (mcp_adapters.l2_run, mcp_adapters.l2_dataset, mcp_adapters.l2_classify),
            (mcp_adapters.l2_recovery_run, mcp_adapters.l2_recovery_dataset,
             mcp_adapters.l2_recovery_classify),
            (mcp_adapters.l3a_bulk_run, mcp_adapters.l3a_bulk_dataset,
             mcp_adapters.l3a_bulk_classify),
            (mcp_adapters.l3a_recovery_run, mcp_adapters.l3a_recovery_dataset,
             mcp_adapters.l3a_recovery_classify),
        )
        results = []
        for parse_run, parse_dataset, accept in adapter_calls:
            run = parse_run(run_payload, RUN_ID)
            page = parse_dataset(dataset_payload, DATASET_ID, 2)
            results.append(accept(run, page, shortcodes))
        self.assertTrue(all(result["verdict"] == "PASS" for result in results))
        self.assertTrue(all(result["functionalVerdict"] == "PASS" for result in results))
        self.assertTrue(all(result["buildVerified"] == "UNVERIFIED_SOURCE_ABSENT" for result in results))
        self.assertTrue(all(result["runSource"] == "MCP"
                            and result["datasetSource"] == "get-dataset-items" for result in results))
        self.assertTrue(all(result["itemCount"] == result["totalItemCount"] == result["parsedItems"] == 2
                            for result in results))
        self.assertTrue(all(result["complete"] is True and result["costCapStatus"] == "NOT_VERIFIED"
                            for result in results))
        expected = [{"match": "matched", "segments_count": 15},
                    {"match": "matched", "segments_count": 14}]
        for result in results:
            self.assertEqual([{k: row[k] for k in ("match", "segments_count")}
                              for row in result["results"]], expected)
            self.assertEqual(result["extras"], [])
            self.assertEqual(result["businessErrors"], 0)
        self.assertIs(mcp_adapters.mcp_parse, mcp_parse)
        self.assertFalse(any(hasattr(mcp_adapters, name)
                             for name in ("call_actor", "create_actor_run", "rest_get")))

    def test_every_adapter_entrypoint_is_repository_managed_and_shared(self):
        for name in dir(mcp_adapters):
            if name.endswith(("_run", "_dataset", "_classify")) or name == "l3a_bulk_run_id":
                self.assertTrue(callable(getattr(mcp_adapters, name)), name)
        self.assertEqual(mcp_adapters.l3a_bulk_run_id(FIXTURE["run"], RUN_ID), RUN_ID)

    def test_l3a_bulk_run_identity_rejects_dataset_store_and_opaque_ids(self):
        for payload in (
            {"storages": {"datasets": {"default": {"id": RUN_ID}}}},
            {"storages": {"keyValueStores": {"default": {"id": RUN_ID}}}},
            {"id": "A1234567890123456"},
        ):
            with self.assertRaises(mcp_parse.MCPParseError) as caught:
                mcp_adapters.l3a_bulk_run_id(payload)
            self.assertEqual(caught.exception.code, "RUN_IDENTITY_UNAVAILABLE")

    def test_l3a_bulk_run_identity_rejects_conflict_and_accepts_expected_run(self):
        with self.assertRaises(mcp_parse.MCPParseError) as caught:
            mcp_adapters.l3a_bulk_run_id({"runId": RUN_ID, "actorRunId": "OTHER_RUN_12345678"})
        self.assertEqual(caught.exception.code, "RUN_IDENTITY_CONFLICT")
        with self.assertRaises(mcp_parse.MCPParseError) as caught:
            mcp_adapters.l3a_bulk_run_id({"runId": "OTHER_RUN_12345678"}, RUN_ID)
        self.assertEqual(caught.exception.code, "RUN_IDENTITY_MISMATCH")


if __name__ == "__main__":
    unittest.main()
