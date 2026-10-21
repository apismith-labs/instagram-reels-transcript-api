import importlib
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
import client as api_client  # noqa: E402
from reliable_actor import ApiError, APPROVED_BUILD_ID  # noqa: E402
from offline_support import FakeTransport  # noqa: E402

URL = "https://www.instagram.com/reels/synthetic-reel/"


def success_transport(item=None):
    actor_item = item or {
        "text": "Synthetic transcript",
        "segments": [{"text": "Synthetic segment", "start": 0, "end": 1}],
        "title": "Synthetic title",
        "duration": 3,
        "timestamp": 123,
        "unknownActorField": {"keep": True},
    }
    return FakeTransport([
        {"data": {"id": "run-synthetic", "defaultDatasetId": "dataset-synthetic", "buildNumber": "0.0.50", "buildId": APPROVED_BUILD_ID}},
        {"data": {"status": "SUCCEEDED", "defaultDatasetId": "dataset-synthetic"}},
        [actor_item],
    ])


class ReusableClientTests(unittest.TestCase):
    def test_import_is_network_and_credential_inert(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("import attempted network")) as opener:
            with patch("os.getenv", side_effect=AssertionError("import read environment credentials")):
                importlib.reload(api_client)
        opener.assert_not_called()

    def test_url_and_token_configuration_errors_happen_before_post(self):
        transport = FakeTransport([])
        for url in (None, "", "[reel](https://www.instagram.com/reels/x/)", "http://www.instagram.com/reels/x/", "https://example.com/reel/x/"):
            with self.subTest(url=url):
                with self.assertRaises(api_client.ConfigurationError):
                    api_client.get_transcript(url, token="synthetic-token", transport=transport)
                self.assertEqual(transport.post_count, 0)

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(api_client.ConfigurationError, "APIFY_TOKEN is required"):
                api_client.get_transcript(URL, transport=transport)
        self.assertEqual(transport.post_count, 0)

    def test_explicit_token_takes_priority_over_environment(self):
        transport = success_transport()
        seen = {}

        def make_transport(token):
            seen["token"] = token
            return transport

        with patch.dict(os.environ, {"APIFY_TOKEN": "synthetic-environment-token"}, clear=True):
            with patch.object(api_client, "RestTransport", side_effect=make_transport):
                result = api_client.get_transcript(URL, token="synthetic-explicit-token")
        self.assertEqual(seen["token"], "synthetic-explicit-token")
        self.assertTrue(result.succeeded)

    def test_success_result_exposes_text_segments_and_original_actor_item(self):
        transport = success_transport()
        result = api_client.get_transcript(URL, token="synthetic-token", transport=transport, timeout=5)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.text, "Synthetic transcript")
        self.assertEqual(result.segments[0]["text"], "Synthetic segment")
        self.assertEqual(result.items[0]["title"], "Synthetic title")
        self.assertEqual(result.items[0]["duration"], 3)
        self.assertEqual(result.items[0]["timestamp"], 123)
        self.assertEqual(result.items[0]["unknownActorField"], {"keep": True})
        self.assertEqual((result.run_id, result.dataset_id, result.source_url, result.dataset_complete),
            ("run-synthetic", "dataset-synthetic", URL, True))
        post = next(request for request in transport.requests if request["method"] == "POST")
        self.assertEqual(post["query"]["build"], "0.0.50")
        self.assertEqual(post["body"], {"videoUrl": URL})

    def test_actor_business_error_is_a_result_state(self):
        transport = success_transport({"errMsg": "synthetic failure", "url": URL, "title": "Synthetic failed item"})
        result = api_client.get_transcript(URL, token="synthetic-token", transport=transport)
        self.assertEqual(result.status, "actor_error")
        self.assertIsNone(result.text)
        self.assertIn("synthetic failure", result.error)
        self.assertEqual(result.items[0]["title"], "Synthetic failed item")

    def test_unknown_creation_raises_distinct_no_blind_retry_exception(self):
        transport = FakeTransport([ApiError("synthetic timeout", ambiguous=True)])
        with self.assertRaises(api_client.CreationUnknownError):
            api_client.get_transcript(URL, token="synthetic-token", transport=transport)
        self.assertEqual(transport.post_count, 1)

    def test_build_timeout_and_charge_configuration_fail_before_post(self):
        transport = FakeTransport([])
        invalid_options = (
            {"build": "latest"},
            {"timeout": 0},
            {"max_total_charge_usd": "not-a-number", "require_charge_cap": True},
            {"dataset_limit": 0},
        )
        for options in invalid_options:
            with self.subTest(options=options):
                with self.assertRaises(api_client.ConfigurationError):
                    api_client.get_transcript(URL, token="synthetic-token", transport=transport, **options)
                self.assertEqual(transport.post_count, 0)

    def test_build_mismatch_raises_protocol_error_with_known_run_id(self):
        transport = FakeTransport([{
            "data": {"id": "run-wrong-build", "defaultDatasetId": "dataset-wrong-build",
                "buildNumber": "0.0.50", "buildId": "synthetic-wrong-build"},
        }])
        with self.assertRaises(api_client.ProtocolError) as captured:
            api_client.get_transcript(URL, token="synthetic-token", transport=transport)
        self.assertEqual(captured.exception.run_id, "run-wrong-build")
        self.assertEqual(captured.exception.dataset_id, "dataset-wrong-build")
        self.assertEqual(transport.post_count, 1)

    def test_post_creation_then_get_failure_raises_with_existing_run_identity(self):
        transport = FakeTransport([
            {"data": {"id": "run-existing", "defaultDatasetId": "dataset-existing", "buildNumber": "0.0.50", "buildId": APPROVED_BUILD_ID}},
            ApiError("synthetic GET failure", status=401),
        ])
        with self.assertRaises(api_client.TranscriptTransportError) as captured:
            api_client.get_transcript(URL, token="synthetic-token", transport=transport)
        self.assertEqual(captured.exception.run_id, "run-existing")
        self.assertEqual(captured.exception.dataset_id, "dataset-existing")
        self.assertIn("do not call get_transcript again", str(captured.exception))
        self.assertEqual(transport.post_count, 1)

    def test_quickstart_help_is_safe_and_requires_an_explicit_url(self):
        import quickstart_single
        with self.assertRaises(SystemExit) as help_exit:
            quickstart_single.build_parser().parse_args(["--help"])
        self.assertEqual(help_exit.exception.code, 0)
        with self.assertRaises(SystemExit) as missing_exit:
            quickstart_single.build_parser().parse_args([])
        self.assertEqual(missing_exit.exception.code, 2)

    def test_default_call_creates_no_journal_or_other_files(self):
        transport = success_transport()
        with tempfile.TemporaryDirectory() as cwd:
            previous = Path.cwd()
            try:
                os.chdir(cwd)
                result = api_client.get_transcript(URL, token="synthetic-token", transport=transport)
                self.assertEqual(result.status, "success")
                self.assertEqual(list(Path(cwd).iterdir()), [])
            finally:
                os.chdir(previous)

    def test_copy_pair_imports_outside_repository_in_package_and_module_styles(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source_client = PYTHON_EXAMPLES / "client.py"
            source_runner = PYTHON_EXAMPLES / "reliable_actor.py"

            # Package-style import.
            package = root_path / "copied_integration"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            shutil.copy2(source_client, package / "client.py")
            shutil.copy2(source_runner, package / "reliable_actor.py")
            sys.path.insert(0, str(root_path))
            try:
                copied_package = importlib.import_module("copied_integration.client")
                self.assertEqual(copied_package.APPROVED_BUILD_NUMBER, "0.0.50")
            finally:
                sys.path.remove(str(root_path))
                for name in list(sys.modules):
                    if name == "copied_integration" or name.startswith("copied_integration."):
                        sys.modules.pop(name, None)

            # Side-by-side module import from another working directory.
            module_dir = root_path / "modules"
            module_dir.mkdir()
            shutil.copy2(source_client, module_dir / "client.py")
            shutil.copy2(source_runner, module_dir / "reliable_actor.py")
            old_client, old_runner = sys.modules.pop("client", None), sys.modules.pop("reliable_actor", None)
            sys.path.insert(0, str(module_dir))
            previous = Path.cwd()
            elsewhere = root_path / "elsewhere"
            elsewhere.mkdir()
            try:
                os.chdir(elsewhere)
                copied_module = importlib.import_module("client")
                self.assertEqual(Path(copied_module.__file__).resolve().parent, module_dir.resolve())
                self.assertEqual(copied_module.APPROVED_BUILD_NUMBER, "0.0.50")
                copied_result = copied_module.get_transcript(URL, token="synthetic-token", transport=success_transport())
                self.assertEqual(copied_result.text, "Synthetic transcript")
                self.assertEqual(list(elsewhere.iterdir()), [])
            finally:
                os.chdir(previous)
                sys.path.remove(str(module_dir))
                sys.modules.pop("client", None)
                sys.modules.pop("reliable_actor", None)
                if old_client is not None:
                    sys.modules["client"] = old_client
                if old_runner is not None:
                    sys.modules["reliable_actor"] = old_runner


if __name__ == "__main__":
    unittest.main()
