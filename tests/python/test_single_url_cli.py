import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "examples/python"))
from single_url import format_output, prepare_cli_request  # noqa: E402
from offline_support import FakeTransport  # noqa: E402

URL = "https://www.instagram.com/reels/DeKRjqRFQuJ/"


class SingleUrlCliTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport([])
        self.invoke_count = 0

    def test_no_args_help_unknown_and_invalid_url_never_reach_transport(self):
        cases = ([], ["--help"], ["--mystery"], ["[Reel](https://www.instagram.com/reels/x/)"])
        for argv in cases:
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit):
                    prepare_cli_request(argv, {"APIFY_TOKEN": "synthetic-token"})
                self.assertEqual(self.transport.post_count, 0)
                self.assertEqual(self.invoke_count, 0)

    def test_missing_token_never_reaches_transport(self):
        with self.assertRaisesRegex(RuntimeError, "APIFY_TOKEN is missing"):
            prepare_cli_request([URL], {})
        self.assertEqual(self.transport.post_count, 0)

    def test_valid_explicit_url_is_the_only_input_source(self):
        request = prepare_cli_request([URL], {"APIFY_TOKEN": "synthetic-token", "INSTAGRAM_REEL_URL": "https://example.invalid/"})
        self.assertEqual(request["url"], URL)
        self.assertEqual(self.transport.post_count, 0)

    def test_output_shape_is_stable_for_success_and_failure(self):
        success = format_output({"status": "success", "sourceUrl": URL, "rawItems": [{"timestamp": 0}, {"text": "Synthetic transcript", "segments": [{"text": "Synthetic"}], "timestamp": 1}]})
        failure = format_output({"status": "actor_error", "error": "synthetic error"})
        self.assertEqual(list(success), list(failure))
        self.assertEqual(success["transcript"], "Synthetic transcript")
        self.assertEqual(success["segmentsCount"], 1)
        self.assertEqual(success["items"][0]["timestamp"], 0)
        self.assertIsNone(failure["transcript"])
        self.assertEqual(failure["segmentsCount"], 0)


if __name__ == "__main__":
    unittest.main()
