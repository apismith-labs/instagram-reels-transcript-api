import json
import unittest
from pathlib import Path

from offline_support import FakeActorClient, FakeTransport, load_fixture

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs/audit/contracts/instagram-transcripts-scraper-0.0.50.json"


class OfflineContractTests(unittest.TestCase):
    def test_contract_is_audit_derived_and_keeps_unknowns(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["actor"]["buildNumber"], "0.0.50")
        self.assertEqual(contract["evidenceStatus"], "normalized_from_audit_report")
        self.assertEqual(contract["input"]["modeRule"]["exactlyOneOf"], ["videoUrl", "bulkUrls", "usernames"])
        self.assertEqual(contract["input"]["fields"]["resultsLimit"]["multiAccountScope"], "unknown")
        self.assertIn("sessionid", contract["knownUnknowns"][0])
        self.assertEqual(contract["input"]["fields"]["videoUrl"]["runtimeDefault"], "unknown")

    def test_all_required_synthetic_fixtures_are_marked(self):
        names = [p.name for p in (ROOT / "tests/fixtures").glob("*.synthetic.json")]
        self.assertEqual(len(names), 10)
        for name in names:
            self.assertTrue(load_fixture(name)["_fixture"].startswith("SYNTHETIC"), name)

    def test_bulk_partial_and_out_of_order_map_by_url(self):
        partial = load_fixture("bulk-partial.synthetic.json")
        out_of_order = load_fixture("bulk-out-of-order.synthetic.json")
        self.assertEqual(len(partial["items"]), 2)
        self.assertTrue(any(item.get("errMsg") for item in partial["items"]))
        self.assertNotEqual(out_of_order["input"]["bulkUrls"][0], out_of_order["items"][0]["url"])
        self.assertEqual({x["url"] for x in out_of_order["items"]}, set(out_of_order["input"]["bulkUrls"]))

    def test_profile_non_video_does_not_require_transcript_or_media(self):
        item = load_fixture("profile-non-video.synthetic.json")["items"][0]
        self.assertEqual(item["type"], "image")
        self.assertNotIn("text", item)
        self.assertNotIn("audioUrl", item)

    def test_fake_transport_records_calls_and_raises_queued_error(self):
        transport = FakeTransport([{"data": {"id": "synthetic-run"}}, TimeoutError("synthetic timeout")])
        self.assertEqual(transport.request("POST", "/runs")["data"]["id"], "synthetic-run")
        with self.assertRaises(TimeoutError):
            transport.request("GET", "/runs/synthetic-run")
        self.assertEqual((transport.post_count, transport.get_count), (1, 1))

    def test_fake_actor_client_tracks_run_status_and_dataset(self):
        client = FakeActorClient(run_responses=[{"id": "synthetic-run"}], status_responses=[{"status": "SUCCEEDED"}], dataset_responses=[[{"url": "synthetic"}]])
        run = client.start_run("synthetic/actor", {"videoUrl": "synthetic"})
        status = client.get_run(run["id"])
        items = client.get_dataset("synthetic-dataset")
        self.assertEqual(client.run_ids, ["synthetic-run"])
        self.assertEqual(client.polled_run_ids, ["synthetic-run"])
        self.assertEqual(client.dataset_ids, ["synthetic-dataset"])
        self.assertEqual(status["status"], "SUCCEEDED")
        self.assertEqual(len(items), 1)


if __name__ == "__main__":
    unittest.main()
