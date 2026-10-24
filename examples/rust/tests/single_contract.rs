use instagram_transcripts::{
    status::{AttributionVerification, Status},
    Client, Config, ErrorKind, InMemoryJournal, Journal, JournalRecord, Request, Response,
    Transport, TransportError, TransportErrorKind,
};
use reqwest::Method;
use serde_json::{json, Value};
use std::{
    collections::VecDeque,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

#[derive(Default)]
struct FakeTransport {
    steps: Mutex<VecDeque<std::result::Result<Response, TransportError>>>,
    requests: Mutex<Vec<Request>>,
}
impl FakeTransport {
    fn with(steps: Vec<std::result::Result<Response, TransportError>>) -> Self {
        Self {
            steps: Mutex::new(steps.into()),
            requests: Mutex::new(Vec::new()),
        }
    }
    fn requests(&self) -> Vec<Request> {
        self.requests.lock().unwrap().clone()
    }
    fn posts(&self) -> usize {
        self.requests()
            .iter()
            .filter(|r| r.method == Method::POST)
            .count()
    }
    fn datasets(&self) -> usize {
        self.requests()
            .iter()
            .filter(|r| r.url.contains("/datasets/"))
            .count()
    }
}
impl Transport for FakeTransport {
    fn send(&self, r: &Request) -> std::result::Result<Response, TransportError> {
        self.requests.lock().unwrap().push(r.clone());
        self.steps
            .lock()
            .unwrap()
            .pop_front()
            .expect("unexpected HTTP request")
    }
    fn guarantees_single_shot_post(&self) -> bool {
        true
    }
}
struct FakeClock {
    origin: Instant,
    elapsed: Mutex<Duration>,
}
impl Default for FakeClock {
    fn default() -> Self {
        Self {
            origin: Instant::now(),
            elapsed: Mutex::new(Duration::ZERO),
        }
    }
}
impl instagram_transcripts::Clock for FakeClock {
    fn now(&self) -> Instant {
        self.origin + *self.elapsed.lock().unwrap()
    }
    fn sleep(&self, d: Duration) {
        *self.elapsed.lock().unwrap() += d;
    }
}
fn ok(v: Value) -> std::result::Result<Response, TransportError> {
    Ok(Response::json(200, v))
}
fn post_ok() -> std::result::Result<Response, TransportError> {
    Ok(Response::json(201, json!({"data":{"id":"run-1"}})))
}
fn run(
    status: &str,
    number: Value,
    id: &str,
    dataset: Option<&str>,
) -> std::result::Result<Response, TransportError> {
    let mut d = json!({"id":"run-1","status":status,"buildNumber":number,"buildId":id});
    if let Some(ds) = dataset {
        d["defaultDatasetId"] = json!(ds);
    }
    ok(json!({"data":d}))
}
fn item(url: &str, extra: Value) -> Value {
    let mut v = json!({"url":url});
    if let (Some(a), Some(b)) = (v.as_object_mut(), extra.as_object()) {
        for (k, x) in b {
            a.insert(k.clone(), x.clone());
        }
    }
    v
}
fn good_steps(items: Value) -> Vec<std::result::Result<Response, TransportError>> {
    vec![
        post_ok(),
        run(
            "SUCCEEDED",
            json!("0.0.50"),
            "aJLRmMdQapLQRT4sJ",
            Some("ds-1"),
        ),
        ok(items),
    ]
}
fn config(t: Arc<FakeTransport>, j: Option<Arc<dyn Journal>>, timeout: Duration) -> Config {
    let mut b = Config::builder()
        .token("synthetic-token")
        .max_total_charge_usd("0.10")
        .transport(t)
        .clock(Arc::new(FakeClock::default()))
        .poll_timeout(timeout);
    if let Some(j) = j {
        b = b.journal(j);
    }
    b.build().unwrap()
}
const URL: &str = "https://www.instagram.com/reel/ABC123/";

#[test]
fn a_post_timeout_is_creation_unknown_once() {
    // Prevents a timeout from replaying a potentially accepted billable POST.
    let t = Arc::new(FakeTransport::with(vec![Err(TransportError::new(
        TransportErrorKind::Timeout,
    ))]));
    let e = Client::new(config(t.clone(), None, Duration::from_secs(20)))
        .get_transcript(URL)
        .unwrap_err();
    assert_eq!(e.kind, ErrorKind::CreationUnknown);
    assert_eq!(t.posts(), 1, "single-shot POST invariant violated");
}
#[test]
fn b_missing_run_id_is_unknown_once() {
    // Prevents malformed successful create responses from triggering another POST.
    let t = Arc::new(FakeTransport::with(vec![Ok(Response::json(
        201,
        json!({"data":{"status":"READY"}}),
    ))]));
    let e = Client::new(config(t.clone(), None, Duration::from_secs(3)))
        .get_transcript(URL)
        .unwrap_err();
    assert_eq!(e.kind, ErrorKind::CreationUnknown);
    assert_eq!(t.posts(), 1);
}
#[test]
fn c_poll_timeout_keeps_run_id_and_never_recreates() {
    // Prevents polling timeout recovery from restarting paid work.
    let t = Arc::new(FakeTransport::with(vec![
        post_ok(),
        run("RUNNING", json!("0.0.50"), "aJLRmMdQapLQRT4sJ", Some("ds")),
        run("RUNNING", json!("0.0.50"), "aJLRmMdQapLQRT4sJ", Some("ds")),
    ]));
    let e = Client::new(config(t.clone(), None, Duration::from_secs(2)))
        .get_transcript(URL)
        .unwrap_err();
    assert_eq!(e.kind, ErrorKind::Transport);
    assert_eq!(e.run_id.as_deref(), Some("run-1"));
    assert!(e.message.contains("run-1"));
    assert_eq!(t.posts(), 1);
}
#[test]
fn d_failed_run_is_classified_and_not_retried() {
    // Prevents a terminal Actor failure from being mistaken for a reason to recreate.
    let t = Arc::new(FakeTransport::with(vec![
        post_ok(),
        run("FAILED", json!("0.0.50"), "aJLRmMdQapLQRT4sJ", Some("ds")),
    ]));
    let e = Client::new(config(t.clone(), None, Duration::from_secs(3)))
        .get_transcript(URL)
        .unwrap_err();
    assert_eq!(e.kind, ErrorKind::RunFailed);
    assert_eq!(t.posts(), 1);
}
#[test]
fn e_dataset_500_does_not_recreate() {
    // Exhausts the bounded GET retries while proving no second create POST occurs.
    let mut steps = vec![
        post_ok(),
        run(
            "SUCCEEDED",
            json!("0.0.50"),
            "aJLRmMdQapLQRT4sJ",
            Some("ds-1"),
        ),
    ];
    steps.extend((0..4).map(|_| Ok(Response::json(500, json!({"error":"private body"})))));
    let t = Arc::new(FakeTransport::with(steps));
    let e = Client::new(config(t.clone(), None, Duration::from_secs(20)))
        .get_transcript(URL)
        .unwrap_err();
    assert_eq!(e.kind, ErrorKind::Dataset);
    assert!(!e.message.contains("private body"));
    assert_eq!(t.posts(), 1);
    assert_eq!(t.datasets(), 4);
}
#[test]
fn f_dataset_object_shape_is_rejected() {
    // Locks the actual bare-array Dataset wire contract against wrapper-object regressions.
    let t = Arc::new(FakeTransport::with(good_steps(json!({"data":[]}))));
    let e = Client::new(config(t.clone(), None, Duration::from_secs(3)))
        .get_transcript(URL)
        .unwrap_err();
    assert_eq!(e.kind, ErrorKind::Protocol);
    assert_eq!(t.posts(), 1);
}
#[test]
fn g_limit_hit_is_unknown_and_incomplete() {
    // Prevents a capped Dataset page from being advertised as a complete transcript.
    let t = Arc::new(FakeTransport::with(good_steps(json!([item(
        URL,
        json!({"text":"x"})
    )]))));
    let mut c = Config::builder()
        .token("synthetic-token")
        .max_total_charge_usd("0.1")
        .dataset_page_limit(1)
        .transport(t.clone())
        .build()
        .unwrap();
    let _ = &mut c;
    let r = Client::new(c).get_transcript(URL).unwrap();
    assert_eq!(r.status, Status::Unknown);
    assert!(!r.dataset_complete);
}
#[test]
fn h_unmatched_dataset_url_never_leaks_transcript() {
    // Prevents another video's transcript from being returned for this input.
    let t = Arc::new(FakeTransport::with(good_steps(json!([item(
        "https://instagram.com/reel/OTHER",
        json!({"text":"wrong transcript"})
    )]))));
    let result = Client::new(config(t.clone(), None, Duration::from_secs(3))).get_transcript(URL);
    assert_eq!(t.posts(), 1, "single-shot POST invariant violated");
    let r = result.unwrap();
    assert_eq!(
        r.status,
        Status::Unknown,
        "unmatched dataset URL must stay unknown"
    );
    assert_eq!(r.text, None);
    assert_eq!(r.attribution_verification, AttributionVerification::Unknown);
}
#[test]
fn i_actor_error_precedes_present_transcript() {
    // Prevents errMsg-bearing items from being reported as successful transcripts.
    let t = Arc::new(FakeTransport::with(good_steps(json!([item(
        URL,
        json!({"text":"not success","errMsg":"crawed empty"})
    )]))));
    let r = Client::new(config(t, None, Duration::from_secs(3)))
        .get_transcript(URL)
        .unwrap();
    assert_eq!(r.status, Status::ActorError);
    assert!(r.error.unwrap().contains("crawed empty"));
}
#[test]
fn j_missing_text_is_no_transcript() {
    // Prevents an item without transcript text from being reported as success.
    let t = Arc::new(FakeTransport::with(good_steps(json!([item(
        URL,
        json!({"segments":[]})
    )]))));
    let r = Client::new(config(t, None, Duration::from_secs(3)))
        .get_transcript(URL)
        .unwrap();
    assert_eq!(r.status, Status::NoTranscript);
}
#[test]
fn m_build_mismatch_blocks_dataset_read() {
    // Prevents data from an unapproved Actor Build from entering results.
    let t = Arc::new(FakeTransport::with(vec![
        post_ok(),
        run("SUCCEEDED", json!("0.0.51"), "wrong", Some("ds")),
    ]));
    let e = Client::new(config(t.clone(), None, Duration::from_secs(3)))
        .get_transcript(URL)
        .unwrap_err();
    assert_eq!(e.kind, ErrorKind::BuildMismatch);
    assert_eq!(t.datasets(), 0);
    assert_eq!(t.posts(), 1, "single-shot POST invariant violated");
}
#[test]
fn n_missing_charge_cap_fails_before_transport() {
    // Prevents any request from being issued when a required cap is absent.
    let t = Arc::new(FakeTransport::default());
    let result = Config::builder()
        .token("synthetic")
        .transport(t.clone())
        .build();
    assert!(
        matches!(result, Err(ref error) if error.kind == ErrorKind::Configuration),
        "missing charge cap must fail before transport"
    );
    assert_eq!(t.requests().len(), 0);
}
#[test]
fn create_rejection_is_not_retried() {
    // Prevents explicit authorization/configuration rejection from causing another attempt.
    let t = Arc::new(FakeTransport::with(vec![Ok(Response::json(
        401,
        json!({"error":"secret"}),
    ))]));
    let e = Client::new(config(t.clone(), None, Duration::from_secs(3)))
        .get_transcript(URL)
        .unwrap_err();
    assert_eq!(e.kind, ErrorKind::CreateRejected);
    assert_eq!(t.posts(), 1);
}
#[test]
fn redirect_307_is_unknown_and_not_followed() {
    // Prevents POST replay through redirect behavior.
    let t = Arc::new(FakeTransport::with(vec![Ok(Response::json(
        307,
        json!({"location":"elsewhere"}),
    ))]));
    let e = Client::new(config(t.clone(), None, Duration::from_secs(3)))
        .get_transcript(URL)
        .unwrap_err();
    assert_eq!(e.kind, ErrorKind::CreationUnknown);
    assert_eq!(t.requests().len(), 1);
}
#[test]
fn retry_after_retries_only_get() {
    // Allows safe GET polling recovery while preserving the single-create invariant.
    let mut pending = run("RUNNING", json!("0.0.50"), "aJLRmMdQapLQRT4sJ", Some("ds")).unwrap();
    pending.status = 200;
    pending.body = json!({"data":{"id":"r","status":"RUNNING"}}).to_string();
    pending.headers.insert("retry-after".into(), "0".into());
    let t = Arc::new(FakeTransport::with(vec![
        post_ok(),
        Ok(pending),
        run(
            "SUCCEEDED",
            json!("0.0.50"),
            "aJLRmMdQapLQRT4sJ",
            Some("ds"),
        ),
        ok(json!([item(URL, json!({"text":"ok"}))])),
    ]));
    let r = Client::new(config(t.clone(), None, Duration::from_secs(5)))
        .get_transcript(URL)
        .unwrap();
    assert_eq!(r.status, Status::Success);
    assert_eq!(t.posts(), 1);
}
#[test]
fn session_is_omitted_unless_explicit() {
    // Prevents an absent optional session identifier from changing Actor input.
    let t = Arc::new(FakeTransport::with(good_steps(json!([item(
        URL,
        json!({"text":"ok"})
    )]))));
    let _ = Client::new(config(t.clone(), None, Duration::from_secs(3)))
        .get_transcript(URL)
        .unwrap();
    let req = t
        .requests()
        .into_iter()
        .find(|r| r.method == Method::POST)
        .unwrap();
    assert!(req.body.unwrap().get("sessionid").is_none());
}
#[test]
fn cap_and_restart_are_query_parameters_only() {
    // Prevents the cap from being misplaced in input and locks restart protection.
    let t = Arc::new(FakeTransport::with(good_steps(json!([item(
        URL,
        json!({"text":"ok"})
    )]))));
    let _ = Client::new(config(t.clone(), None, Duration::from_secs(3)))
        .get_transcript(URL)
        .unwrap();
    let req = t
        .requests()
        .into_iter()
        .find(|r| r.method == Method::POST)
        .unwrap();
    assert!(req.url.contains("maxTotalChargeUsd=0.10"));
    assert!(req.url.contains("restartOnError=false"));
    let body = req.body.unwrap();
    assert!(body.get("maxTotalChargeUsd").is_none());
    assert_eq!(body["videoUrl"], URL);
}
#[test]
fn journal_intent_is_written_before_post() {
    // Prevents a billable create attempt without prior recovery intent.
    let j = Arc::new(InMemoryJournal::default());
    let t = Arc::new(FakeTransport::with(good_steps(json!([item(
        URL,
        json!({"text":"ok"})
    )]))));
    let _ = Client::new(config(t.clone(), Some(j.clone()), Duration::from_secs(3)))
        .get_transcript(URL)
        .unwrap();
    let records = j.records();
    assert_eq!(records[0].stage, "intent");
    assert_eq!(records[1].stage, "run_created");
    assert_eq!(
        records[0].context.as_ref().unwrap()["sessionid"],
        Value::Null
    );
    assert_eq!(t.posts(), 1);
}
struct FailJournal;
impl Journal for FailJournal {
    fn append(&self, _: &JournalRecord) -> instagram_transcripts::Result<()> {
        Err(instagram_transcripts::Error::new(
            ErrorKind::Journal,
            "test",
            "disk error",
        ))
    }
    fn latest(&self, _: &str) -> instagram_transcripts::Result<Option<JournalRecord>> {
        Ok(None)
    }
}
#[test]
fn journal_failure_prevents_post() {
    // Prevents execution when durable intent recording fails.
    let t = Arc::new(FakeTransport::default());
    let e = Client::new(config(
        t.clone(),
        Some(Arc::new(FailJournal)),
        Duration::from_secs(3),
    ))
    .get_transcript(URL)
    .unwrap_err();
    assert_eq!(e.kind, ErrorKind::Journal);
    assert_eq!(t.posts(), 0);
}
#[test]
fn invalid_url_fails_before_any_request() {
    // Prevents malformed URLs from reaching Actor creation.
    let t = Arc::new(FakeTransport::default());
    let e = Client::new(config(t.clone(), None, Duration::from_secs(3)))
        .get_transcript("http://instagram.com/reel/a")
        .unwrap_err();
    assert_eq!(e.kind, ErrorKind::Input);
    assert_eq!(t.requests().len(), 0);
}
#[test]
fn extra_dataset_item_is_retained_but_not_used() {
    // Prevents extras from being attributed by position while preserving raw evidence.
    let t = Arc::new(FakeTransport::with(good_steps(json!([
        item(URL, json!({"text":"right"})),
        item("https://instagram.com/reel/OTHER", json!({"text":"wrong"}))
    ]))));
    let r = Client::new(config(t, None, Duration::from_secs(3)))
        .get_transcript(URL)
        .unwrap();
    assert_eq!(r.status, Status::Unknown);
    assert_eq!(r.text, None);
    assert_eq!(r.raw_items.len(), 2);
}
#[test]
fn successful_result_preserves_run_dataset_build_and_segments() {
    // Locks the public result contract for a correctly attributed Single response.
    let t = Arc::new(FakeTransport::with(good_steps(json!([item(
        URL,
        json!({"text":"transcript","segments":[{"start":0,"text":"hello"}]})
    )]))));
    let result = Client::new(config(t.clone(), None, Duration::from_secs(3))).get_transcript(URL);
    assert_eq!(t.posts(), 1, "single-shot POST invariant violated");
    let r = result.unwrap();
    assert_eq!(r.status, Status::Success);
    assert_eq!(r.run_id.as_deref(), Some("run-1"));
    assert_eq!(r.dataset_id.as_deref(), Some("ds-1"));
    assert_eq!(r.build_number.as_deref(), Some("0.0.50"));
    assert_eq!(r.build_id.as_deref(), Some("aJLRmMdQapLQRT4sJ"));
    assert_eq!(r.segments.len(), 1);
}
#[test]
fn explicit_session_only_added_when_nonempty() {
    // Prevents emitting empty sessionid while retaining explicit opt-in behavior.
    let t = Arc::new(FakeTransport::with(good_steps(json!([item(
        URL,
        json!({"text":"ok"})
    )]))));
    let c = Config::builder()
        .token("synthetic")
        .max_total_charge_usd("0.10")
        .session_id(Some("synthetic-session".into()))
        .transport(t.clone())
        .build()
        .unwrap();
    let _ = Client::new(c).get_transcript(URL).unwrap();
    let req = t
        .requests()
        .into_iter()
        .find(|r| r.method == Method::POST)
        .unwrap();
    assert_eq!(req.body.unwrap()["sessionid"], "synthetic-session");
}
#[test]
fn build_number_and_id_must_both_match() {
    // Prevents accepting a Run based on only one Build identity field.
    let t = Arc::new(FakeTransport::with(vec![
        post_ok(),
        run("SUCCEEDED", json!("0.0.50"), "wrong", Some("ds")),
    ]));
    let e = Client::new(config(t.clone(), None, Duration::from_secs(3)))
        .get_transcript(URL)
        .unwrap_err();
    assert_eq!(e.kind, ErrorKind::BuildMismatch);
    assert_eq!(t.datasets(), 0);
}
#[test]
fn pending_run_uses_get_not_post() {
    // Prevents polling an existing Run through a mutating endpoint.
    let t = Arc::new(FakeTransport::with(vec![
        post_ok(),
        run("RUNNING", json!("0.0.50"), "aJLRmMdQapLQRT4sJ", Some("ds")),
        run(
            "SUCCEEDED",
            json!("0.0.50"),
            "aJLRmMdQapLQRT4sJ",
            Some("ds"),
        ),
        ok(json!([item(URL, json!({"text":"ok"}))])),
    ]));
    let r = Client::new(config(t.clone(), None, Duration::from_secs(5)))
        .get_transcript(URL)
        .unwrap();
    assert_eq!(r.status, Status::Success);
    assert_eq!(t.posts(), 1);
    assert!(t
        .requests()
        .iter()
        .filter(|r| r.url.contains("actor-runs"))
        .all(|r| r.method == Method::GET));
}
#[test]
fn response_body_never_enters_http_diagnostic() {
    // Prevents raw server errors from leaking arbitrary response content.
    let t = Arc::new(FakeTransport::with(vec![Ok(Response::json(
        500,
        json!({"token":"synthetic-secret","detail":"raw body"}),
    ))]));
    let e = Client::new(config(t.clone(), None, Duration::from_secs(3)))
        .get_transcript(URL)
        .unwrap_err();
    assert!(!e.message.contains("raw body"));
    assert!(!e.message.contains("synthetic-secret"));
    assert_eq!(t.posts(), 1);
}

#[test]
fn legacy_csv_binary_is_disabled() {
    // Proves the historical billable CSV implementation cannot be reached as a Cargo binary.
    let output = std::process::Command::new(env!("CARGO_BIN_EXE_batch_csv"))
        .output()
        .expect("legacy binary should launch");
    assert_eq!(output.status.code(), Some(2));
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("is disabled"));
}

#[test]
fn cli_rejects_invalid_input_before_credentials_or_network() {
    // Proves invalid CLI URLs fail before credential handling and never invoke Actor transport.
    let output = std::process::Command::new(env!("CARGO_BIN_EXE_instagram-transcripts"))
        .args(["single", "https://instagram.com/reel/abc?query=blocked"])
        .env("APIFY_TOKEN", "synthetic-cli-token")
        .output()
        .expect("CLI should launch");
    assert_eq!(output.status.code(), Some(2));
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stdout.is_empty());
    assert!(stderr.contains("ResultStatus: configuration_error"));
    assert!(!stderr.contains("synthetic-cli-token"));
}

#[test]
fn unsafe_transport_is_rejected_at_configuration_time() {
    // Prevents a custom transport without a single-shot POST guarantee from being used.
    struct UnsafeTransport;
    impl Transport for UnsafeTransport {
        fn send(&self, _: &Request) -> std::result::Result<Response, TransportError> {
            panic!("configuration must reject before sending")
        }
        fn guarantees_single_shot_post(&self) -> bool {
            false
        }
    }
    let result = Config::builder()
        .token("synthetic")
        .max_total_charge_usd("0.10")
        .transport(Arc::new(UnsafeTransport))
        .build();
    assert!(matches!(result, Err(ref error) if error.kind == ErrorKind::Configuration));
}

#[test]
fn empty_dataset_is_an_explicit_empty_result() {
    // Requires three empty observations before classifying a Dataset as genuinely empty.
    let t = Arc::new(FakeTransport::with(vec![
        post_ok(),
        run(
            "SUCCEEDED",
            json!("0.0.50"),
            "aJLRmMdQapLQRT4sJ",
            Some("ds-1"),
        ),
        ok(json!([])),
        ok(json!([])),
        ok(json!([])),
    ]));
    let result = Client::new(config(t.clone(), None, Duration::from_secs(10)))
        .get_transcript(URL)
        .unwrap();
    assert_eq!(result.status, Status::Empty);
    assert!(result.dataset_complete);
    assert_eq!(t.posts(), 1);
    assert_eq!(t.datasets(), 3);
}

#[test]
fn empty_dataset_visibility_lag_recovers_without_recreating_run() {
    let t = Arc::new(FakeTransport::with(vec![
        post_ok(),
        run(
            "SUCCEEDED",
            json!("0.0.50"),
            "aJLRmMdQapLQRT4sJ",
            Some("ds-1"),
        ),
        ok(json!([])),
        ok(json!([])),
        ok(json!([item(URL, json!({"text":"visible now"}))])),
    ]));
    let result = Client::new(config(t.clone(), None, Duration::from_secs(10)))
        .get_transcript(URL)
        .unwrap();
    assert_eq!(result.status, Status::Success);
    assert_eq!(result.text.as_deref(), Some("visible now"));
    assert_eq!(t.posts(), 1);
    assert_eq!(t.datasets(), 3);
}

#[test]
fn dataset_server_errors_retry_then_succeed_with_one_post() {
    let t = Arc::new(FakeTransport::with(vec![
        post_ok(),
        run(
            "SUCCEEDED",
            json!("0.0.50"),
            "aJLRmMdQapLQRT4sJ",
            Some("ds-1"),
        ),
        Ok(Response::json(500, json!({}))),
        Ok(Response::json(500, json!({}))),
        ok(json!([item(URL, json!({"text":"recovered"}))])),
    ]));
    let result = Client::new(config(t.clone(), None, Duration::from_secs(20)))
        .get_transcript(URL)
        .unwrap();
    assert_eq!(result.status, Status::Success);
    assert_eq!(t.posts(), 1);
    assert_eq!(t.datasets(), 3);
}

#[test]
fn dataset_four_server_errors_fail_with_run_id_and_one_post() {
    let mut steps = vec![
        post_ok(),
        run(
            "SUCCEEDED",
            json!("0.0.50"),
            "aJLRmMdQapLQRT4sJ",
            Some("ds-1"),
        ),
    ];
    steps.extend((0..4).map(|_| Ok(Response::json(500, json!({})))));
    let t = Arc::new(FakeTransport::with(steps));
    let error = Client::new(config(t.clone(), None, Duration::from_secs(20)))
        .get_transcript(URL)
        .unwrap_err();
    assert_eq!(error.kind, ErrorKind::Dataset);
    assert_eq!(error.run_id.as_deref(), Some("run-1"));
    assert_eq!(t.posts(), 1);
    assert_eq!(t.datasets(), 4);
}

#[test]
fn dataset_429_honors_retry_after_seconds() {
    let clock = Arc::new(FakeClock::default());
    let t = Arc::new(FakeTransport::with(vec![
        post_ok(),
        run(
            "SUCCEEDED",
            json!("0.0.50"),
            "aJLRmMdQapLQRT4sJ",
            Some("ds-1"),
        ),
        Ok(Response::json(429, json!({})).header("Retry-After", "2")),
        ok(json!([item(URL, json!({"text":"after rate limit"}))])),
    ]));
    let c = Config::builder()
        .token("synthetic-token")
        .max_total_charge_usd("0.10")
        .transport(t.clone())
        .clock(clock.clone())
        .poll_timeout(Duration::from_secs(10))
        .build()
        .unwrap();
    let result = Client::new(c).get_transcript(URL).unwrap();
    assert_eq!(result.status, Status::Success);
    assert_eq!(*clock.elapsed.lock().unwrap(), Duration::from_secs(2));
    assert_eq!(t.posts(), 1);
    assert_eq!(t.datasets(), 2);
}

#[test]
fn dataset_connection_failure_retries_but_nonretryable_4xx_does_not() {
    let t = Arc::new(FakeTransport::with(vec![
        post_ok(),
        run(
            "SUCCEEDED",
            json!("0.0.50"),
            "aJLRmMdQapLQRT4sJ",
            Some("ds-1"),
        ),
        Err(TransportError::new(TransportErrorKind::Connection)),
        ok(json!([item(URL, json!({"text":"after reconnect"}))])),
    ]));
    let result = Client::new(config(t.clone(), None, Duration::from_secs(10)))
        .get_transcript(URL)
        .unwrap();
    assert_eq!(result.status, Status::Success);
    assert_eq!(t.posts(), 1);
    assert_eq!(t.datasets(), 2);

    let t = Arc::new(FakeTransport::with(vec![
        post_ok(),
        run(
            "SUCCEEDED",
            json!("0.0.50"),
            "aJLRmMdQapLQRT4sJ",
            Some("ds-1"),
        ),
        Ok(Response::json(404, json!({}))),
    ]));
    let error = Client::new(config(t.clone(), None, Duration::from_secs(10)))
        .get_transcript(URL)
        .unwrap_err();
    assert_eq!(error.kind, ErrorKind::Dataset);
    assert_eq!(t.posts(), 1);
    assert_eq!(t.datasets(), 1);
}

#[test]
fn dataset_retry_after_past_deadline_does_not_sleep_or_retry() {
    let clock = Arc::new(FakeClock::default());
    let t = Arc::new(FakeTransport::with(vec![
        post_ok(),
        run(
            "SUCCEEDED",
            json!("0.0.50"),
            "aJLRmMdQapLQRT4sJ",
            Some("ds-1"),
        ),
        Ok(Response::json(503, json!({})).header("Retry-After", "2")),
    ]));
    let c = Config::builder()
        .token("synthetic-token")
        .max_total_charge_usd("0.10")
        .transport(t.clone())
        .clock(clock.clone())
        .poll_timeout(Duration::from_secs(2))
        .build()
        .unwrap();
    let error = Client::new(c).get_transcript(URL).unwrap_err();
    assert_eq!(error.kind, ErrorKind::Dataset);
    assert_eq!(*clock.elapsed.lock().unwrap(), Duration::ZERO);
    assert_eq!(t.posts(), 1);
    assert_eq!(t.datasets(), 1);
}

#[test]
fn empty_confirmations_and_transient_retries_share_four_get_budget() {
    let t = Arc::new(FakeTransport::with(vec![
        post_ok(),
        run(
            "SUCCEEDED",
            json!("0.0.50"),
            "aJLRmMdQapLQRT4sJ",
            Some("ds-1"),
        ),
        Ok(Response::json(500, json!({}))),
        ok(json!([])),
        ok(json!([])),
        ok(json!([])),
    ]));
    let result = Client::new(config(t.clone(), None, Duration::from_secs(20)))
        .get_transcript(URL)
        .unwrap();
    assert_eq!(result.status, Status::Empty);
    assert_eq!(t.posts(), 1);
    assert_eq!(t.datasets(), 4);
}

#[test]
fn malformed_dataset_items_are_not_success() {
    // Prevents malformed Actor item shapes from becoming an empty transcript success.
    let t = Arc::new(FakeTransport::with(good_steps(json!([
        "unexpected scalar"
    ]))));
    let result = Client::new(config(t, None, Duration::from_secs(3)))
        .get_transcript(URL)
        .unwrap();
    assert_eq!(result.status, Status::Unknown);
    assert_eq!(result.text, None);
}

#[test]
fn actor_id_is_encoded_in_run_endpoint() {
    // Prevents a slash or reserved actor identifier character from changing endpoint routing.
    let t = Arc::new(FakeTransport::with(good_steps(json!([item(
        URL,
        json!({"text":"ok"})
    )]))));
    let config = Config::builder()
        .token("synthetic")
        .actor_id("org/name?x")
        .max_total_charge_usd("0.10")
        .transport(t.clone())
        .build()
        .unwrap();
    Client::new(config).get_transcript(URL).unwrap();
    let post = t
        .requests()
        .into_iter()
        .find(|r| r.method == Method::POST)
        .unwrap();
    assert!(post.url.contains("/acts/org~name%3Fx/runs?"));
}
