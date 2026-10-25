"""Offline-only Profile parser acceptance tests using synthetic safe sentinels."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import mcp_parse

FIXTURE = json.loads((ROOT / "tests/fixtures/dx2-profile-synthetic.json").read_text())
DATASET_ID = "synthetic-profile-dataset-001"
RUN_ID = "synthetic-profile-run-001"


def run_meta(payload=None, *, status="SUCCEEDED", dataset_id=DATASET_ID, count=None):
    if payload is None:
        payload = {"structuredContent": {
            "runId": RUN_ID, "status": status,
            "storages": {"datasets": {"default": {"id": dataset_id, "itemCount": count}}},
        }}
    return mcp_parse.run_metadata(payload, expected_run_id=RUN_ID)


def page_payload(items, *, offset=0, total=None, dataset_id=DATASET_ID, is_error=False):
    structured = {"datasetId": dataset_id, "itemCount": len(items), "offset": offset,
                  "limit": 2, "items": items}
    if total is not None:
        structured["totalItemCount"] = total
    return {"structuredContent": structured, **({"isError": True} if is_error else {})}


def page(items, *, offset=0, total=None, dataset_id=DATASET_ID):
    return mcp_parse.dataset_items(page_payload(items, offset=offset, total=total, dataset_id=dataset_id),
                                   expected_dataset_id=DATASET_ID, allow_incomplete=True,
                                   allow_unknown_items=True)


def post(owner="creator", **extra):
    return {"ownerUsername": owner, "type": "Video", "code": "post001", **extra}


class ProfileInputTests(unittest.TestCase):
    def test_valid_input_preserves_raw_and_comparison_values(self):
        got = mcp_parse.validate_profile_input(["Creator.One"], results_limit=1, skip_pinned_posts=False)
        self.assertEqual(got.usernames, ("Creator.One",))
        self.assertEqual(got.normalized_usernames, ("creator.one",))
        self.assertEqual(got.to_dict()["skipPinnedPosts"], False)

    def test_invalid_username_shapes_duplicates_and_case_ambiguity_reject(self):
        for names in (None, "creator", [], [""], [" creator"], ["@creator"], ["one", "one"], ["Alpha", "alpha"]):
            with self.subTest(names=names), self.assertRaises(mcp_parse.MCPParseError):
                mcp_parse.validate_profile_input(names)

    def test_optional_parameters_validate_types_without_boolean_integer_coercion(self):
        for value in (0, -1, True, 1.0, "1"):
            with self.subTest(value=value), self.assertRaises(mcp_parse.MCPParseError):
                mcp_parse.validate_profile_input(["creator"], results_limit=value)
        for value in (0, 1, "false"):
            with self.subTest(value=value), self.assertRaises(mcp_parse.MCPParseError):
                mcp_parse.validate_profile_input(["creator"], skip_pinned_posts=value)
        absent = mcp_parse.validate_profile_input(["creator"])
        self.assertIsNone(absent.results_limit)
        self.assertIsNone(absent.skip_pinned_posts)


class ProfileAttributionAndIdentityTests(unittest.TestCase):
    def test_single_owner_match_does_not_require_reel_page_url(self):
        result = mcp_parse.profile_item(post("creator"), ["creator"])
        self.assertEqual(result.status, "PROFILE_POST_MATCHED")
        self.assertEqual(result.attribution, "MATCHED_OWNER")
        self.assertEqual(result.post_keys, ("code:post001",))

    def test_single_missing_owner_is_context_only_not_verified(self):
        result = mcp_parse.profile_item({"type": "Image", "caption": "safe"}, ["creator"])
        self.assertEqual(result.attribution, "CONTEXT_ONLY_UNCONFIRMED")
        self.assertNotEqual(result.status, "PROFILE_POST_MATCHED")

    def test_shuffled_multi_account_items_map_by_owner_not_order(self):
        results = [mcp_parse.profile_item(post("two", code="twoPost"), ["one", "two"]),
                   mcp_parse.profile_item(post("one", code="onePost"), ["one", "two"])]
        self.assertEqual([result.requested_owner for result in results], ["two", "one"])
        missing = mcp_parse.profile_item({"userName": "one", "type": "Image"}, ["one", "two"])
        self.assertEqual(missing.attribution, "OWNER_UNAVAILABLE")

    def test_username_is_never_owner_fallback_and_author_conflict_is_separate(self):
        missing = mcp_parse.profile_item({"userName": "creator", "type": "Video"}, ["creator"])
        self.assertEqual(missing.attribution, "CONTEXT_ONLY_UNCONFIRMED")
        self.assertIsNone(missing.owner_username)
        conflict = mcp_parse.profile_item(post("creator", userName="other"), ["creator"])
        self.assertEqual(conflict.status, "PROFILE_POST_MATCHED")
        self.assertTrue(conflict.author_field_conflict)

    def test_owner_mismatch_and_case_only_match_fail_closed(self):
        self.assertEqual(mcp_parse.profile_item(post("other"), ["creator"]).status, "OWNER_MISMATCH")
        self.assertEqual(mcp_parse.profile_item(post("CREATOR"), ["creator"]).status, "OWNER_AMBIGUOUS")
        self.assertEqual(mcp_parse.profile_item({"ownerUsername": 3, "type": "Video"}, ["creator"]).status,
                         "OWNER_AMBIGUOUS")

    def test_post_url_and_code_corroborate_or_conflict(self):
        good = mcp_parse.profile_item(post("creator", url="https://www.instagram.com/p/post001/"), ["creator"])
        bad = mcp_parse.profile_item(post("creator", url="https://www.instagram.com/reel/other/"), ["creator"])
        self.assertEqual(good.post_identity, "IDENTIFIED")
        self.assertEqual(bad.status, "POST_IDENTITY_CONFLICT")

    def test_profile_url_and_cdn_media_are_not_post_identity(self):
        profile_url = mcp_parse.profile_item({"ownerUsername": "creator", "url": "https://www.instagram.com/creator/"}, ["creator"])
        cdn = mcp_parse.profile_item({"ownerUsername": "creator", "type": "Video",
                                      "videoUrl": "https://cdn.invalid/private"}, ["creator"])
        self.assertEqual(profile_url.post_identity, "PROFILE_PAGE_URL_ONLY")
        self.assertEqual(profile_url.status, "UNKNOWN_SHAPE")
        self.assertEqual(cdn.post_identity, "UNAVAILABLE")
        self.assertEqual(cdn.post_keys, ())

    def test_pk_and_id_are_separate_namespaced_keys(self):
        result = mcp_parse.profile_item({"ownerUsername": "creator", "type": "Carousel",
                                         "pk": "large-pk", "id": "other-id"}, ["creator"])
        self.assertEqual(result.post_keys, ("pk:large-pk", "id:other-id"))

    def test_integer_pk_id_and_large_ids_are_preserved_without_float_conversion(self):
        large = 10**40 + 123
        cases = [({"pk": 123456}, ("pk:123456",)),
                 ({"id": 987654}, ("id:987654",)),
                 ({"pk": large}, (f"pk:{large}",)),
                 ({"pk": True, "id": False}, ())]
        for extra, expected in cases:
            with self.subTest(extra=extra):
                result = mcp_parse.profile_item({"ownerUsername": "creator", "type": "Video", **extra},
                                                ["creator"])
                self.assertEqual(result.post_keys, expected)
        numeric = mcp_parse.profile_item({"ownerUsername": "creator", "type": "Video", "pk": 123},
                                         ["creator"])
        string = mcp_parse.profile_item({"ownerUsername": "creator", "type": "Video", "pk": "123"},
                                       ["creator"])
        duplicate = mcp_parse._profile_duplicate_states([numeric, string])
        self.assertEqual([item.duplicate_status for item in duplicate], ["DUPLICATE", "DUPLICATE"])
        other_account = mcp_parse.profile_item({"ownerUsername": "other", "type": "Video", "pk": 123},
                                               ["creator", "other"])
        self.assertEqual(mcp_parse._profile_duplicate_states([numeric, other_account])[1].duplicate_status,
                         "UNIQUE")

    def test_duplicate_detection_is_scoped_by_owner_and_unknown_without_keys(self):
        same_owner = [mcp_parse.profile_item(post("one"), ["one", "two"]),
                      mcp_parse.profile_item(post("one"), ["one", "two"])]
        updated = mcp_parse._profile_duplicate_states(same_owner)
        self.assertEqual([item.duplicate_status for item in updated], ["DUPLICATE", "DUPLICATE"])
        cross_owner = [mcp_parse.profile_item(post("one"), ["one", "two"]),
                       mcp_parse.profile_item(post("two"), ["one", "two"])]
        self.assertEqual([item.duplicate_status for item in mcp_parse._profile_duplicate_states(cross_owner)],
                         ["UNIQUE", "UNIQUE"])
        no_key = mcp_parse.profile_item({"ownerUsername": "one", "type": "Video", "caption": "similar"}, ["one"])
        self.assertEqual(no_key.duplicate_status, "NOT_VERIFIABLE")

    def test_unknown_shapes_are_not_dropped(self):
        result = mcp_parse.profile_item({"futureField": {"safe": True}}, ["creator"])
        self.assertEqual(result.status, "UNKNOWN_SHAPE")
        self.assertEqual(result.item_keys, ("futureField",))

    def test_image_video_carousel_and_unknown_types_are_preserved(self):
        for kind in ("Image", "Video", "Carousel", "future-type"):
            with self.subTest(kind=kind):
                result = mcp_parse.profile_item({"ownerUsername": "creator", "type": kind,
                                                 "code": "safe-post-key"}, ["creator"])
                self.assertEqual(result.status, "PROFILE_POST_MATCHED")


class ProfileTranscriptAndErrorTests(unittest.TestCase):
    def test_text_states(self):
        cases = [({}, "MISSING"), ({"text": None}, "NULL"), ({"text": ""}, "EMPTY"),
                 ({"text": "  "}, "WHITESPACE_ONLY"), ({"text": "synthetic"}, "NONEMPTY_STRING"),
                 ({"text": 7}, "UNSUPPORTED_TYPE")]
        for item, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(mcp_parse.profile_item({"ownerUsername": "creator", "type": "Video", **item},
                                                        ["creator"]).text_state, expected)

    def test_segment_states_count_and_null_are_distinct(self):
        cases = [({}, "MISSING", None), ({"segments": None}, "NULL", None),
                 ({"segments": []}, "EMPTY_ARRAY", 0), ({"segments": [{"x": 1}]}, "NONEMPTY_ARRAY", 1),
                 ({"segments": "bad"}, "UNSUPPORTED_TYPE", None)]
        for item, state, count in cases:
            with self.subTest(state=state):
                result = mcp_parse.profile_item({"ownerUsername": "creator", "type": "Video", **item}, ["creator"])
                self.assertEqual((result.segments_state, result.segments_count), (state, count))

    def test_error_states_whitespace_empty_and_nonempty(self):
        cases = [({}, "MISSING", False, None), ({"errMsg": ""}, "EMPTY", False, None),
                 ({"errMsg": "  "}, "EMPTY", True, None),
                 ({"errMsg": "synthetic failure"}, "NONEMPTY", False, "errMsg: synthetic failure"),
                 ({"errMsg": 2}, "UNSUPPORTED_TYPE", False, None)]
        for item, state, whitespace, error in cases:
            with self.subTest(state=state, whitespace=whitespace):
                result = mcp_parse.profile_item({"ownerUsername": "creator", "type": "Video", **item}, ["creator"])
                self.assertEqual((result.err_msg_state, result.err_msg_whitespace_only, result.business_error),
                                 (state, whitespace, error))

    def test_null_empty_whitespace_and_nonempty_errmsg_have_distinct_detail_states(self):
        cases = [({"errMsg": None}, "NULL"), ({"errMsg": ""}, "EMPTY"),
                 ({"errMsg": "  "}, "WHITESPACE_ONLY"), ({"errMsg": "boom"}, "NONEMPTY")]
        for extra, detail in cases:
            with self.subTest(detail=detail):
                row = mcp_parse.profile_item({"ownerUsername": "creator", "type": "Video", **extra}, ["creator"])
                self.assertEqual(row.err_msg_state_detail, detail)

    def test_shared_business_error_keys_and_conflicting_sources_are_preserved(self):
        cases = [({"errMsg": "one"}, ("errMsg",)), ({"error": "two"}, ("error",)),
                 ({"errorMessage": "three"}, ("errorMessage",))]
        for extra, sources in cases:
            with self.subTest(sources=sources):
                row = mcp_parse.profile_item({"ownerUsername": "creator", "type": "Video",
                                              "code": "post", **extra}, ["creator"])
                self.assertEqual(row.status, "ACTOR_ITEM_ERROR")
                self.assertEqual(row.business_error_sources, sources)
        conflict = mcp_parse.profile_item({"ownerUsername": "creator", "type": "Video", "code": "post",
                                           "errMsg": "first", "error": "second",
                                           "errorMessage": "second"}, ["creator"])
        self.assertEqual(conflict.business_error_sources, ("errMsg", "error", "errorMessage"))
        self.assertEqual(conflict.business_error_messages, ("first", "second", "second"))
        self.assertTrue(conflict.business_error_conflict)
        self.assertIn("errMsg", conflict.business_error)
        self.assertIn("errorMessage", conflict.business_error)
        self.assertLessEqual(len(conflict.business_error), 300)

    def test_whitespace_alternate_error_is_not_business_error_and_unsupported_type_is_visible(self):
        whitespace = mcp_parse.profile_item({"ownerUsername": "creator", "type": "Video", "error": " \t"},
                                           ["creator"])
        unsupported = mcp_parse.profile_item({"ownerUsername": "creator", "type": "Video", "error": 3},
                                             ["creator"])
        self.assertIsNone(whitespace.business_error)
        self.assertEqual(whitespace.status, "PROFILE_POST_MATCHED")
        self.assertEqual(dict(whitespace.business_error_field_states)["error"], "WHITESPACE_ONLY")
        self.assertEqual(unsupported.status, "UNKNOWN_SHAPE")

    def test_transcript_state_is_independent_and_never_retains_body(self):
        row = mcp_parse.profile_item(post("creator", text="SYNTHETIC_PRIVATE_BODY",
                                          segments=[{"text": "SYNTHETIC_SEGMENT_BODY"}]), ["creator"])
        data = row.to_dict()
        self.assertEqual(row.transcript_assessment, "NOT_EXPECTED_PROFILE_MODE")
        self.assertEqual(row.transcript_data_state, "PRESENT")
        self.assertEqual(row.segments_count, 1)
        self.assertNotIn("SYNTHETIC_PRIVATE_BODY", repr(data))
        self.assertNotIn("SYNTHETIC_SEGMENT_BODY", repr(data))

    def test_business_error_wins_even_when_transcript_is_present(self):
        row = mcp_parse.profile_item(post("creator", text="synthetic", segments=[{}], errMsg="synthetic error"),
                                     ["creator"])
        self.assertEqual(row.status, "ACTOR_ITEM_ERROR")
        self.assertEqual(row.transcript_data_state, "PRESENT")


class ProfileDatasetAndAcceptanceTests(unittest.TestCase):
    def test_fixture_replay_has_metadata_pass_and_keeps_transcript_signals_only(self):
        run = mcp_parse.run_metadata(FIXTURE["run"], expected_run_id=RUN_ID)
        dataset = mcp_parse.dataset_items(FIXTURE["dataset"], expected_dataset_id=DATASET_ID,
                                          allow_incomplete=True)
        accepted = mcp_parse.profile_acceptance(run, [dataset], FIXTURE["input"]["usernames"],
                                                results_limit=1, skip_pinned_posts=False)
        self.assertEqual((accepted["functionalVerdict"], accepted["verdict"]), ("PASS", "PASS"))
        self.assertEqual(accepted["datasetCompleteness"], "COMPLETE")
        row = accepted["items"][0]
        self.assertEqual((row["status"], row["text_state"], row["segments_state"], row["segments_count"]),
                         ("PROFILE_POST_MATCHED", "NONEMPTY_STRING", "NONEMPTY_ARRAY", 1))
        rendered = json.dumps(accepted)
        self.assertNotIn("SYNTHETIC_CAPTION_DO_NOT_OUTPUT", rendered)
        self.assertNotIn("SYNTHETIC_TRANSCRIPT_DO_NOT_OUTPUT", rendered)
        self.assertNotIn("SYNTHETIC_SEGMENT_DO_NOT_OUTPUT", rendered)
        self.assertEqual(accepted["accountContentCoverage"], "UNVERIFIED")
        self.assertEqual(accepted["statusScope"], "AGGREGATE")
        self.assertEqual(accepted["datasetSource"], "MCP")
        self.assertEqual(accepted["itemsSource"], "structuredContent.items")
        self.assertEqual(accepted["datasetIdPath"], "storages.datasets.default.id")
        self.assertEqual((accepted["itemCount"], accepted["totalItemCount"], accepted["parsedItemCount"]),
                         (1, 1, 1))

    def test_missing_requested_account_has_aggregate_status_and_blocker(self):
        result = mcp_parse.profile_acceptance(
            run_meta(count=1), [page([post("one", code="one")], total=1)], ["one", "two"])
        self.assertFalse(result["allRequestedAccountsSeen"])
        self.assertEqual(result["requestedAccountsWithoutPost"], ["two"])
        self.assertEqual(result["status"], "REQUESTED_ACCOUNT_WITHOUT_POST")
        self.assertIn("REQUESTED_ACCOUNT_WITHOUT_POST", result["blockingReasons"])
        self.assertEqual(result["functionalVerdict"], "PARTIAL")
        self.assertNotEqual(result["status"], "PROFILE_POST_MATCHED")

    def test_author_field_conflict_blocks_aggregate_pass_with_named_status(self):
        result = mcp_parse.profile_acceptance(
            run_meta(count=1), [page([post("one", code="one", userName="another")], total=1)], ["one"])
        self.assertTrue(result["items"][0]["author_field_conflict"])
        self.assertEqual(result["items"][0]["status"], "PROFILE_POST_MATCHED")
        self.assertEqual(result["status"], "AUTHOR_FIELD_CONFLICT")
        self.assertIn("AUTHOR_FIELD_CONFLICT", result["blockingReasons"])
        self.assertEqual(result["functionalVerdict"], "PARTIAL")
        self.assertEqual(result["statusScope"], "AGGREGATE")
        self.assertNotEqual(result["status"], "PROFILE_POST_MATCHED")

    def test_aggregate_business_error_blocks_pass_for_identified_post(self):
        result = mcp_parse.profile_acceptance(
            run_meta(count=3), [page([post("one", code="one"), post("two", code="two"),
                                    post("two", code="two-error", errMsg="synthetic failure")], total=3)], ["one", "two"])
        self.assertTrue(all(item["duplicate_status"] == "UNIQUE" for item in result["items"]))
        self.assertEqual(result["status"], "ACTOR_ITEM_ERROR")
        self.assertEqual(result["functionalVerdict"], "PARTIAL")
        self.assertIn("ACTOR_ITEM_ERROR", result["blockingReasons"])

    def test_context_only_lovepegz_result_is_self_describing_and_not_owner_pass(self):
        item = {"type": "Video", "code": "syntheticLovepegzPost", "userName": "lovepegz"}
        result = mcp_parse.profile_acceptance(run_meta(count=1),
            [page([item], total=1)], ["lovepegz"], results_limit=1)
        self.assertEqual(result["items"][0]["attribution"], "CONTEXT_ONLY_UNCONFIRMED")
        self.assertEqual(result["status"], "CONTEXT_ONLY_UNCONFIRMED")
        self.assertEqual(result["functionalVerdict"], "PARTIAL")
        self.assertEqual(result["ownerFieldAbsentCount"], 1)
        self.assertFalse(result["allRequestedAccountsSeen"])
        self.assertEqual(result["matchedAccounts"], [])
        self.assertEqual(result["ownerPresenceByAccount"], [{
            "requestedUsername": "lovepegz", "recordCount": 1, "ownerFieldPresentCount": 0,
            "ownerFieldAbsentCount": 1, "ownerFieldTypeErrorCount": 0, "ownerFieldEmptyCount": 0,
            "ownerMismatchCount": 0, "ownerAmbiguousCount": 0,
            "trustedOwnerMatchCount": 0, "contextOnlyCount": 1,
        }])
        self.assertIn("CONTEXT_ONLY_UNCONFIRMED", result["blockingReasons"])

    def test_owner_absence_type_error_and_foreign_owner_are_counted_separately(self):
        items = [post("one", code="one"), {"type": "Video", "code": "missing"},
                 {"ownerUsername": 7, "type": "Video", "code": "invalid"},
                 post("foreign", code="foreign")]
        result = mcp_parse.profile_acceptance(run_meta(count=4), [page(items, total=4)], ["one"])
        self.assertEqual(result["ownerFieldPresentCount"], 2)
        self.assertEqual(result["ownerFieldAbsentCount"], 1)
        self.assertEqual(result["ownerFieldTypeErrorCount"], 1)
        self.assertEqual(result["ownerMismatchCount"], 1)
        self.assertEqual(result["ownerAmbiguousCount"], 1)
        self.assertEqual(result["contextOnlyUnconfirmedCount"], 1)
        self.assertEqual(result["status"], "OWNER_MISMATCH")

    def test_multiple_blocking_reasons_keep_business_error_and_completeness(self):
        result = mcp_parse.profile_acceptance(run_meta(count=2),
            [page([post("one", code="one", error="synthetic boom")], total=2)], ["one", "two"])
        self.assertEqual(result["status"], "ACTOR_ITEM_ERROR")
        self.assertIn("ACTOR_ITEM_ERROR", result["blockingReasons"])
        self.assertIn("INCOMPLETE", result["blockingReasons"])
        self.assertEqual(result["datasetCompleteness"], "INCOMPLETE")
        self.assertEqual(result["functionalVerdict"], "PARTIAL")

    def test_complete_empty_dataset_is_empty_not_transcript_failure(self):
        accepted = mcp_parse.profile_acceptance(run_meta(), [page([], total=0)], ["creator"])
        self.assertEqual(accepted["status"], "EMPTY_PROFILE_RESULT")
        self.assertEqual(accepted["functionalVerdict"], "PARTIAL")
        self.assertFalse(accepted["transcriptRequired"])

    def test_missing_total_makes_completeness_unknown_not_empty_or_pass(self):
        accepted = mcp_parse.profile_acceptance(run_meta(), [page([], total=None)], ["creator"])
        self.assertEqual(accepted["datasetCompleteness"], "COMPLETENESS_UNKNOWN")
        self.assertEqual(accepted["status"], "COMPLETENESS_UNKNOWN")
        self.assertEqual(accepted["functionalVerdict"], "COMPLETENESS_UNKNOWN")

    def test_multi_page_ledger_proves_contiguous_dataset_page_coverage(self):
        first = page([post("creator", code="one")], offset=0, total=2)
        second = page([post("creator", code="two")], offset=1, total=2)
        ledger = mcp_parse.profile_page_ledger([second, first], expected_dataset_id=DATASET_ID)
        self.assertEqual(ledger.completeness, "COMPLETE")
        self.assertEqual([item["code"] for item in ledger.items], ["one", "two"])

    def test_page_gap_duplicate_offset_count_and_dataset_mismatch_fail_closed(self):
        gap = mcp_parse.profile_page_ledger([page([post(code="two")], offset=1, total=2)],
                                            expected_dataset_id=DATASET_ID)
        self.assertEqual(gap.completeness, "INCOMPLETE")
        with self.assertRaises(mcp_parse.MCPParseError):
            mcp_parse.profile_page_ledger([page([], total=0), page([], total=0)], expected_dataset_id=DATASET_ID)
        with self.assertRaises(mcp_parse.MCPParseError):
            mcp_parse.profile_page_ledger([page([], total=0, dataset_id="other-dataset")], expected_dataset_id=DATASET_ID)
        with self.assertRaises(mcp_parse.MCPParseError):
            mcp_parse.dataset_items(page_payload([post()], total=2), expected_dataset_id=DATASET_ID)

    def test_profile_ledger_rejects_dataset_echo_mismatch_independently(self):
        wrong_echo_page = mcp_parse.DatasetPage("different-dataset", ({"ownerUsername": "creator",
            "type": "Video", "code": "one"},), 1, 1, 0, 10, "structuredContent.items", True,
            ("structuredContent",))
        with self.assertRaises(mcp_parse.MCPParseError) as caught:
            mcp_parse.profile_acceptance(run_meta(count=1), [wrong_echo_page], ["creator"])
        self.assertEqual(caught.exception.code, "DATASET_RUN_BINDING_MISMATCH")

    def test_incomplete_dataset_and_owner_or_identity_errors_block_pass(self):
        incomplete = mcp_parse.profile_acceptance(run_meta(), [page([post()], total=2)], ["creator"])
        self.assertEqual(incomplete["datasetCompleteness"], "INCOMPLETE")
        self.assertEqual(incomplete["status"], "INCOMPLETE")
        self.assertEqual(incomplete["functionalVerdict"], "PARTIAL")
        for item, expected in ((post("other"), "OWNER_MISMATCH"),
                               (post("creator", url="https://www.instagram.com/p/other/"), "POST_IDENTITY_CONFLICT"),
                               ({"ownerUsername": "creator", "type": "Video"}, "DUPLICATE_CHECK_NOT_VERIFIABLE")):
            result = mcp_parse.profile_acceptance(run_meta(), [page([item], total=1)], ["creator"])
            self.assertEqual(result["status"], expected)
            self.assertNotEqual(result["functionalVerdict"], "PASS")

    def test_repeated_stable_key_is_duplicate_within_owner_only(self):
        items = [post("creator"), post("creator")]
        result = mcp_parse.profile_acceptance(run_meta(count=2), [page(items, total=2)], ["creator"])
        self.assertEqual(result["status"], "DUPLICATE_PROFILE_POST")
        self.assertTrue(all(item["duplicate_status"] == "DUPLICATE" for item in result["items"]))

    def test_failed_run_is_distinct_and_missing_or_nonterminal_run_rejected(self):
        failed = mcp_parse.profile_acceptance(run_meta(status="FAILED"), [], ["creator"])
        self.assertEqual(failed["status"], "RUN_FAILED")
        with self.assertRaises(mcp_parse.MCPParseError):
            mcp_parse.profile_acceptance(run_meta(status="RUNNING"), [], ["creator"])
        with self.assertRaises(mcp_parse.MCPParseError):
            mcp_parse.profile_acceptance(run_meta({"structuredContent": {"status": "SUCCEEDED",
                "storages": {"datasets": {"default": {"id": DATASET_ID}}}}}), [], ["creator"])

    def test_results_limit_scope_not_interpreted_for_multiple_accounts(self):
        accepted = mcp_parse.profile_acceptance(run_meta(count=2),
            [page([post("one", code="one"), post("two", code="two")], total=2)],
            ["one", "two"], results_limit=1)
        self.assertEqual(accepted["functionalVerdict"], "PASS")
        self.assertEqual(accepted["resultsLimit"], 1)
        self.assertEqual(accepted["accountContentCoverage"], "UNVERIFIED")

    def test_dataset_envelope_mcp_error_malformed_and_content_json(self):
        with self.assertRaises(mcp_parse.MCPParseError) as caught:
            mcp_parse.dataset_items(page_payload([], total=0, is_error=True), expected_dataset_id=DATASET_ID,
                                    allow_incomplete=True)
        self.assertEqual(caught.exception.code, "MCP_TOOL_ERROR")
        with self.assertRaises(mcp_parse.MCPParseError) as caught:
            mcp_parse.dataset_items({"structuredContent": {"items": "bad"}}, expected_dataset_id=DATASET_ID)
        self.assertEqual(caught.exception.code, "ITEMS_NOT_FOUND")
        content_only = {"content": [{"type": "text", "text": json.dumps({"datasetId": DATASET_ID,
            "itemCount": 1, "totalItemCount": 1, "offset": 0, "items": [post()]})}]}
        parsed = mcp_parse.dataset_items(content_only, expected_dataset_id=DATASET_ID, allow_incomplete=True)
        self.assertEqual(parsed.items_source, "content[0].text.items")
        self.assertEqual(len(parsed.items), 1)

    def test_explicit_items_array_preserves_unrecognized_profile_shapes(self):
        payload = {"structuredContent": {"datasetId": DATASET_ID, "itemCount": 1,
            "totalItemCount": 1, "offset": 0, "items": [{"futureProfileEnvelope": "safe"}]}}
        parsed = mcp_parse.dataset_items(payload, expected_dataset_id=DATASET_ID, allow_incomplete=True,
                                         allow_unknown_items=True)
        self.assertEqual(parsed.items, ({"futureProfileEnvelope": "safe"},))
        accepted = mcp_parse.profile_acceptance(run_meta(count=1), [parsed], ["creator"])
        self.assertEqual(accepted["status"], "UNKNOWN_SHAPE")
        self.assertEqual(accepted["functionalVerdict"], "PARTIAL")


if __name__ == "__main__":
    unittest.main()
