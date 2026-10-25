"""Run named repository regression tests against isolated Profile guard mutations."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MUTATIONS = (
    ("M1 owner attribution", "elif owner in context.usernames:", "elif True:",
     "tests.python.test_mcp_profile_parse.ProfileAttributionAndIdentityTests.test_owner_mismatch_and_case_only_match_fail_closed"),
    ("M2 independent Dataset ledger echo", "if any(page.dataset_id != expected_dataset_id for page in pages):",
     "if False:",
     "tests.python.test_mcp_profile_parse.ProfileDatasetAndAcceptanceTests.test_profile_ledger_rejects_dataset_echo_mismatch_independently"),
    ("M3 completeness downgrade", 'elif cursor < total:\n        completeness = "INCOMPLETE"',
     'elif cursor < total:\n        completeness = "COMPLETE"',
     "tests.python.test_mcp_profile_parse.ProfileDatasetAndAcceptanceTests.test_incomplete_dataset_and_owner_or_identity_errors_block_pass"),
    ("M4 transcript field state", "text_state = _profile_text_state(item)", 'text_state = "MISSING"',
     "tests.python.test_mcp_profile_parse.ProfileTranscriptAndErrorTests.test_text_states"),
    ("M5 userName owner fallback", 'if "ownerUsername" not in item:\n'
     '        attribution = "CONTEXT_ONLY_UNCONFIRMED" if len(context.usernames) == 1 else "OWNER_UNAVAILABLE"\n'
     '        requested_owner = context.usernames[0] if len(context.usernames) == 1 else None',
     'if "ownerUsername" not in item:\n'
     '        owner = item.get("userName") if isinstance(item.get("userName"), str) else owner\n'
     '        if owner in context.usernames:\n'
     '            attribution, requested_owner = "MATCHED_OWNER", owner\n'
     '        else:\n'
     '            attribution = "CONTEXT_ONLY_UNCONFIRMED" if len(context.usernames) == 1 else "OWNER_UNAVAILABLE"\n'
     '            requested_owner = context.usernames[0] if len(context.usernames) == 1 else None',
     "tests.python.test_mcp_profile_parse.ProfileAttributionAndIdentityTests.test_username_is_never_owner_fallback_and_author_field_conflict_is_separate"),
    ("M6 requested-account strict gate", "and bool(results) and every_requested_account_seen and all_items_matched",
     "and bool(results) and all_items_matched",
     "tests.python.test_mcp_profile_parse.ProfileDatasetAndAcceptanceTests.test_missing_requested_account_has_aggregate_status_and_blocker"),
    ("M7 unique-post strict gate", 'and all(item.duplicate_status == "UNIQUE" for item in results)', "and True",
     "tests.python.test_mcp_profile_parse.ProfileDatasetAndAcceptanceTests.test_repeated_stable_key_is_duplicate_within_owner_only"),
    ("M8 author-conflict strict gate", "and author_conflict_count == 0", "and True",
     "tests.python.test_mcp_profile_parse.ProfileDatasetAndAcceptanceTests.test_author_field_conflict_blocks_aggregate_pass_with_named_status"),
    ("M9 all-items strict gate", "and bool(results) and every_requested_account_seen and all_items_matched",
     "and bool(results) and every_requested_account_seen",
     "tests.python.test_mcp_profile_parse.ProfileDatasetAndAcceptanceTests.test_aggregate_business_error_blocks_pass_for_identified_post"),
    ("M10 business-error guard", "if business_error is not None:", "if False:",
     "tests.python.test_mcp_profile_parse.ProfileTranscriptAndErrorTests.test_shared_business_error_keys_and_conflicting_sources_are_preserved"),
    ("M11 contiguous-page guard", "if page.offset != cursor:", "if False:",
     "tests.python.test_mcp_profile_parse.ProfileDatasetAndAcceptanceTests.test_page_gap_duplicate_offset_count_and_dataset_mismatch_fail_closed"),
    ("M12 null segment count", 'return "NULL", None', 'return "NULL", 0',
     "tests.python.test_mcp_profile_parse.ProfileTranscriptAndErrorTests.test_segment_states_count_and_null_are_distinct"),
    ("M13 whitespace alternate error", 'elif isinstance(value, str) and not value.strip():\n                state = "WHITESPACE_ONLY"',
     'elif isinstance(value, str) and not value.strip():\n                state = "NONEMPTY"\n                sources.append(key)\n                messages.append(scrub(value))',
     "tests.python.test_mcp_profile_parse.ProfileTranscriptAndErrorTests.test_whitespace_alternate_error_is_not_business_error_and_unsupported_type_is_visible"),
    ("M14 author-conflict observation", "author_conflict = bool(owner and author and owner != author)",
     "author_conflict = False",
     "tests.python.test_mcp_profile_parse.ProfileDatasetAndAcceptanceTests.test_author_field_conflict_blocks_aggregate_pass_with_named_status"),
    ("M15 parsed itemCount consistency", "if item_count is not None and item_count != len(items):", "if False:",
     "tests.python.test_mcp_parse_p2.RunAndDatasetBindingTests.test_p2f4_dataset_item_count_mismatch"),
    ("M16 owner field consumption", "owner = owner_value if owner_field_state == \"PRESENT\" else None", "owner = None",
     "tests.python.test_mcp_profile_parse.ProfileAttributionAndIdentityTests.test_single_owner_match_does_not_require_reel_page_url"),
)


def make_isolated_tree(root: Path) -> Path:
    shutil.copytree(ROOT / "tools", root / "tools", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(ROOT / "tests", root / "tests", ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", "test_mcp_profile_mutations.py"))
    return root / "tools" / "mcp_parse.py"


class ProfileGuardMutationTests(unittest.TestCase):
    def test_named_repository_regressions_kill_guard_mutations(self):
        for name, old, new, test_name in MUTATIONS:
            with self.subTest(mutation=name), tempfile.TemporaryDirectory(prefix="profile-mutation-") as temp:
                isolated_root = Path(temp)
                parser_path = make_isolated_tree(isolated_root)
                source = parser_path.read_text()
                self.assertEqual(source.count(old), 1, f"mutation anchor changed for {name}")
                parser_path.write_text(source.replace(old, new, 1))
                result = subprocess.run(
                    [sys.executable, "-m", "unittest", test_name], cwd=isolated_root,
                    env={**os.environ, "PYTHONPATH": str(isolated_root)},
                    text=True, capture_output=True, check=False,
                )
                self.assertNotEqual(result.returncode, 0, f"mutation survived: {name}")
                self.assertIn(test_name.rsplit(".", 1)[-1], result.stderr,
                              f"failure did not come from the named committed regression: {name}\n{result.stderr}")


if __name__ == "__main__":
    unittest.main()
