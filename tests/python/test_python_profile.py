import importlib
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
PYTHON_EXAMPLES = ROOT / "examples/python"
sys.path.insert(0, str(PYTHON_EXAMPLES))
import client as profile_client  # noqa: E402
import quickstart_profile  # noqa: E402
from offline_support import FakeTransport, load_fixture  # noqa: E402
from reliable_actor import ApiError, APPROVED_BUILD_ID  # noqa: E402


def make_transport(items, *, build_number="0.0.50", build_id=APPROVED_BUILD_ID, repeats=1):
    responses = [
        {"data": {"id": "profile-run-synthetic", "defaultDatasetId": "profile-dataset-synthetic",
                  "buildNumber": build_number, "buildId": build_id}},
        {"data": {"status": "SUCCEEDED", "defaultDatasetId": "profile-dataset-synthetic"}},
        *([items] * repeats),
    ]
    return FakeTransport(responses)


class PythonProfileTests(unittest.TestCase):
    def call(self, usernames="synthetic_creator", items=None, **options):
        if items is None:
            items = [{"url": "https://www.instagram.com/p/synthetic-post/", "type": "image",
                      "ownerUsername": "synthetic_creator", "caption": "Synthetic caption."}]
        transport = make_transport(items)
        result = profile_client.get_profile_posts(usernames, token="synthetic-token", transport=transport, **options)
        return result, transport

    def test_single_and_multiple_username_inputs_create_canonical_profile_body(self):
        single = profile_client.build_profile_input("one.creator", results_limit=4, only_posts_newer_than="7 days",
                                                    skip_pinned_posts=True, include_shares_count=False)
        self.assertEqual(single, {"usernames": ["one.creator"], "resultsLimit": 4,
                                  "onlyPostsNewerThan": "7 days", "skipPinnedPosts": True,
                                  "includeSharesCount": False})
        transport = make_transport([] , repeats=3)
        result = profile_client.get_profile_posts(["one.creator", "two_creator"], token="synthetic-token",
                                                  transport=transport, results_limit=2, dataset_limit=10,
                                                  max_total_charge_usd="0.30", require_charge_cap=True)
        self.assertEqual(transport.post_count, 1)
        self.assertEqual(result.status, "empty")
        post = next(row for row in transport.requests if row["method"] == "POST")
        self.assertEqual(post["body"], {"usernames": ["one.creator", "two_creator"], "resultsLimit": 2})
        self.assertEqual(post["query"]["build"], "0.0.50")
        self.assertEqual(post["query"]["maxTotalChargeUsd"], 0.3)
        self.assertEqual(post["query"]["restartOnError"], "false")
        self.assertNotIn("videoUrl", post["body"])
        self.assertNotIn("bulkUrls", post["body"])

    def test_profile_image_and_video_without_transcript_are_success(self):
        image = load_fixture("profile-non-video.synthetic.json")["items"][0]
        video = load_fixture("profile-video.synthetic.json")["items"][0]
        for item in (image, video):
            with self.subTest(kind=item["type"]):
                result, transport = self.call(items=[item])
                self.assertEqual(result.status, "success")
                self.assertIsNone(result.error)
                self.assertEqual(transport.post_count, 1)
                self.assertEqual(result.posts[0].raw, item)
                self.assertNotIn("text", result.posts[0].raw)
                self.assertNotIn("segments", result.posts[0].raw)
        self.assertNotIn("text", profile_client.ProfilePost.__dataclass_fields__)
        self.assertNotIn("segments", profile_client.ProfilePost.__dataclass_fields__)

    def test_original_fields_and_owner_username_are_not_replaced_by_user_name(self):
        item = {"url": "https://www.instagram.com/reel/synthetic-video/", "type": "video",
                "ownerUsername": "synthetic_creator", "userName": "different_author",
                "caption": "Synthetic", "videoUrl": "https://cdn.invalid/video", "videoDuration": 9.5,
                "timestamp": "synthetic timestamp", "customField": {"keep": True}}
        result, _ = self.call(items=[item])
        post = result.posts[0]
        self.assertEqual((post.owner_username, post.type, post.video_url, post.video_duration),
                         ("synthetic_creator", "video", "https://cdn.invalid/video", 9.5))
        self.assertEqual(post.timestamp, "synthetic timestamp")
        self.assertEqual(post.raw["userName"], "different_author")
        self.assertEqual(post.raw["customField"], {"keep": True})

    def test_complete_empty_dataset_and_actor_item_error_have_distinct_states(self):
        transport = make_transport([], repeats=3)
        result = profile_client.get_profile_posts("synthetic_creator", token="synthetic-token", transport=transport)
        self.assertEqual(result.status, "empty")
        self.assertTrue(result.dataset_complete)
        self.assertEqual(transport.get_count, 4)  # Run GET plus three Dataset reads.

        result, _ = self.call(items=[{"errMsg": "Synthetic profile failure"}])
        self.assertEqual(result.status, "actor_error")
        self.assertEqual(result.posts[0].status, "actor_error")
        self.assertIn("Synthetic profile failure", result.posts[0].error)

    def test_unrecognized_items_and_ambiguous_multi_account_ownership_are_unknown(self):
        malformed = {"url": "https://example.invalid/not-a-post", "text": "Synthetic"}
        result, _ = self.call(items=[malformed])
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.posts[0].raw, malformed)

        no_owner = {"url": "https://www.instagram.com/p/synthetic-post/", "type": "image",
                    "userName": "one", "caption": "Synthetic"}
        result, _ = self.call(["one", "two"], items=[no_owner])
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.posts[0].status, "unknown")
        self.assertIsNone(result.posts[0].owner_username)

    def test_multi_account_shuffled_posts_only_attribute_from_owner_username(self):
        items = [
            {"url": "https://www.instagram.com/p/post-two/", "type": "carousel", "ownerUsername": "two", "caption": "2"},
            {"url": "https://www.instagram.com/reel/post-one/", "type": "video", "ownerUsername": "one", "caption": "1"},
        ]
        result, transport = self.call(["one", "two"], items=items)
        self.assertEqual(result.status, "success")
        self.assertEqual(transport.post_count, 1)
        self.assertEqual([post.owner_username for post in result.posts], ["two", "one"])
        self.assertEqual([post.raw for post in result.posts], items)

    def test_incomplete_dataset_is_unknown_even_with_valid_posts(self):
        items = [
            {"url": "https://www.instagram.com/p/one/", "type": "image", "ownerUsername": "synthetic_creator"},
            {"url": "https://www.instagram.com/p/two/", "type": "carousel", "ownerUsername": "synthetic_creator"},
        ]
        result, _ = self.call(items=items, dataset_limit=2)
        self.assertFalse(result.dataset_complete)
        self.assertEqual(result.status, "unknown")
        self.assertEqual([post.status for post in result.posts], ["success", "success"])

        with patch.object(profile_client, "execute_input", return_value={
            "status": "unknown", "runId": "run-truncated", "datasetId": "dataset-truncated",
            "rawItems": [], "datasetComplete": False,
        }):
            empty_incomplete = profile_client.get_profile_posts("synthetic_creator", token="synthetic-token")
        self.assertEqual(empty_incomplete.status, "unknown")
        self.assertFalse(empty_incomplete.dataset_complete)

    def test_input_and_configuration_errors_are_rejected_before_post(self):
        invalid_values = [
            ([], {}), ("", {}), ("@creator", {}), ("two words", {}), ("one/../two", {}),
            (".creator", {}), ("creator.", {}), ("two..dots", {}),
            (["one", "one"], {}), (["one", "One"], {}), (None, {}),
            ("creator", {"results_limit": 0}), ("creator", {"results_limit": True}),
            ("creator", {"only_posts_newer_than": "2026-02-31"}),
            ("creator", {"only_posts_newer_than": "2026-07-01T10:30:00Z"}),
            ("creator", {"only_posts_newer_than": "0 days"}),
            ("creator", {"skip_pinned_posts": 1}),
            ("creator", {"include_shares_count": "false"}),
            ("creator", {"dataset_limit": 0}),
            ("creator", {"max_total_charge_usd": "invalid", "require_charge_cap": True}),
        ]
        for usernames, options in invalid_values:
            with self.subTest(usernames=usernames, options=options):
                transport = FakeTransport([])
                with self.assertRaises(profile_client.ConfigurationError):
                    profile_client.get_profile_posts(usernames, token="synthetic-token", transport=transport, **options)
                self.assertEqual(transport.post_count, 0)
        transport = FakeTransport([])
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(profile_client.ConfigurationError, "APIFY_TOKEN"):
                profile_client.get_profile_posts("creator", transport=transport)
        self.assertEqual(transport.post_count, 0)

    def test_build_mismatch_preserves_ids_and_creation_unknown_is_not_retried(self):
        transport = make_transport([], build_id="synthetic-wrong-build")
        with self.assertRaises(profile_client.ProtocolError) as captured:
            profile_client.get_profile_posts("creator", token="synthetic-token", transport=transport)
        self.assertEqual((captured.exception.run_id, captured.exception.dataset_id),
                         ("profile-run-synthetic", "profile-dataset-synthetic"))
        self.assertEqual(transport.post_count, 1)
        self.assertEqual(transport.get_count, 0)

        transport = FakeTransport([ApiError("synthetic POST timeout", ambiguous=True)])
        with self.assertRaises(profile_client.CreationUnknownError):
            profile_client.get_profile_posts("creator", token="synthetic-token", transport=transport)
        self.assertEqual(transport.post_count, 1)

    def test_default_uses_no_journal_and_import_has_no_network_or_credential_side_effect(self):
        transport = make_transport([{"url": "https://www.instagram.com/p/one/", "type": "image"}])
        with tempfile.TemporaryDirectory(prefix="profile cwd 空格 ") as temp:
            old_cwd = Path.cwd()
            try:
                os.chdir(temp)
                result = profile_client.get_profile_posts("synthetic_creator", token="synthetic-token", transport=transport)
                self.assertEqual(result.status, "success")
                self.assertEqual(list(Path(temp).iterdir()), [])
            finally:
                os.chdir(old_cwd)
        with patch("urllib.request.urlopen", side_effect=AssertionError("unexpected network")):
            with patch("os.getenv", side_effect=AssertionError("unexpected credential read")):
                importlib.reload(profile_client)

    def test_quickstart_help_and_missing_usernames_do_not_call_fetch(self):
        calls = []
        def fetch(*args, **kwargs):
            calls.append(args)
            raise AssertionError("unexpected call")
        with self.assertRaises(SystemExit) as help_result:
            quickstart_profile.run_cli(["--help"], fetch=fetch)
        self.assertEqual(help_result.exception.code, 0)
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as missing_result:
                quickstart_profile.run_cli([], fetch=fetch)
        self.assertEqual(missing_result.exception.code, 2)
        self.assertEqual(calls, [])

        post = profile_client.ProfilePost(
            "https://www.instagram.com/p/synthetic/", "image", "synthetic_creator", "Synthetic caption",
            None, None, None, "success", {"url": "https://www.instagram.com/p/synthetic/", "type": "image"},
        )
        result = profile_client.ProfileResult("success", [post], ["synthetic_creator"], "run-id", "dataset-id", True, None, [post.raw])
        output = StringIO()
        with redirect_stdout(output):
            exit_code = quickstart_profile.run_cli(["synthetic_creator"], fetch=lambda *args, **kwargs: result)
        self.assertEqual(exit_code, 0)
        self.assertIn("type=image", output.getvalue())
        self.assertNotIn("transcript", output.getvalue().lower())

    def test_copy_pair_imports_and_runs_from_non_ascii_external_directory(self):
        with tempfile.TemporaryDirectory(prefix="profile integration 中文 ") as temp:
            base = Path(temp)
            target = base / "copied modules"
            target.mkdir()
            shutil.copy2(PYTHON_EXAMPLES / "client.py", target / "client.py")
            shutil.copy2(PYTHON_EXAMPLES / "reliable_actor.py", target / "reliable_actor.py")
            cwd = base / "other cwd 中文"
            cwd.mkdir()
            previous = Path.cwd()
            old_modules = {name: sys.modules.pop(name, None) for name in ("client", "reliable_actor")}
            sys.path.insert(0, str(target))
            try:
                os.chdir(cwd)
                copied = importlib.import_module("client")
                transport = make_transport([{"url": "https://www.instagram.com/p/one/", "type": "image"}])
                result = copied.get_profile_posts("synthetic_creator", token="synthetic-token", transport=transport)
                self.assertEqual(result.status, "success")
                self.assertEqual(list(cwd.iterdir()), [])
            finally:
                os.chdir(previous)
                sys.path.remove(str(target))
                for name in ("client", "reliable_actor"):
                    sys.modules.pop(name, None)
                    if old_modules[name] is not None:
                        sys.modules[name] = old_modules[name]


if __name__ == "__main__":
    unittest.main()
