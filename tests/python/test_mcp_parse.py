import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import mcp_parse


FIXTURE = json.loads((ROOT / "tests/fixtures/dx2-native-mcp-record.redacted.json").read_text())
EXPECTED = FIXTURE["expectedShortcodes"]
RUN = FIXTURE["run"]
DATASET = FIXTURE["dataset"]
RUN_ID = "JyaFWeQ1SrLXIteIK"
DATASET_ID = "MHT7DmSNRX0kmcsKg"


def run_meta(payload=RUN):
    return mcp_parse.run_metadata(payload, expected_run_id=RUN_ID)


def dataset_page(payload=DATASET, expected=DATASET_ID, run_count=2):
    return mcp_parse.dataset_items(payload, expected_dataset_id=expected,
                                   expected_run_item_count=run_count)


class NativeMCPParserTests(unittest.TestCase):
    """T-01 through T-22 from the W2 handoff, using an offline redacted capture."""

    def test_t01_captured_items_keep_media_fields_out_of_identity(self):
        result = mcp_parse.classify(dataset_page().items, EXPECTED)
        self.assertEqual([x["match"] for x in result["results"]], ["matched", "matched"])
        self.assertEqual([x["segments_count"] for x in result["results"]], [15, 14])
        self.assertTrue(all(x["transcript_present"] for x in result["results"]))
        self.assertEqual(result["verdict"], "PASS")

    def test_t02_url_and_code_agree(self):
        item = dataset_page().items[0]
        self.assertEqual(mcp_parse.reel_identity(item), (EXPECTED[0], "url+code"))

    def test_t03_url_and_code_disagreement_is_identity_conflict(self):
        item = dict(dataset_page().items[0], code=EXPECTED[1])
        result = mcp_parse.classify([item], [EXPECTED[0]])
        self.assertEqual(result["results"][0]["match"], "identity_conflict")
        self.assertNotEqual(result["verdict"], "PASS")

    def test_t04_nonempty_transcript_is_true(self):
        row = mcp_parse.classify(dataset_page().items[:1], [EXPECTED[0]])["results"][0]
        self.assertIs(row["transcript_present"], True)

    def test_t05_empty_or_missing_transcript_is_false_not_unknown(self):
        for item in (dict(dataset_page().items[0], text=""),
                     {k: v for k, v in dataset_page().items[0].items() if k != "text"}):
            row = mcp_parse.classify([item], [EXPECTED[0]])["results"][0]
            self.assertIs(row["transcript_present"], False)

    def test_t06_business_error_is_surfaced(self):
        item = dict(dataset_page().items[0], errMsg="captured business failure")
        row = mcp_parse.classify([item], [EXPECTED[0]])["results"][0]
        self.assertEqual(row["match"], "business_error")
        self.assertTrue(row["business_error"])

    def test_t07_record_order_does_not_change_attribution(self):
        forward = mcp_parse.classify(dataset_page().items, EXPECTED)
        reverse = mcp_parse.classify(list(reversed(dataset_page().items)), EXPECTED)
        self.assertEqual(forward["results"], reverse["results"])

    def test_t08_duplicate_and_extra_are_explicit(self):
        items = list(dataset_page().items)
        items.extend([dict(items[0]), dict(items[0], url="https://www.instagram.com/reel/extra-code/", code="extra-code")])
        result = mcp_parse.classify(items, EXPECTED)
        self.assertEqual(result["results"][0]["match"], "duplicate_matches")
        self.assertEqual(len(result["extras"]), 1)
        self.assertNotEqual(result["verdict"], "PASS")
        error_case = mcp_parse.classify(items + [dict(items[-1], errMsg="extra-row failure")], EXPECTED)
        self.assertGreaterEqual(error_case["businessErrors"], 1)
        self.assertTrue(any(row["businessError"] for row in error_case["extraDetails"]))

    def test_t09_recorded_run_resolves_dataset_id_by_exact_path(self):
        run = run_meta()
        self.assertEqual(run.dataset_id, DATASET_ID)
        self.assertEqual(run.dataset_id_path, "storages.datasets.default.id")
        self.assertEqual(run.run_id, RUN_ID)

    def test_t10_json_content_layer_is_a_valid_fallback(self):
        run_json = json.loads(RUN["content"][0]["text"])
        payload = {"content": [{"type": "text", "text": json.dumps({"runId": RUN_ID,
                    "status": "SUCCEEDED", "storages": run_json["storages"]})}]}
        run = mcp_parse.run_metadata(payload, expected_run_id=RUN_ID)
        self.assertEqual(run.dataset_id, DATASET_ID)
        self.assertTrue(run.dataset_id_path.startswith("content[0].text."))

    def test_t11_structured_items_are_selected(self):
        page = dataset_page()
        self.assertEqual(page.items_source, "structuredContent.items")
        self.assertEqual(len(page.items), 2)

    def test_t12_structured_items_beat_text_blocks(self):
        page = dataset_page()
        self.assertNotIn("type", page.items[0])
        self.assertIn("url", page.items[0])

    def test_t13_is_error_true_is_hard_failure(self):
        with self.assertRaises(mcp_parse.MCPParseError) as caught:
            mcp_parse.dataset_items(dict(DATASET, isError=True), expected_dataset_id=DATASET_ID)
        self.assertEqual(caught.exception.code, "MCP_TOOL_ERROR")
        self.assertFalse(mcp_parse.response_is_error({}))
        self.assertFalse(mcp_parse.response_is_error({"isError": False}))
        self.assertFalse(mcp_parse.response_is_error({"isError": 0}))

    def test_t14_disagreeing_dataset_ids_fail_closed(self):
        payload = json.loads(json.dumps(RUN))
        payload["structuredContent"]["datasetId"] = "OTHER_DATASET_ID"
        with self.assertRaises(mcp_parse.MCPParseError) as caught:
            mcp_parse.run_metadata(payload, expected_run_id=RUN_ID)
        self.assertEqual(caught.exception.code, "DATASET_ID_CONFLICT")

    def test_t15_missing_dataset_id_is_typed_unavailable(self):
        payload = {"structuredContent": {"runId": RUN_ID, "status": "SUCCEEDED"}}
        with self.assertRaises(mcp_parse.MCPParseError) as caught:
            mcp_parse.run_metadata(payload, expected_run_id=RUN_ID)
        self.assertEqual(caught.exception.code, "DATASET_ID_UNAVAILABLE")

    def test_t16_pagination_cannot_claim_completeness(self):
        payload = json.loads(json.dumps(DATASET))
        payload["structuredContent"]["offset"] = 1
        with self.assertRaises(mcp_parse.MCPParseError) as caught:
            mcp_parse.dataset_items(payload, expected_dataset_id=DATASET_ID)
        self.assertEqual(caught.exception.code, "INCOMPLETE_DATASET")
        payload = json.loads(json.dumps(DATASET))
        payload["structuredContent"]["totalItemCount"] = 3
        with self.assertRaises(mcp_parse.MCPParseError) as caught:
            mcp_parse.dataset_items(payload, expected_dataset_id=DATASET_ID)
        self.assertEqual(caught.exception.code, "INCOMPLETE_DATASET")

    def test_t17_missing_build_metadata_does_not_block_functional_pass(self):
        run = run_meta()
        page = dataset_page()
        accepted = mcp_parse.acceptance(run, page, EXPECTED)
        self.assertEqual(accepted["buildVerified"], "UNVERIFIED_SOURCE_ABSENT")
        self.assertEqual(accepted["verdict"], "PASS")

    def test_t18_ambiguous_create_transport_outcome_is_never_retry_signal(self):
        self.assertEqual(mcp_parse.creation_transport_outcome(request_sent=True, response_received=False), "OUTCOME_UNKNOWN")

    def test_t19_text_blocks_only_are_not_dataset_items(self):
        with self.assertRaises(mcp_parse.MCPParseError) as caught:
            mcp_parse.dataset_items({"content": [{"type": "text", "text": "not dataset rows"}]})
        self.assertEqual(caught.exception.code, "ITEMS_NOT_FOUND")

    def test_t20_negative_control_media_identity_regression(self):
        # The fixture has CDN media URLs; URL/code matching remains unchanged by them.
        rows = mcp_parse.classify(dataset_page().items, EXPECTED)["results"]
        self.assertTrue(all(row["match"] == "matched" for row in rows))

    def test_t21_shared_entry_point_is_order_and_envelope_invariant(self):
        # All client adapters call this same canonical classifier after extraction.
        baseline = mcp_parse.classify(dataset_page().items, EXPECTED)
        wrapped = {"structuredContent": {"items": list(reversed(dataset_page().items)),
                                         "datasetId": DATASET_ID, "itemCount": 2,
                                         "totalItemCount": 2, "offset": 0, "limit": 10}}
        from_wrapped = mcp_parse.classify(mcp_parse.dataset_items(wrapped, expected_dataset_id=DATASET_ID).items, EXPECTED)
        self.assertEqual(baseline["results"], from_wrapped["results"])

    def test_t22_cost_value_retains_observed_source_and_missing_is_none(self):
        run = run_meta()
        self.assertEqual(run.cost_value, 0.0155)
        self.assertEqual(run.cost_path, "_meta.com.apify/ActorRun.usageTotalUsd")
        payload = json.loads(json.dumps(RUN))
        payload.pop("_meta")
        missing = mcp_parse.run_metadata(payload, expected_run_id=RUN_ID)
        self.assertIsNone(missing.cost_value)
        self.assertIsNone(missing.cost_path)


if __name__ == "__main__":
    unittest.main()
