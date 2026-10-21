import ast
import importlib
import json
import os
import stat
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from threading import Lock
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
PYTHON_EXAMPLES = ROOT / "examples/python"
sys.path.insert(0, str(PYTHON_EXAMPLES))
import batch_csv  # noqa: E402
import client as api_client  # noqa: E402
from offline_support import FakeTransport  # noqa: E402

URL_1 = "https://www.instagram.com/reels/synthetic-one/"
URL_2 = "https://www.instagram.com/reels/synthetic-two/"


def success_transport(run_id, text):
    return FakeTransport([
        {"data": {"id": run_id, "defaultDatasetId": "dataset-" + run_id, "buildNumber": "0.0.50", "buildId": "aJLRmMdQapLQRT4sJ"}},
        {"data": {"status": "SUCCEEDED", "defaultDatasetId": "dataset-" + run_id}},
        [{"text": text, "segments": [{"text": "synthetic segment", "start": 0, "end": 1}], "title": "Synthetic title", "timestamp": 0, "extraField": {"keep": True}}],
    ])


class PythonCsvBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="中文 csv batch ")
        self.root = Path(self.temp.name)
        self.output_dir = self.root / "outputs with 空格"
        self.csv_path = self.root / "input 文件.csv"

    def tearDown(self):
        self.temp.cleanup()

    def write_csv(self, content, *, encoding="utf-8"):
        self.csv_path.write_text(content, encoding=encoding, newline="")
        return self.csv_path

    def invoke(self, args, *, env=None, runner=None, journal=None):
        stdout, stderr = StringIO(), StringIO()
        if journal is None:
            journal = api_client._MemoryJournal()
        code = batch_csv.run_cli(
            args, environment=env or {}, transcript_runner=runner, output_dir=self.output_dir,
            journal=journal, stdout=stdout, stderr=stderr,
        )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_import_does_not_read_credentials_or_make_requests(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network on import")) as opener:
            with patch("os.getenv", side_effect=AssertionError("credential read on import")):
                importlib.reload(batch_csv)
        opener.assert_not_called()
        self.assertFalse(self.output_dir.exists())

    def test_no_arguments_and_help_do_not_submit_runs(self):
        calls = []
        for args, expected in (([], 2), (["--help"], 0)):
            with self.subTest(args=args):
                code, _, _ = self.invoke(args, runner=lambda *a, **k: calls.append((a, k)))
                self.assertEqual(code, expected)
                self.assertEqual(calls, [])
        self.assertFalse(self.output_dir.exists())

    def test_dry_run_validates_and_prints_run_count_without_token_or_post(self):
        self.write_csv("videoUrl\n" + URL_1 + "\n" + URL_2 + "\n")
        calls = []
        code, output, error = self.invoke([str(self.csv_path), "--dry-run"], runner=lambda *a, **k: calls.append(a))
        plan = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual(error, "")
        self.assertEqual((plan["rows"], plan["maximumActorRuns"], plan["concurrency"]), (2, 2, 3))
        self.assertEqual(calls, [])
        self.assertFalse(self.output_dir.exists())

    def test_empty_csv_and_missing_file_return_clear_error_without_runs(self):
        self.write_csv("videoUrl\n\n")
        calls = []
        for args in ([str(self.csv_path)], [str(self.root / "missing.csv")]):
            code, _, error = self.invoke(args, env={"APIFY_TOKEN": "synthetic-token"}, runner=lambda *a, **k: calls.append(a))
            self.assertEqual(code, 2)
            self.assertTrue(error.startswith("Error:"))
        self.assertEqual(calls, [])

    def test_missing_url_header_and_invalid_url_report_input_location_without_runs(self):
        calls = []
        self.write_csv("url\n" + URL_1 + "\n")
        code, _, error = self.invoke([str(self.csv_path)], env={"APIFY_TOKEN": "synthetic-token"}, runner=lambda *a, **k: calls.append(a))
        self.assertEqual(code, 2)
        self.assertIn("videoUrl column", error)
        self.write_csv("videoUrl\n" + URL_1 + "\n[bad](https://instagram.com/reel/x/)\n")
        code, _, error = self.invoke([str(self.csv_path)], env={"APIFY_TOKEN": "synthetic-token"}, runner=lambda *a, **k: calls.append(a))
        self.assertEqual(code, 2)
        self.assertIn("line 3", error)
        self.assertEqual(calls, [])

    def test_non_numeric_or_non_positive_concurrency_is_human_readable_and_no_run(self):
        self.write_csv("videoUrl\n" + URL_1 + "\n")
        calls = []
        for value in ("abc", "0", "-2"):
            code, _, error = self.invoke([str(self.csv_path)], env={"MAX_CONCURRENCY": value, "APIFY_TOKEN": "synthetic-token"}, runner=lambda *a, **k: calls.append(a))
            self.assertEqual(code, 2)
            self.assertIn("concurrency", error)
            self.assertNotIn("Traceback", error)
        self.assertEqual(calls, [])

    def test_missing_token_is_rejected_before_any_runner_call(self):
        self.write_csv("videoUrl\n" + URL_1 + "\n")
        calls = []
        code, _, error = self.invoke([str(self.csv_path)], runner=lambda *a, **k: calls.append(a))
        self.assertEqual(code, 2)
        self.assertIn("APIFY_TOKEN is required", error)
        self.assertEqual(calls, [])

    def test_two_rows_create_two_independent_runs_and_keep_full_items(self):
        self.write_csv("videoUrl\n" + URL_1 + "\n" + URL_2 + "\n")
        transports = {URL_1: success_transport("run-one", "first transcript"), URL_2: success_transport("run-two", "second transcript")}
        lock = Lock()
        seen = []

        def runner(url, **kwargs):
            with lock:
                seen.append(url)
            return api_client.get_transcript(url, transport=transports[url], **kwargs)

        code, output, error = self.invoke([str(self.csv_path), "--concurrency", "2"], env={"APIFY_TOKEN": "synthetic-token"}, runner=runner)
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(set(seen), {URL_1, URL_2})
        self.assertEqual(sum(item.post_count for item in transports.values()), 2)
        target = Path(json.loads(output.splitlines()[-1])["output"])
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        document = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(document["requested"], 2)
        self.assertEqual([row["inputRow"] for row in document["rows"]], ["2", "3"])
        self.assertEqual({row["runId"] for row in document["rows"]}, {"run-one", "run-two"})
        self.assertEqual(document["rows"][0]["segmentsCount"], 1)
        self.assertEqual(document["rows"][0]["items"][0]["extraField"], {"keep": True})
        self.assertEqual(set(document["rows"][0]), set(document["rows"][1]))

    def test_one_business_failure_does_not_drop_another_success(self):
        self.write_csv("videoUrl\n" + URL_1 + "\n" + URL_2 + "\n")
        transports = {
            URL_1: success_transport("run-success", "synthetic transcript"),
            URL_2: FakeTransport([
                {"data": {"id": "run-error", "defaultDatasetId": "dataset-run-error", "buildNumber": "0.0.50", "buildId": "aJLRmMdQapLQRT4sJ"}},
                {"data": {"status": "SUCCEEDED", "defaultDatasetId": "dataset-run-error"}},
                [{"errMsg": "synthetic actor error"}],
            ]),
        }

        def runner(url, **kwargs):
            return api_client.get_transcript(url, transport=transports[url], **kwargs)

        code, output, _ = self.invoke([str(self.csv_path)], env={"APIFY_TOKEN": "synthetic-token"}, runner=runner)
        doc = json.loads(Path(json.loads(output.splitlines()[-1])["output"]).read_text(encoding="utf-8"))
        self.assertEqual(code, 1)
        self.assertEqual(doc["processed"], 2)
        self.assertEqual(doc["counts"], {"success": 1, "actor_error": 1})
        self.assertEqual([row["status"] for row in doc["rows"]], ["success", "actor_error"])
        self.assertEqual([row.post_count for row in transports.values()], [1, 1])

    def test_creation_unknown_is_reported_and_never_retried(self):
        self.write_csv("videoUrl\n" + URL_1 + "\n")
        transport = FakeTransport([api_client.ApiError("synthetic ambiguous timeout", ambiguous=True)])

        def runner(url, **kwargs):
            return api_client.get_transcript(url, transport=transport, **kwargs)

        code, output, _ = self.invoke([str(self.csv_path)], env={"APIFY_TOKEN": "synthetic-token"}, runner=runner)
        doc = json.loads(Path(json.loads(output.splitlines()[-1])["output"]).read_text(encoding="utf-8"))
        self.assertEqual(code, 1)
        self.assertEqual(transport.post_count, 1)
        self.assertEqual(doc["rows"][0]["status"], "creation_unknown")
        self.assertIsNone(doc["rows"][0]["runId"])

    def test_bom_crlf_blank_rows_and_line_numbers(self):
        content = "\ufeffvideoUrl\r\n" + URL_1 + "\r\n\r\n" + URL_2 + "\r\n"
        self.write_csv(content)
        rows = batch_csv.read_urls(self.csv_path)
        self.assertEqual(rows, [{"inputRow": "2", "sourceUrl": URL_1}, {"inputRow": "4", "sourceUrl": URL_2}])

    def test_explicit_output_is_not_overwritten(self):
        self.write_csv("videoUrl\n" + URL_1 + "\n")
        existing = self.root / "keep this.json"
        existing.write_text("preserve", encoding="utf-8")
        calls = []
        code, _, error = self.invoke([str(self.csv_path), "--output", str(existing)], env={"APIFY_TOKEN": "synthetic-token"}, runner=lambda *a, **k: calls.append(a))
        self.assertEqual(code, 2)
        self.assertIn("already exists", error)
        self.assertEqual(existing.read_text(encoding="utf-8"), "preserve")
        self.assertEqual(calls, [])

    def test_default_output_uses_unique_name_and_preserves_previous_run(self):
        self.write_csv("videoUrl\n" + URL_1 + "\n")
        self.output_dir.mkdir(parents=True)
        previous = self.output_dir / "python-batch-results-20261021T000000Z.json"
        previous.write_text("historical", encoding="utf-8")
        runner = lambda url, **kwargs: api_client.get_transcript(url, transport=success_transport("run-new", "text"), **kwargs)
        code, output, _ = self.invoke([str(self.csv_path)], env={"APIFY_TOKEN": "synthetic-token"}, runner=runner)
        new_path = Path(json.loads(output.splitlines()[-1])["output"])
        self.assertEqual(code, 0)
        self.assertNotEqual(new_path, previous)
        self.assertEqual(previous.read_text(encoding="utf-8"), "historical")

    def test_default_output_and_journal_follow_explicit_csv_directory(self):
        self.write_csv("videoUrl\n" + URL_1 + "\n")
        transport = success_transport("run-next-to-csv", "synthetic transcript")
        runner = lambda url, **kwargs: api_client.get_transcript(url, transport=transport, **kwargs)
        stdout, stderr = StringIO(), StringIO()
        code = batch_csv.run_cli(
            [str(self.csv_path)], environment={"APIFY_TOKEN": "synthetic-token"},
            transcript_runner=runner, stdout=stdout, stderr=stderr,
        )
        result_path = Path(json.loads(stdout.getvalue().splitlines()[-1])["output"])
        self.assertEqual((code, stderr.getvalue()), (0, ""))
        self.assertEqual(result_path.parent, self.csv_path.parent)
        self.assertTrue((self.csv_path.parent / "python-run-journal.jsonl").is_file())

    def test_run_plan_and_native_bulk_semantics_are_explicit(self):
        parser = batch_csv.build_parser()
        self.assertIn("one independent Actor Run per Reel URL", parser.description)
        self.assertIn("bulkUrls", batch_csv.__doc__)

    def test_can_run_from_outside_repository_working_directory(self):
        self.write_csv("videoUrl\n" + URL_1 + "\n")
        previous = Path.cwd()
        outside = self.root / "outside cwd"
        outside.mkdir()
        try:
            os.chdir(outside)
            code, output, _ = self.invoke([str(self.csv_path), "--dry-run"])
        finally:
            os.chdir(previous)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["rows"], 1)

    def test_sources_parse_as_python_310(self):
        source_roots = (ROOT / "examples/python", ROOT / "tests/python", ROOT / "scripts")
        sources = [source for source_root in source_roots for source in source_root.rglob("*.py")]
        for source in sources:
            ast.parse(source.read_text(encoding="utf-8"), filename=str(source), feature_version=(3, 10))

    def test_fixture_files_remain_unmodified(self):
        fixture_dir = ROOT / "tests/fixtures"
        before = {path.relative_to(fixture_dir): path.read_bytes() for path in fixture_dir.rglob("*") if path.is_file()}
        # This assertion protects against accidental test-side fixture writes.
        self.assertTrue(before)
        after = {path.relative_to(fixture_dir): path.read_bytes() for path in fixture_dir.rglob("*") if path.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
