use super::*;
use crate::journal::Journal;
use crate::transport::{Clock, Request, Response, Transport, TransportError, TransportErrorKind};
use std::{
    collections::VecDeque,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

fn urls(values: &[&str]) -> Vec<String> {
    values.iter().map(|s| (*s).to_owned()).collect()
}
fn result_for(input: &[&str], items: Vec<Value>, complete: bool) -> BulkResult {
    let plan = plan_bulk(&urls(input)).unwrap();
    attribute_bulk(&plan, &items, complete)
}
fn usable(url: &str, text: &str) -> Value {
    json!({"url":url,"shortCode":url.trim_end_matches('/').rsplit('/').next().unwrap(),"text":text})
}
fn assert_counts(result: &BulkResult, expected: (usize, usize, usize, usize, usize)) {
    assert_eq!(
        (
            result.counts.success,
            result.counts.empty,
            result.counts.unknown,
            result.counts.error,
            result.counts.extra_items
        ),
        expected,
        "fixture counts must match emitted rows and physical extras"
    );
}

#[test]
fn planning_deduplicates_typed_identities_and_preserves_every_source_occurrence() {
    let plan = plan_bulk(&urls(&[
        "https://www.instagram.com/reel/AbC/",
        "https://instagram.com/reels/AbC",
        "https://instagram.com/p/AbC",
        "https://instagram.com/reel/abc",
        "https://www.instagram.com/reel/AbC/",
    ]))
    .unwrap();
    assert_eq!(plan.tasks.len(), 3);
    assert_eq!(plan.tasks[0].source_indexes, [0, 1, 4]);
    assert_eq!(plan.tasks[0].source_urls.len(), 3);
    assert_eq!(plan.tasks[0].identity.media_type, MediaType::Reel);
    assert_eq!(plan.tasks[1].identity.media_type, MediaType::Post);
    assert_eq!(plan.tasks[2].identity.shortcode, "abc");
    assert_eq!(plan.actor_urls.len(), 3);
}

#[test]
fn invalid_bulk_input_is_rejected_before_any_transport_request() {
    for bad in [
        "https://instagram.com/reel/A?x=1",
        "http://instagram.com/reel/A",
        "https://evil.example/reel/A",
    ] {
        assert!(plan_bulk(&urls(&["https://instagram.com/reel/OK", bad])).is_err());
    }
    assert!(plan_bulk(&[]).is_err());
}

#[test]
fn typed_fallback_requires_item_media_type_and_validates_the_unique_pair() {
    let ok = result_for(
        &["https://instagram.com/reel/ABC"],
        vec![json!({"mediaType":"reel","shortCode":"ABC","text":"fallback"})],
        true,
    );
    assert_eq!(ok.results[0].status, TaskStatus::Success);
    assert_eq!(ok.results[0].attribution, Attribution::TypedFallback);
    let shortcode_only = result_for(
        &["https://instagram.com/reel/ABC"],
        vec![json!({"shortCode":"ABC","text":"not enough evidence"})],
        true,
    );
    assert_eq!(shortcode_only.results[0].status, TaskStatus::Unknown);
    let invalid_url = result_for(
        &["https://instagram.com/reel/ABC"],
        vec![json!({"url":7,"mediaType":"reel","shortCode":"ABC","text":"must not fallback"})],
        true,
    );
    assert_eq!(invalid_url.results[0].status, TaskStatus::Unknown);
    assert_eq!(invalid_url.extra_items[0].reason, ExtraReason::InvalidItem);
}

#[test]
fn reel_alias_urls_match_by_typed_identity_in_both_directions() {
    for (input, dataset_url) in [
        (
            "https://instagram.com/reel/ABC",
            "https://instagram.com/reels/ABC",
        ),
        (
            "https://instagram.com/reels/ABC",
            "https://instagram.com/reel/ABC",
        ),
    ] {
        let result = result_for(
            &[input],
            vec![usable(dataset_url, "alias transcript")],
            true,
        );
        assert_eq!(result.results[0].identity.media_type, MediaType::Reel);
        assert_eq!(result.results[0].status, TaskStatus::Success);
        assert_eq!(result.results[0].attribution, Attribution::TypedFallback);
        assert_eq!(result.results[0].raw_items.len(), 1);
        assert_counts(&result, (1, 0, 0, 0, 0));
        assert!(result.extra_items.is_empty());
        assert_eq!(result.status, BatchStatus::Success);
        assert_eq!(result.exit_code(), 0);
    }
}

#[test]
fn two_reel_alias_inputs_dedupe_and_matching_source_is_exact() {
    let result = result_for(
        &[
            "https://instagram.com/reel/ABC",
            "https://instagram.com/reels/ABC",
        ],
        vec![usable("https://instagram.com/reels/ABC", "transcript")],
        true,
    );
    assert_eq!(result.results.len(), 1);
    assert_eq!(result.results[0].source_indexes, [0, 1]);
    assert_eq!(result.results[0].source_urls.len(), 2);
    assert_eq!(result.results[0].identity.media_type, MediaType::Reel);
    assert_eq!(result.results[0].status, TaskStatus::Success);
    assert_eq!(result.results[0].attribution, Attribution::ExactUrl);
    assert_counts(&result, (1, 0, 0, 0, 0));
    assert!(result.extra_items.is_empty());
    assert_eq!(result.status, BatchStatus::Success);
    assert_eq!(result.exit_code(), 0);
}

#[test]
fn shortcode_case_and_post_reel_type_remain_strict() {
    let case = result_for(
        &["https://instagram.com/reel/ABC"],
        vec![usable("https://instagram.com/reel/abc", "wrong case")],
        true,
    );
    assert_eq!(case.results[0].status, TaskStatus::Empty);
    assert_eq!(case.results[0].attribution, Attribution::None);
    assert_counts(&case, (0, 1, 0, 0, 1));
    assert_eq!(case.extra_items[0].reason, ExtraReason::Unmatched);
    assert_eq!(case.status, BatchStatus::PartialSuccess);
    assert_eq!(case.exit_code(), 2);

    let typed = result_for(
        &[
            "https://instagram.com/reel/SAME",
            "https://instagram.com/p/SAME",
        ],
        vec![usable("https://instagram.com/p/SAME", "post only")],
        true,
    );
    assert_eq!(typed.results[0].status, TaskStatus::Empty);
    assert_eq!(typed.results[1].status, TaskStatus::Success);
    assert_eq!(typed.results[1].attribution, Attribution::ExactUrl);
    assert_counts(&typed, (1, 1, 0, 0, 0));
    assert_eq!(typed.status, BatchStatus::Success);
    assert_eq!(typed.exit_code(), 0);
}

#[test]
fn url_and_self_reported_type_conflict_fails_closed() {
    let result = result_for(
        &[
            "https://instagram.com/reel/ABC",
            "https://instagram.com/p/ABC",
        ],
        vec![json!({
            "url":"https://instagram.com/reels/ABC",
            "shortCode":"ABC",
            "mediaType":"post",
            "text":"conflicting type"
        })],
        true,
    );
    assert!(result
        .results
        .iter()
        .all(|row| row.status == TaskStatus::Unknown));
    assert!(result
        .results
        .iter()
        .all(|row| row.attribution == Attribution::ConflictingEvidence));
    assert_eq!(
        result.extra_items[0].reason,
        ExtraReason::ConflictingEvidence
    );
    assert_eq!(result.extra_items[0].affected_task_indexes, [0, 1]);
    assert_counts(&result, (0, 0, 2, 0, 1));
    assert_eq!(result.status, BatchStatus::Unknown);
    assert_eq!(result.exit_code(), 2);
}

#[test]
fn duplicate_typed_fallback_retains_observed_attribution() {
    let item = json!({"mediaType":"reel","shortCode":"ABC","text":"fallback"});
    let result = result_for(
        &["https://instagram.com/reel/ABC"],
        vec![item.clone(), item],
        true,
    );
    assert_eq!(result.results[0].status, TaskStatus::Unknown);
    assert_eq!(result.results[0].attribution, Attribution::TypedFallback);
    assert!(result.results[0].raw_items.is_empty());
    assert!(result
        .extra_items
        .iter()
        .all(|extra| extra.reason == ExtraReason::Duplicate && extra.affected_task_indexes == [0]));
    assert_counts(&result, (0, 0, 1, 0, 2));
    assert_eq!(result.status, BatchStatus::Unknown);
    assert_eq!(result.results[0].status, TaskStatus::Unknown);
    assert_eq!(result.exit_code(), 2);
}

#[test]
fn mixed_duplicate_evidence_prefers_exact_url_attribution() {
    let result = result_for(
        &["https://instagram.com/reel/ABC"],
        vec![
            usable("https://instagram.com/reel/ABC", "exact"),
            usable("https://instagram.com/reels/ABC", "typed fallback"),
        ],
        true,
    );
    assert_eq!(result.results[0].status, TaskStatus::Unknown);
    assert_eq!(result.results[0].attribution, Attribution::ExactUrl);
    assert_eq!(result.results[0].raw_items.len(), 0);
    assert!(result
        .extra_items
        .iter()
        .all(|extra| extra.reason == ExtraReason::Duplicate));
    assert_counts(&result, (0, 0, 1, 0, 2));
    assert_eq!(result.status, BatchStatus::Unknown);
    assert_eq!(result.exit_code(), 2);
}

#[test]
fn typed_fallback_does_not_cross_media_types_with_same_shortcode() {
    let result = result_for(
        &[
            "https://instagram.com/reel/SAME",
            "https://instagram.com/p/SAME",
        ],
        vec![json!({"mediaType":"post","shortCode":"SAME","text":"post only"})],
        true,
    );
    assert_eq!(
        result.results[0].status,
        TaskStatus::Empty,
        "typed fallback crossed media types"
    );
    assert_eq!(
        result.results[1].status,
        TaskStatus::Success,
        "typed fallback crossed media types"
    );
    assert_eq!(result.results[1].attribution, Attribution::TypedFallback);
}

#[test]
fn incomplete_dataset_never_reports_batch_success_or_confirmed_empty() {
    let result = result_for(
        &[
            "https://instagram.com/reel/A",
            "https://instagram.com/reel/B",
        ],
        vec![usable("https://instagram.com/reel/A", "verified")],
        false,
    );
    assert_eq!(result.results[0].status, TaskStatus::Success);
    assert_eq!(result.results[1].status, TaskStatus::Unknown);
    assert_eq!(result.status, BatchStatus::PartialSuccess);
}

#[test]
fn frozen_dataset_fixtures_01_through_06_are_deterministic() {
    let f1 = result_for(
        &[
            "https://instagram.com/reel/ABC",
            "https://instagram.com/reels/ABC",
        ],
        vec![usable("https://instagram.com/reels/ABC", "transcript")],
        true,
    );
    assert_eq!(f1.status, BatchStatus::Success);
    assert_counts(&f1, (1, 0, 0, 0, 0));
    assert_eq!(f1.exit_code(), 0);
    assert_eq!(f1.results[0].source_indexes, [0, 1]);

    let f2 = result_for(
        &[
            "https://instagram.com/p/ABC",
            "https://instagram.com/reel/ABC",
        ],
        vec![json!({"shortCode":"ABC","text":"unsafe position"})],
        true,
    );
    assert_eq!(
        f2.status,
        BatchStatus::Unknown,
        "all shortcode-only ambiguity remains unknown"
    );
    assert_counts(&f2, (0, 0, 2, 0, 1));
    assert_eq!(f2.exit_code(), 2);

    let dup = usable("https://instagram.com/reel/ABC", "a");
    let f3 = result_for(
        &["https://instagram.com/reel/ABC"],
        vec![dup.clone(), dup],
        true,
    );
    assert_eq!(f3.results[0].status, TaskStatus::Unknown);
    assert_eq!(f3.results[0].attribution, Attribution::ExactUrl);
    assert_counts(&f3, (0, 0, 1, 0, 2));
    assert_eq!(f3.status, BatchStatus::Unknown);
    assert_eq!(f3.exit_code(), 2);
    assert!(f3.results[0].raw_items.is_empty());

    let f4 = result_for(
        &[
            "https://instagram.com/reel/A",
            "https://instagram.com/reel/B",
        ],
        vec![
            json!({"url":"https://instagram.com/reel/A","shortCode":"B","mediaType":"reel","text":"conflicted"}),
        ],
        true,
    );
    assert_eq!(f4.status, BatchStatus::Unknown);
    assert_counts(&f4, (0, 0, 2, 0, 1));
    assert_eq!(
        f4.results
            .iter()
            .filter(|r| r.attribution == Attribution::ConflictingEvidence)
            .count(),
        2
    );

    let f5 = result_for(
        &["https://instagram.com/reel/ABC"],
        vec![
            usable("https://instagram.com/reel/ABC", "ok"),
            usable("https://instagram.com/reel/OTHER", "extra"),
        ],
        true,
    );
    assert_eq!(f5.status, BatchStatus::PartialSuccess);
    assert_counts(&f5, (1, 0, 0, 0, 1));

    let f6 = result_for(
        &[
            "https://instagram.com/reel/ABC",
            "https://instagram.com/p/DEF",
        ],
        vec![
            usable("https://instagram.com/reel/ABC", "ok"),
            json!({"shortCode":"DEF","text":"ambiguous"}),
        ],
        true,
    );
    assert_eq!(f6.status, BatchStatus::PartialSuccess);
    assert_counts(&f6, (1, 0, 1, 0, 1));
}

#[test]
fn frozen_dataset_fixtures_07_through_12_are_deterministic_and_conserve_items() {
    let f7 = result_for(&["https://instagram.com/reel/ABC"], vec![], true);
    assert_eq!(f7.status, BatchStatus::Empty);
    assert_counts(&f7, (0, 1, 0, 0, 0));
    assert_eq!(f7.exit_code(), 0);

    let f8 = result_for(
        &["https://instagram.com/reel/ABC"],
        vec![json!({"url":"https://instagram.com/reel/ABC","shortCode":"ABC"})],
        true,
    );
    assert_eq!(f8.results[0].error_code.as_deref(), Some("no_transcript"));
    assert_eq!(f8.status, BatchStatus::Error);
    assert_counts(&f8, (0, 0, 0, 1, 0));
    assert_eq!(f8.exit_code(), 1);

    let f9 = result_for(
        &[
            "https://instagram.com/reel/A",
            "https://instagram.com/reel/B",
        ],
        vec![
            json!({"url":"https://instagram.com/reel/A","shortCode":"A","errMsg":"crawed empty"}),
            json!({"url":"https://instagram.com/reel/B","shortCode":"B","errMsg":"actor failed"}),
        ],
        true,
    );
    assert_eq!(f9.counts.error, 2);
    assert_counts(&f9, (0, 0, 0, 2, 0));
    assert_eq!(f9.results[0].error_code.as_deref(), Some("actor_error"));

    let f10 = result_for(
        &[
            "https://instagram.com/reel/ABC",
            "https://instagram.com/p/DEF",
        ],
        vec![usable("https://instagram.com/reel/ABC", "ok")],
        true,
    );
    assert_eq!(f10.status, BatchStatus::Success);
    assert_counts(&f10, (1, 1, 0, 0, 0));

    let f11 = result_for(
        &["https://instagram.com/reel/ABC"],
        vec![json!({"shortCode":"ABC","mediaType":"post","text":"other type"})],
        true,
    );
    assert_eq!(f11.status, BatchStatus::PartialSuccess);
    assert_counts(&f11, (0, 1, 0, 0, 1));
    assert_eq!(f11.extra_items[0].reason, ExtraReason::Unmatched);

    let f12 = result_for(
        &["https://instagram.com/reel/ABC"],
        vec![
            usable("https://instagram.com/reel/ABC", "ok"),
            json!({"shortCode":"ABC","text":"ambiguous"}),
        ],
        true,
    );
    assert_eq!(f12.status, BatchStatus::Unknown);
    assert_counts(&f12, (0, 0, 1, 0, 2));
    assert!(f12
        .extra_items
        .iter()
        .any(|e| e.reason == ExtraReason::TaskUnresolved));
    let physical_items =
        f12.results.iter().map(|r| r.raw_items.len()).sum::<usize>() + f12.extra_items.len();
    assert_eq!(physical_items, 2);
}

#[derive(Default)]
struct FakeClock;
impl Clock for FakeClock {
    fn now(&self) -> Instant {
        Instant::now()
    }
    fn sleep(&self, _: Duration) {}
}
struct FakeTransport {
    queue: Mutex<VecDeque<std::result::Result<Response, TransportError>>>,
    requests: Mutex<Vec<Request>>,
    events: Arc<Mutex<Vec<&'static str>>>,
}
impl FakeTransport {
    fn new(responses: Vec<Response>) -> Self {
        Self {
            queue: Mutex::new(responses.into_iter().map(Ok).collect()),
            requests: Mutex::new(vec![]),
            events: Arc::new(Mutex::new(vec![])),
        }
    }
    fn requests(&self) -> Vec<Request> {
        self.requests.lock().unwrap().clone()
    }
}
impl Transport for FakeTransport {
    fn send(&self, request: &Request) -> std::result::Result<Response, TransportError> {
        self.requests.lock().unwrap().push(request.clone());
        if request.method == reqwest::Method::POST {
            self.events.lock().unwrap().push("post");
        }
        self.queue
            .lock()
            .unwrap()
            .pop_front()
            .unwrap_or_else(|| Err(TransportError::new(TransportErrorKind::Other)))
    }
    fn guarantees_single_shot_post(&self) -> bool {
        true
    }
}
struct EventJournal {
    events: Arc<Mutex<Vec<&'static str>>>,
}
impl crate::journal::Journal for EventJournal {
    fn append(&self, _: &JournalRecord) -> Result<()> {
        self.events.lock().unwrap().push("journal");
        Ok(())
    }
    fn latest(&self, _: &str) -> Result<Option<JournalRecord>> {
        Ok(None)
    }
}
fn fixture_config(transport: Arc<FakeTransport>) -> Config {
    let journal = Arc::new(EventJournal {
        events: transport.events.clone(),
    });
    Config::builder()
        .token("synthetic-test-token")
        .max_total_charge_usd("0.10")
        .transport(transport)
        .clock(Arc::new(FakeClock))
        .journal(journal.clone())
        .build()
        .unwrap()
}

#[test]
fn native_bulk_executes_one_post_with_unique_typed_inputs_and_journals_first() {
    let transport = Arc::new(FakeTransport::new(vec![
        Response::json(201, json!({"data":{"id":"run-bulk-1"}})),
        Response::json(
            200,
            json!({"data":{"id":"run-bulk-1","status":"SUCCEEDED","defaultDatasetId":"dataset-bulk-1","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}),
        ),
        Response::json(
            200,
            json!([
                {"url":"https://instagram.com/reels/ABC","shortCode":"ABC","text":"reel transcript"},
                {"url":"https://instagram.com/p/ABC","shortCode":"ABC","text":"post transcript"}
            ]),
        ),
    ]));
    let config = fixture_config(transport.clone());
    let inputs = urls(&[
        "https://instagram.com/reel/ABC",
        "https://instagram.com/reels/ABC",
        "https://instagram.com/p/ABC",
    ]);
    let result = execute_bulk(
        &config,
        &inputs,
        BulkOptions {
            results_limit: Some(12),
            skip_pinned_posts: Some(false),
            include_shares_count: Some(false),
        },
    );
    assert_eq!(result.status, BatchStatus::Success);
    assert_eq!(result.run_id.as_deref(), Some("run-bulk-1"));
    let reqs = transport.requests();
    assert_eq!(
        reqs.iter()
            .filter(|r| r.method == reqwest::Method::POST)
            .count(),
        1,
        "Actor receives unique identities once"
    );
    let body = reqs[0].body.as_ref().unwrap();
    assert_eq!(
        body["bulkUrls"].as_array().unwrap().len(),
        2,
        "Actor receives unique identities once"
    );
    assert_eq!(body["bulkUrls"][0], inputs[0]);
    assert_eq!(body["bulkUrls"][1], inputs[2]);
    assert_eq!(body["resultsLimit"], 12);
    assert!(reqs[0].url.contains("maxTotalChargeUsd=0.10"));
    assert!(reqs[0].url.contains("restartOnError=false"));
    assert!(transport.events.lock().unwrap()[0] == "journal");
    assert_eq!(
        transport
            .events
            .lock()
            .unwrap()
            .iter()
            .filter(|v| **v == "post")
            .count(),
        1
    );
    assert_eq!(result.results[0].source_indexes, [0, 1]);
    assert_eq!(
        result.results[0].raw_items.len() + result.results[1].raw_items.len(),
        2
    );
}

#[test]
fn execute_bulk_attributes_reel_alias_from_fake_actor_response() {
    let transport = Arc::new(FakeTransport::new(vec![
        Response::json(201, json!({"data":{"id":"run-alias"}})),
        Response::json(
            200,
            json!({"data":{"id":"run-alias","status":"SUCCEEDED","defaultDatasetId":"dataset-alias","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}),
        ),
        Response::json(
            200,
            json!([{"url":"https://instagram.com/reels/ABC","shortCode":"ABC","text":"verified alias transcript"}]),
        ),
    ]));
    let result = execute_bulk(
        &fixture_config(transport.clone()),
        &urls(&["https://instagram.com/reel/ABC"]),
        BulkOptions::default(),
    );
    assert_eq!(result.run_id.as_deref(), Some("run-alias"));
    assert_eq!(result.dataset_id.as_deref(), Some("dataset-alias"));
    assert_eq!(result.results[0].status, TaskStatus::Success);
    assert_eq!(result.results[0].attribution, Attribution::TypedFallback);
    assert_eq!(
        result.results[0].text.as_deref(),
        Some("verified alias transcript")
    );
    assert_counts(&result, (1, 0, 0, 0, 0));
    assert!(result.extra_items.is_empty());
    assert_eq!(result.status, BatchStatus::Success);
    assert_eq!(result.exit_code(), 0);
    assert_eq!(
        transport
            .requests()
            .iter()
            .filter(|request| request.method == reqwest::Method::POST)
            .count(),
        1,
        "alias attribution must not create another Run"
    );
}

#[test]
fn execute_bulk_url_identity_never_crosses_post_and_reel_media_types() {
    for (input, dataset_url, run_id, dataset_id) in [
        (
            "https://www.instagram.com/p/ABC/",
            "https://www.instagram.com/reel/ABC/",
            "run-post-input",
            "dataset-post-input",
        ),
        (
            "https://www.instagram.com/reel/ABC/",
            "https://www.instagram.com/p/ABC/",
            "run-reel-input",
            "dataset-reel-input",
        ),
    ] {
        let transport = Arc::new(FakeTransport::new(vec![
            Response::json(201, json!({"data":{"id":run_id}})),
            Response::json(
                200,
                json!({"data":{"id":run_id,"status":"SUCCEEDED","defaultDatasetId":dataset_id,"buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}),
            ),
            Response::json(200, json!([usable(dataset_url, "must not be trusted")])),
        ]));
        let result = execute_bulk(
            &fixture_config(transport.clone()),
            &urls(&[input]),
            BulkOptions::default(),
        );

        assert_eq!(result.results.len(), 1);
        assert_eq!(result.results[0].status, TaskStatus::Empty);
        assert_eq!(result.results[0].attribution, Attribution::None);
        assert!(result.results[0].raw_items.is_empty());
        assert!(result.results[0].text.is_none());
        assert!(result.results[0].segments.is_empty());
        assert_eq!(result.extra_items.len(), 1);
        assert_eq!(result.extra_items[0].reason, ExtraReason::Unmatched);
        assert!(result.extra_items[0].affected_task_indexes.is_empty());
        assert_counts(&result, (0, 1, 0, 0, 1));
        assert_eq!(result.status, BatchStatus::PartialSuccess);
        assert_eq!(result.exit_code(), 2);
        assert_eq!(
            transport
                .requests()
                .iter()
                .filter(|request| request.method == reqwest::Method::POST)
                .count(),
            1,
            "cross-type mismatch must not trigger another Run"
        );
    }
}

#[test]
fn uncertain_bulk_create_is_not_retried_and_has_no_task_rows() {
    let transport = Arc::new(FakeTransport {
        queue: Mutex::new(VecDeque::from([Err(TransportError::new(
            TransportErrorKind::Timeout,
        ))])),
        requests: Mutex::new(vec![]),
        events: Arc::new(Mutex::new(vec![])),
    });
    let result = execute_bulk(
        &fixture_config(transport.clone()),
        &urls(&["https://instagram.com/reel/A"]),
        BulkOptions::default(),
    );
    assert_eq!(result.status, BatchStatus::CreationUnknown);
    assert_eq!(result.exit_code(), 10);
    assert_eq!(
        transport
            .requests()
            .iter()
            .filter(|r| r.method == reqwest::Method::POST)
            .count(),
        1,
        "creation_unknown must not retry create POST"
    );
    assert!(result.results.is_empty());
    assert_eq!(result.planned_task_count, Some(1));
}

#[test]
fn explicit_create_rejection_is_one_post_and_uses_its_operation_exit_code() {
    let transport = Arc::new(FakeTransport::new(vec![Response::json(
        400,
        json!({"error":"rejected"}),
    )]));
    let result = execute_bulk(
        &fixture_config(transport.clone()),
        &urls(&["https://instagram.com/reel/A"]),
        BulkOptions::default(),
    );
    assert_eq!(result.status, BatchStatus::Error);
    assert_eq!(result.error_code.as_deref(), Some("create_rejected"));
    assert_eq!(result.exit_code(), 4);
    assert!(result.results.is_empty());
    assert_eq!(result.counts.error, 0);
    assert_eq!(
        transport
            .requests()
            .iter()
            .filter(|r| r.method == reqwest::Method::POST)
            .count(),
        1
    );
}

struct FailingJournal;
impl crate::journal::Journal for FailingJournal {
    fn append(&self, _: &JournalRecord) -> Result<()> {
        Err(Error::new(
            ErrorKind::Journal,
            "journal",
            "synthetic journal failure",
        ))
    }
    fn latest(&self, _: &str) -> Result<Option<JournalRecord>> {
        Ok(None)
    }
}

#[test]
fn journal_intent_failure_fails_closed_before_create_post() {
    let transport = Arc::new(FakeTransport::new(vec![]));
    let config = Config::builder()
        .token("synthetic-token")
        .max_total_charge_usd("0.10")
        .transport(transport.clone())
        .clock(Arc::new(FakeClock))
        .journal(Arc::new(FailingJournal))
        .build()
        .unwrap();
    let result = execute_bulk(
        &config,
        &urls(&["https://instagram.com/reel/A"]),
        BulkOptions::default(),
    );
    assert_eq!(result.error_code.as_deref(), Some("journal_error"));
    assert_eq!(result.exit_code(), 2);
    assert!(
        transport.requests().is_empty(),
        "journal intent failure must mean POST=0"
    );
}

#[test]
fn build_mismatch_stops_before_dataset_and_preserves_observed_identity() {
    let transport = Arc::new(FakeTransport::new(vec![
        Response::json(201, json!({"data":{"id":"run-wrong-build"}})),
        Response::json(
            200,
            json!({"data":{"id":"run-wrong-build","status":"SUCCEEDED","defaultDatasetId":"dataset-x","buildNumber":"0.0.49","buildId":"wrong"}}),
        ),
    ]));
    let result = execute_bulk(
        &fixture_config(transport.clone()),
        &urls(&["https://instagram.com/reel/A"]),
        BulkOptions::default(),
    );
    assert_eq!(result.error_code.as_deref(), Some("build_mismatch"));
    assert_eq!(result.exit_code(), 7);
    assert_eq!(
        result.results[0].error_code.as_deref(),
        Some("build_mismatch")
    );
    assert_eq!(result.build_number.as_deref(), Some("0.0.49"));
    assert_eq!(
        transport.requests().len(),
        2,
        "no Dataset read after Build mismatch"
    );
}

#[test]
fn run_failed_maps_to_explicit_task_errors_and_preserves_run_identity() {
    let transport = Arc::new(FakeTransport::new(vec![
        Response::json(201, json!({"data":{"id":"run-failed-bulk"}})),
        Response::json(
            200,
            json!({"data":{"id":"run-failed-bulk","status":"FAILED","defaultDatasetId":"dataset-failed-bulk","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}),
        ),
    ]));
    let result = execute_bulk(
        &fixture_config(transport.clone()),
        &urls(&["https://instagram.com/reel/A"]),
        BulkOptions::default(),
    );
    assert_eq!(result.status, BatchStatus::Error);
    assert_eq!(result.error_code.as_deref(), Some("run_failed"));
    assert_eq!(result.exit_code(), 9);
    assert_eq!(result.run_id.as_deref(), Some("run-failed-bulk"));
    assert_eq!(result.dataset_id.as_deref(), Some("dataset-failed-bulk"));
    assert_eq!(result.run_status.as_deref(), Some("FAILED"));
    assert_eq!(result.results[0].error_code.as_deref(), Some("run_failed"));
    assert_counts(&result, (0, 0, 0, 1, 0));
    assert_eq!(
        transport.requests().len(),
        2,
        "failed Run must not read Dataset"
    );
}

#[test]
fn batch_operation_schema_keeps_planned_count_present_or_null() {
    let not_planned = BulkResult::operation_error("input_error", "bad URL", None, None, None);
    let serialized = serde_json::to_value(not_planned).unwrap();
    assert!(serialized.get("plannedTaskCount").is_some());
    assert!(serialized["plannedTaskCount"].is_null());
    let planned = BulkResult::operation_error("creation_unknown", "unknown", Some(2), None, None);
    assert_eq!(
        serde_json::to_value(planned).unwrap()["plannedTaskCount"],
        2
    );
}

#[test]
fn every_operation_error_code_has_a_frozen_status_exit_and_empty_task_shape() {
    let cases = [
        ("input_error", BatchStatus::InputError, 2),
        ("create_rejected", BatchStatus::Error, 4),
        ("creation_unknown", BatchStatus::CreationUnknown, 10),
        ("output_error", BatchStatus::OutputError, 2),
        ("journal_error", BatchStatus::Error, 2),
        ("transport_error", BatchStatus::Error, 8),
        ("run_failed", BatchStatus::Error, 9),
        ("build_mismatch", BatchStatus::Error, 7),
        ("dataset_error", BatchStatus::Error, 7),
        ("attribution_error", BatchStatus::Error, 7),
    ];
    for (code, status, exit_code) in cases {
        let result = BulkResult::operation_error(
            code,
            "synthetic diagnostic",
            Some(2),
            Some("run".into()),
            Some("dataset".into()),
        );
        assert_eq!(result.status, status, "status for {code}");
        assert_eq!(
            result.error_code.as_deref(),
            Some(code),
            "error code for {code}"
        );
        assert_eq!(result.exit_code(), exit_code, "exit code for {code}");
        assert!(result.results.is_empty(), "task rows emitted for {code}");
        assert!(result.extra_items.is_empty(), "extras emitted for {code}");
        assert_counts(&result, (0, 0, 0, 0, 0));
        assert_eq!(result.planned_task_count, Some(2));
        assert_eq!(result.run_id.as_deref(), Some("run"));
        assert_eq!(result.dataset_id.as_deref(), Some("dataset"));
    }
}

#[test]
fn normal_bulk_serialization_uses_frozen_camel_case_schema_and_counts() {
    let result = result_for(
        &["https://instagram.com/reel/ABC"],
        vec![usable("https://instagram.com/reel/ABC", "ok")],
        true,
    );
    let value = serde_json::to_value(result).unwrap();
    assert_eq!(value["plannedTaskCount"], 1);
    assert_eq!(value["results"][0]["identity"]["mediaType"], "reel");
    assert_eq!(value["counts"]["success"], 1);
    assert_eq!(value["results"][0]["attribution"], "exact_url");

    let with_secret = result_for(
        &["https://instagram.com/reel/ABC"],
        vec![
            json!({"url":"https://instagram.com/reel/ABC","shortCode":"ABC","text":"caption api_key=OPAQUE_BULK_RESULT_SECRET"}),
        ],
        true,
    );
    let serialized = serde_json::to_string(&with_secret).unwrap();
    assert!(
        !serialized.contains("OPAQUE_BULK_RESULT_SECRET"),
        "secret persisted"
    );
    assert!(serialized.contains("caption api_key=[REDACTED]"));
}

#[test]
fn resume_bulk_reads_existing_run_and_never_posts() {
    let journal = Arc::new(crate::journal::InMemoryJournal::default());
    journal.append(&JournalRecord { stage: "run_created".into(), mode: "native_bulk".into(), actor_id: "actor".into(),
        source_url: None, run_id: Some("resume-bulk-run".into()), dataset_id: None, run_status: None,
        build_number: Some("0.0.50".into()), build_id: Some("aJLRmMdQapLQRT4sJ".into()), build_verification: "pending".into(),
        cap: Some("0.10".into()), input_digest: None,
        context: Some(json!({"mode":"native_bulk","input":{"bulkUrls":["https://instagram.com/reel/ABC"],"resultsLimit":12}})), error: None }).unwrap();
    let transport = Arc::new(FakeTransport::new(vec![
        Response::json(
            200,
            json!({"data":{"id":"resume-bulk-run","status":"SUCCEEDED","defaultDatasetId":"resume-bulk-dataset","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}),
        ),
        Response::json(
            200,
            json!([usable(
                "https://instagram.com/reel/ABC",
                "resumed transcript"
            )]),
        ),
    ]));
    let config = Config::builder()
        .token("synthetic-test-token")
        .max_total_charge_usd("0.10")
        .transport(transport.clone())
        .clock(Arc::new(FakeClock))
        .journal(journal)
        .build()
        .unwrap();
    let result = resume_bulk(
        &config,
        "resume-bulk-run",
        &urls(&["https://instagram.com/reel/ABC"]),
    );
    assert_eq!(result.status, BatchStatus::Success);
    assert_eq!(
        result.results[0].text.as_deref(),
        Some("resumed transcript")
    );
    assert_eq!(
        transport
            .events
            .lock()
            .unwrap()
            .iter()
            .filter(|e| **e == "post")
            .count(),
        0
    );
}

fn resume_bulk_fixture(
    stage: &str,
    run_id: Option<&str>,
    context: Value,
    responses: Vec<Response>,
    dataset_page_limit: usize,
) -> (
    BulkResult,
    Arc<FakeTransport>,
    Arc<crate::journal::InMemoryJournal>,
) {
    let journal = Arc::new(crate::journal::InMemoryJournal::default());
    journal
        .append(&JournalRecord {
            stage: stage.into(),
            mode: "native_bulk".into(),
            actor_id: "actor".into(),
            source_url: None,
            run_id: run_id.map(str::to_owned),
            dataset_id: None,
            run_status: None,
            build_number: Some("0.0.50".into()),
            build_id: Some("aJLRmMdQapLQRT4sJ".into()),
            build_verification: "pending".into(),
            cap: Some("0.10".into()),
            input_digest: None,
            context: Some(context),
            error: None,
        })
        .unwrap();
    let transport = Arc::new(FakeTransport::new(responses));
    let config = Config::builder()
        .token("synthetic-test-token")
        .max_total_charge_usd("0.10")
        .dataset_page_limit(dataset_page_limit)
        .transport(transport.clone())
        .clock(Arc::new(FakeClock))
        .journal(journal.clone())
        .build()
        .unwrap();
    let result = resume_bulk(
        &config,
        "resume-bulk-run",
        &urls(&["https://instagram.com/reel/ABC"]),
    );
    (result, transport, journal)
}

fn resume_bulk_context(url: &str) -> Value {
    json!({"mode":"native_bulk","input":{"bulkUrls":[url],"resultsLimit":12}})
}

#[test]
fn resume_bulk_input_mismatch_fails_before_any_request() {
    let (result, transport, _) = resume_bulk_fixture(
        "run_created",
        Some("resume-bulk-run"),
        resume_bulk_context("https://instagram.com/reel/OTHER"),
        vec![],
        100,
    );
    assert_eq!(result.error_code.as_deref(), Some("journal_error"));
    assert!(transport.requests().is_empty());
}

#[test]
fn resume_bulk_intent_without_run_id_is_not_reposted() {
    let (result, transport, _) = resume_bulk_fixture(
        "intent",
        None,
        resume_bulk_context("https://instagram.com/reel/ABC"),
        vec![],
        100,
    );
    assert_eq!(result.error_code.as_deref(), Some("journal_error"));
    assert!(transport.requests().is_empty());
}

#[test]
fn resume_bulk_run_failure_is_get_only_and_stops_before_dataset() {
    let (result, transport, journal) = resume_bulk_fixture(
        "run_created",
        Some("resume-bulk-run"),
        resume_bulk_context("https://instagram.com/reel/ABC"),
        vec![Response::json(
            200,
            json!({"data":{"status":"FAILED","defaultDatasetId":"unused"}}),
        )],
        100,
    );
    assert_eq!(result.error_code.as_deref(), Some("run_failed"));
    assert_eq!(transport.requests().len(), 1);
    assert_eq!(transport.requests()[0].method, reqwest::Method::GET);
    let terminal = journal.latest("resume-bulk-run").unwrap().unwrap();
    assert_eq!(terminal.stage, "run_terminal");
    assert_eq!(terminal.run_status.as_deref(), Some("FAILED"));
}

#[test]
fn resume_bulk_build_mismatch_is_get_only_and_stops_before_dataset() {
    let (result, transport, journal) = resume_bulk_fixture(
        "run_created",
        Some("resume-bulk-run"),
        resume_bulk_context("https://instagram.com/reel/ABC"),
        vec![Response::json(
            200,
            json!({"data":{"status":"SUCCEEDED","defaultDatasetId":"unused","buildNumber":"0.0.49","buildId":"wrong"}}),
        )],
        100,
    );
    assert_eq!(result.error_code.as_deref(), Some("build_mismatch"));
    assert_eq!(transport.requests().len(), 1);
    assert_eq!(transport.requests()[0].method, reqwest::Method::GET);
    let terminal = journal.latest("resume-bulk-run").unwrap().unwrap();
    assert_eq!(terminal.stage, "run_terminal");
    assert_eq!(terminal.build_verification, "mismatch");
}

#[test]
fn resume_bulk_incomplete_dataset_is_untrusted_and_get_only() {
    let (result, transport, _) = resume_bulk_fixture(
        "run_created",
        Some("resume-bulk-run"),
        resume_bulk_context("https://instagram.com/reel/ABC"),
        vec![
            Response::json(
                200,
                json!({"data":{"status":"SUCCEEDED","defaultDatasetId":"dataset","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}),
            ),
            Response::json(
                200,
                json!([usable("https://instagram.com/reel/ABC", "partial")]),
            ),
        ],
        1,
    );
    assert_eq!(result.status, BatchStatus::PartialSuccess);
    assert_eq!(result.results[0].status, TaskStatus::Success);
    assert!(!result.dataset_complete);
    assert!(transport
        .requests()
        .iter()
        .all(|request| request.method == reqwest::Method::GET));
}
