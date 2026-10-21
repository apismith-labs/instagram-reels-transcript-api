import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
PYTHON_EXAMPLES = ROOT / "examples/python"
sys.path.insert(0, str(PYTHON_EXAMPLES))
import client as bulk_client  # noqa: E402
import quickstart_bulk  # noqa: E402
from offline_support import FakeTransport, load_fixture  # noqa: E402
from reliable_actor import ApiError, APPROVED_BUILD_ID  # noqa: E402

URLS = [
    "https://www.instagram.com/reels/synthetic-first/",
    "https://www.instagram.com/reels/synthetic-second/",
]


def transport_for(items, *, build_number="0.0.50", build_id=APPROVED_BUILD_ID, dataset_limit=20):
    dataset_responses = items if items and all(isinstance(value, list) for value in items) else [items]
    return FakeTransport([
        {"data": {"id": "run-bulk-synthetic", "defaultDatasetId": "dataset-bulk-synthetic",
                  "buildNumber": build_number, "buildId": build_id}},
        {"data": {"status": "SUCCEEDED", "defaultDatasetId": "dataset-bulk-synthetic"}},
        *dataset_responses,
    ])


class PythonNativeBulkTests(unittest.TestCase):
    def get_result(self, urls=URLS, items=None, **kwargs):
        transport = transport_for(items if items is not None else [
            {"url": URLS[1], "text": "Synthetic second", "segments": [{"t": 2}], "timestamp": 20},
            {"url": URLS[0], "text": "Synthetic first", "segments": [{"t": 1}], "title": "Synthetic title", "duration": 4, "unknownField": True},
        ])
        result = bulk_client.get_transcripts(urls, token="synthetic-token", transport=transport,
                                             dataset_limit=kwargs.pop("dataset_limit", 20), **kwargs)
        return result, transport

    def test_fixture_becomes_exactly_one_run_input_with_shared_safety_query(self):
        fixture = json.loads((ROOT / "tests/fixtures/live/tc02-native-bulk.json").read_text(encoding="utf-8"))
        self.assertEqual(fixture["bulkUrls"], [
            "https://www.instagram.com/reels/DeKRjqRFQuJ/",
            "https://www.instagram.com/reels/Da-FlEEDIO-/",
            "https://www.instagram.com/reels/Dc9GVvjBeZT/",
        ])
        transport = transport_for([[], [], []])
        result = bulk_client.get_transcripts(
            fixture["bulkUrls"], token="synthetic-token", transport=transport, dataset_limit=20,
            results_limit=fixture["resultsLimit"], skip_pinned_posts=fixture["skipPinnedPosts"],
            include_shares_count=fixture["includeSharesCount"], max_total_charge_usd="0.30", require_charge_cap=True,
        )
        self.assertEqual(transport.post_count, 1)
        post = next(row for row in transport.requests if row["method"] == "POST")
        self.assertEqual(post["body"], fixture)
        self.assertEqual(post["query"], {"restartOnError": "false", "maxTotalChargeUsd": 0.3, "build": "0.0.50"})
        self.assertNotIn("build", post["body"])
        self.assertNotIn("maxTotalChargeUsd", post["body"])
        self.assertEqual(result.run_id, "run-bulk-synthetic")
        self.assertEqual(result.status, "unknown")

    def test_out_of_order_fixture_maps_by_url_and_preserves_original_fields(self):
        fixture = load_fixture("bulk-out-of-order.synthetic.json")
        result, transport = self.get_result(fixture["input"]["bulkUrls"], fixture["items"])
        self.assertEqual(transport.post_count, 1)
        self.assertEqual(result.status, "all_success")
        self.assertEqual([row.text for row in result.results], ["Synthetic first.", "Synthetic second."])

        result, _ = self.get_result()
        self.assertEqual(result.status, "all_success")
        self.assertEqual(result.results[0].item["title"], "Synthetic title")
        self.assertEqual(result.results[0].item["duration"], 4)
        self.assertTrue(result.results[0].item["unknownField"])

    def test_partial_failure_retains_successful_sibling(self):
        fixture = load_fixture("bulk-partial.synthetic.json")
        result, transport = self.get_result(fixture["input"]["bulkUrls"], fixture["items"])
        self.assertEqual(transport.post_count, 1)
        self.assertEqual(result.status, "partial_success")
        self.assertEqual([row.status for row in result.results], ["success_transcript", "actor_error"])
        self.assertEqual(result.results[0].text, "Synthetic success.")
        self.assertIn("Synthetic item failure", result.results[1].error)
        self.assertEqual(sum(result.counts.values()), 2)

    def test_no_transcript_empty_missing_duplicate_and_extra_are_explicit(self):
        result, _ = self.get_result(items=[{"url": URLS[0], "text": "", "errMsg": ""},
                                          {"url": URLS[1], "text": None}])
        self.assertEqual([row.status for row in result.results], ["no_transcript", "no_transcript"])
        self.assertEqual(result.status, "all_failed")

        result, _ = self.get_result(items=[{"url": URLS[0], "text": "ok"}])
        self.assertEqual(result.results[1].status, "missing_result")
        self.assertEqual(result.status, "unknown")

        result, _ = self.get_result(items=[{"url": URLS[0], "text": "one"}, {"url": URLS[0], "text": "two"},
                                          {"url": "https://www.instagram.com/reel/not-input/", "text": "extra"}])
        self.assertEqual(result.results[0].status, "duplicate_result")
        self.assertEqual(len(result.extra_results), 1)
        self.assertEqual(result.status, "unknown")

    def test_exact_shortcode_fallback_only_when_url_absent(self):
        result, _ = self.get_result(items=[{"code": "synthetic-first", "text": "mapped"},
                                          {"url": URLS[1], "code": "synthetic-first", "text": "conflict"}])
        self.assertEqual(result.results[0].text, "mapped")
        self.assertEqual(result.results[1].status, "missing_result")
        self.assertEqual(len(result.extra_results), 1)
        self.assertEqual(result.status, "unknown")

    def test_full_dataset_page_marks_absence_unknown_instead_of_missing(self):
        result, _ = self.get_result(items=[{"url": URLS[0], "text": "one"}, {"url": URLS[1], "text": "two"}], dataset_limit=2)
        self.assertFalse(result.dataset_complete)
        self.assertEqual([row.status for row in result.results], ["success_transcript", "success_transcript"])
        self.assertEqual(result.status, "unknown")

    def test_build_mismatch_and_creation_unknown_never_retry_post(self):
        transport = transport_for([], build_id="synthetic-wrong-build")
        with self.assertRaises(bulk_client.ProtocolError) as caught:
            bulk_client.get_transcripts(URLS, token="synthetic-token", transport=transport)
        self.assertEqual(caught.exception.run_id, "run-bulk-synthetic")
        self.assertEqual(transport.post_count, 1)
        self.assertEqual(transport.get_count, 0)

        transport = FakeTransport([ApiError("synthetic timeout", ambiguous=True)])
        with self.assertRaises(bulk_client.CreationUnknownError):
            bulk_client.get_transcripts(URLS, token="synthetic-token", transport=transport)
        self.assertEqual(transport.post_count, 1)

    def test_invalid_inputs_and_missing_token_fail_before_post(self):
        for values in ([], ["[reel](https://www.instagram.com/reels/x/)"], [URLS[0], URLS[0]]):
            transport = FakeTransport([])
            with self.assertRaises(bulk_client.ConfigurationError):
                bulk_client.get_transcripts(values, token="synthetic-token", transport=transport)
            self.assertEqual(transport.post_count, 0)
        transport = FakeTransport([])
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(bulk_client.ConfigurationError):
                bulk_client.get_transcripts(URLS, transport=transport)
        self.assertEqual(transport.post_count, 0)

    def test_explicit_token_works_independent_of_host_environment(self):
        transport = transport_for([{"url": URLS[0], "text": "one"}, {"url": URLS[1], "text": "two"}])
        with patch.dict(os.environ, {}, clear=True):
            result = bulk_client.get_transcripts(URLS, token="synthetic-explicit-token", transport=transport)
        self.assertEqual(result.status, "all_success")
        self.assertEqual(transport.post_count, 1)

    def test_utf8_and_newline_handling_uses_portable_temporary_paths(self):
        with tempfile.TemporaryDirectory(prefix="bulk utf8 空格 ") as temp:
            path = Path(temp) / "result.jsonl"
            with path.open("w", encoding="utf-8", newline="") as stream:
                stream.write('{"text":"合成结果"}\r\n')
            self.assertIn("合成结果", path.read_text(encoding="utf-8"))
            self.assertIn(b"\r\n", path.read_bytes())

    def test_new_python_files_have_no_machine_specific_proxy_or_home_path(self):
        for path in (PYTHON_EXAMPLES / "client.py", PYTHON_EXAMPLES / "quickstart_bulk.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("127.0.0.1:7897", source)
            self.assertNotIn("/Users/peng", source)

    def test_cli_parser_is_injectable_and_does_not_fetch_for_help_or_missing_args(self):
        called = []
        def fake_fetch(*args, **kwargs):
            called.append((args, kwargs))
            raise AssertionError("not expected")
        with self.assertRaises(SystemExit) as help_result:
            quickstart_bulk.run_cli(["--help"], fetch=fake_fetch)
        self.assertEqual(help_result.exception.code, 0)
        with self.assertRaises(SystemExit) as empty_result:
            quickstart_bulk.run_cli([], fetch=fake_fetch)
        self.assertEqual(empty_result.exception.code, 2)
        self.assertEqual(called, [])
        parsed = quickstart_bulk.build_parser().parse_args([*URLS, "--skip-pinned-posts", "false"])
        self.assertIs(parsed.skip_pinned_posts, False)

    def test_copy_pair_bulk_import_from_independent_non_ascii_working_directory(self):
        with tempfile.TemporaryDirectory(prefix="跨平台 Python Bulk ") as temp:
            base = Path(temp)
            module_dir = base / "integration"
            module_dir.mkdir()
            shutil.copy2(PYTHON_EXAMPLES / "client.py", module_dir / "client.py")
            shutil.copy2(PYTHON_EXAMPLES / "reliable_actor.py", module_dir / "reliable_actor.py")
            elsewhere = base / "独立工作目录"
            elsewhere.mkdir()
            old_cwd = Path.cwd()
            old_client, old_runner = sys.modules.pop("client", None), sys.modules.pop("reliable_actor", None)
            sys.path.insert(0, str(module_dir))
            try:
                os.chdir(elsewhere)
                copied = importlib.import_module("client")
                result = copied.get_transcripts(URLS, token="synthetic-token", transport=transport_for([
                    {"url": URLS[0], "text": "synthetic"}, {"url": URLS[1], "text": "synthetic"}
                ]), dataset_limit=20)
                self.assertEqual(result.status, "all_success")
                self.assertEqual(list(elsewhere.iterdir()), [])
            finally:
                os.chdir(old_cwd)
                sys.path.remove(str(module_dir))
                sys.modules.pop("client", None)
                sys.modules.pop("reliable_actor", None)
                if old_client is not None: sys.modules["client"] = old_client
                if old_runner is not None: sys.modules["reliable_actor"] = old_runner

    def test_windows_path_semantics_are_simulated_only(self):
        from pathlib import PureWindowsPath
        path = PureWindowsPath("C:/Users/Example App/project") / "examples" / "python" / "client.py"
        self.assertEqual(path.drive, "C:")
        self.assertTrue(str(path).endswith("examples\\python\\client.py"))


if __name__ == "__main__":
    unittest.main()
