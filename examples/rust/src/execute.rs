use crate::{
    attribution::attribute_single,
    config::Config,
    dataset::parse_dataset,
    error::{Error, ErrorKind, Result},
    journal::JournalRecord,
    status::{AttributionVerification, BuildVerification, Status, TranscriptResult},
    transport::{bearer_headers, Request},
    validators::{encode_actor_id, validate_video_url},
};
use reqwest::Method;
use serde_json::{json, Value};
use std::{
    hash::{Hash, Hasher},
    time::Duration,
};

const API: &str = "https://api.apify.com/v2";

pub(crate) fn get_transcript(config: &Config, url: &str) -> Result<TranscriptResult> {
    let source = validate_video_url(url)?;
    let input = json!({"videoUrl":source});
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    source.hash(&mut hasher);
    let intent = JournalRecord {
        stage: "intent".into(),
        mode: "single".into(),
        actor_id: config.actor_id.clone(),
        source_url: Some(source.clone()),
        run_id: None,
        dataset_id: None,
        run_status: None,
        build_number: Some(config.build_number.clone()),
        build_id: Some(config.build_id.clone()),
        build_verification: "pending".into(),
        cap: Some(config.charge_cap.clone()),
        input_digest: Some(format!("{:016x}", hasher.finish())),
        context: Some(input.clone()),
        error: None,
    };
    config.journal.append(&intent)?;
    let post = match post_run(config, &input) {
        Ok(value) => value,
        Err(error) => {
            let mut failure = intent.clone();
            failure.stage = if error.kind == ErrorKind::CreationUnknown {
                "creation_unknown"
            } else {
                "create_rejected"
            }
            .into();
            failure.error = Some(error.message.clone());
            // A failed journal append cannot trigger a replacement POST; report the original result.
            let _ = config.journal.append(&failure);
            return Err(error);
        }
    };
    let run_id = post
        .get("id")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .ok_or_else(|| {
            Error::new(
                ErrorKind::CreationUnknown,
                "run_create",
                "creation response did not contain a run id",
            )
        })?;
    let mut created = intent.clone();
    created.stage = "run_created".into();
    created.run_id = Some(run_id.clone());
    config.journal.append(&created).map_err(|mut error| {
        error.run_id = Some(run_id.clone());
        error
    })?;
    let run_deadline = config.clock.now() + config.poll_timeout;
    let run = poll_run(config, &run_id, run_deadline)?;
    let run_status = run
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("UNKNOWN")
        .to_owned();
    let dataset_id = run
        .get("defaultDatasetId")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .map(str::to_owned);
    let build_number = read_build_number(&run);
    let build_id = run
        .get("buildId")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let build_verified = build_number.as_deref() == Some(config.build_number.as_str())
        && build_id.as_deref() == Some(config.build_id.as_str());
    let mut terminal = created.clone();
    terminal.stage = "run_terminal".into();
    terminal.run_status = Some(run_status.clone());
    terminal.dataset_id = dataset_id.clone();
    terminal.build_number = build_number.clone();
    terminal.build_id = build_id.clone();
    terminal.build_verification = if build_verified {
        "verified"
    } else {
        "mismatch"
    }
    .into();
    config.journal.append(&terminal).map_err(|mut error| {
        error.run_id = Some(run_id.clone());
        error
    })?;
    if run_status != "SUCCEEDED" {
        let mut e = Error::new(
            ErrorKind::RunFailed,
            "run_poll",
            format!("Actor Run ended with status {run_status}"),
        )
        .with_run(run_id);
        if let Some(d) = dataset_id {
            e = e.with_dataset(d);
        }
        return Err(e);
    }
    if !build_verified {
        return Err(Error::new(
            ErrorKind::BuildMismatch,
            "build_verify",
            "Actor Build identity did not match the configured Build",
        )
        .with_run(run_id));
    }
    let dataset_id = dataset_id.ok_or_else(|| {
        Error::new(
            ErrorKind::Dataset,
            "run_poll",
            "successful Run did not include a Dataset ID",
        )
        .with_run(run_id.clone())
    })?;
    let page = get_dataset_page(config, &dataset_id, run_deadline).map_err(|mut error| {
        error.run_id = Some(run_id.clone());
        error.dataset_id = Some(dataset_id.clone());
        error
    })?;
    let association = attribute_single(&source, &page.items);
    let (status, text, segments, error) = if !page.complete {
        (
            Status::Unknown,
            None,
            Vec::new(),
            Some("Dataset reached the configured read limit and may be incomplete".to_owned()),
        )
    } else if page.items.is_empty() {
        (Status::Empty, None, Vec::new(), None)
    } else if association.verification != AttributionVerification::Verified
        || !association.extras.is_empty()
    {
        (
            Status::Unknown,
            None,
            Vec::new(),
            Some("Dataset items could not be uniquely attributed to the requested URL".to_owned()),
        )
    } else {
        let item = &association.matched[0];
        let err = item
            .get("errMsg")
            .and_then(Value::as_str)
            .filter(|s| !s.trim().is_empty());
        if let Some(message) = err {
            (
                Status::ActorError,
                None,
                Vec::new(),
                Some(crate::sanitize::diagnostic(message)),
            )
        } else {
            let text = item
                .get("text")
                .and_then(Value::as_str)
                .filter(|s| !s.trim().is_empty())
                .map(str::to_owned);
            match text {
                Some(t) => {
                    let segments = item
                        .get("segments")
                        .and_then(Value::as_array)
                        .cloned()
                        .unwrap_or_default();
                    (Status::Success, Some(t), segments, None)
                }
                None => (
                    Status::NoTranscript,
                    None,
                    Vec::new(),
                    Some("Dataset item did not contain transcript text".into()),
                ),
            }
        }
    };
    let mut result = TranscriptResult {
        status,
        run_id: Some(run_id),
        dataset_id: Some(dataset_id),
        source_url: source,
        text,
        segments,
        raw_items: page.items,
        error,
        stage: Some("dataset_classification".into()),
        build_number,
        build_id,
        build_verification: BuildVerification::Verified,
        attribution_verification: association.verification,
        dataset_complete: page.complete,
    };
    result.error = result.error.as_deref().map(crate::sanitize::diagnostic);
    let mut record = terminal;
    record.stage = "classified".into();
    record.build_verification = "verified".into();
    record.error = result.error.clone();
    config.journal.append(&record).map_err(|mut error| {
        error.run_id = Some(result.run_id.clone().unwrap_or_default());
        error.dataset_id = result.dataset_id.clone();
        error
    })?;
    Ok(result)
}

pub(crate) fn post_run(config: &Config, body: &Value) -> Result<Value> {
    let actor = encode_actor_id(&config.actor_id);
    let url = format!(
        "{API}/acts/{actor}/runs?build={}&maxTotalChargeUsd={}&restartOnError=false",
        percent_encode(&config.build_number),
        percent_encode(&config.charge_cap)
    );
    let mut req = Request::new(Method::POST, url);
    req.headers = bearer_headers(&config.token);
    let mut body = body.clone();
    if let Some(session) = &config.session_id {
        body["sessionid"] = Value::String(session.clone());
    }
    req.body = Some(body);
    let response = config.transport.send(&req).map_err(|_| {
        Error::new(
            ErrorKind::CreationUnknown,
            "run_create",
            "Actor Run creation result is unknown; do not retry automatically",
        )
    })?;
    if response.status == 307 || response.status == 308 || (500..600).contains(&response.status) {
        return Err(Error::new(
            ErrorKind::CreationUnknown,
            "run_create",
            format!(
                "Actor Run creation returned HTTP {}; do not retry",
                response.status
            ),
        ));
    }
    if (400..500).contains(&response.status) {
        return Err(Error::new(
            ErrorKind::CreateRejected,
            "run_create",
            format!("Actor rejected Run creation with HTTP {}", response.status),
        ));
    }
    if !(200..300).contains(&response.status) {
        return Err(Error::new(
            ErrorKind::CreationUnknown,
            "run_create",
            "unexpected create response; creation outcome is unknown",
        ));
    }
    let root: Value = serde_json::from_str(&response.body).map_err(|_| {
        Error::new(
            ErrorKind::CreationUnknown,
            "run_create",
            "create response was not valid JSON; creation outcome is unknown",
        )
    })?;
    root.get("data").cloned().ok_or_else(|| {
        Error::new(
            ErrorKind::CreationUnknown,
            "run_create",
            "create response did not contain run data; creation outcome is unknown",
        )
    })
}

pub(crate) fn poll_run(
    config: &Config,
    run_id: &str,
    deadline: std::time::Instant,
) -> Result<Value> {
    let mut delay = Duration::from_secs(1);
    loop {
        if config.clock.now() >= deadline {
            return Err(Error::new(
                ErrorKind::Transport,
                "run_poll",
                format!("polling timed out for runId {run_id}"),
            )
            .with_run(run_id.to_owned()));
        }
        let mut req = Request::new(
            Method::GET,
            format!("{API}/actor-runs/{}", percent_encode(run_id)),
        );
        req.headers = bearer_headers(&config.token);
        match config.transport.send(&req) {
            Err(_) => {
                config
                    .clock
                    .sleep(delay.min(deadline.saturating_duration_since(config.clock.now())));
                delay = (delay * 2).min(Duration::from_secs(30));
            }
            Ok(response) if response.status == 429 || (500..600).contains(&response.status) => {
                let retry = response
                    .headers
                    .get("retry-after")
                    .and_then(|s| s.parse::<u64>().ok())
                    .map(Duration::from_secs)
                    .unwrap_or(delay);
                config
                    .clock
                    .sleep(retry.min(deadline.saturating_duration_since(config.clock.now())));
                delay = (delay * 2).min(Duration::from_secs(30));
            }
            Ok(response) if !(200..300).contains(&response.status) => {
                return Err(Error::new(
                    ErrorKind::Transport,
                    "run_poll",
                    format!("Run polling returned HTTP {}", response.status),
                )
                .with_run(run_id.to_owned()))
            }
            Ok(response) => {
                let root: Value = serde_json::from_str(&response.body).map_err(|_| {
                    Error::new(
                        ErrorKind::Protocol,
                        "run_poll",
                        "Run response was not valid JSON",
                    )
                    .with_run(run_id.to_owned())
                })?;
                let run = root.get("data").cloned().ok_or_else(|| {
                    Error::new(ErrorKind::Protocol, "run_poll", "Run response omitted data")
                        .with_run(run_id.to_owned())
                })?;
                let status = run.get("status").and_then(Value::as_str).unwrap_or("");
                if matches!(status, "SUCCEEDED" | "FAILED" | "TIMED-OUT" | "ABORTED") {
                    return Ok(run);
                }
                let retry = response
                    .headers
                    .get("retry-after")
                    .and_then(|s| s.parse::<u64>().ok())
                    .map(Duration::from_secs)
                    .unwrap_or(delay);
                config
                    .clock
                    .sleep(retry.min(deadline.saturating_duration_since(config.clock.now())));
                delay = (delay * 2).min(Duration::from_secs(30));
            }
        }
    }
}

const MAX_DATASET_ATTEMPTS: usize = 4;
const EMPTY_DATASET_CONFIRMATIONS: usize = 2;

pub(crate) fn get_dataset_page(
    config: &Config,
    dataset_id: &str,
    deadline: std::time::Instant,
) -> Result<crate::dataset::DatasetPage> {
    let mut req = Request::new(
        Method::GET,
        format!(
            "{API}/datasets/{}/items?limit={}&offset=0",
            percent_encode(dataset_id),
            config.dataset_page_limit
        ),
    );
    req.headers = bearer_headers(&config.token);
    let mut attempts = 0;
    let mut empty_reads = 0;
    let mut backoff = Duration::from_secs(1);
    let mut empty_confirmation_delay = Duration::from_secs(1);

    loop {
        if attempts == MAX_DATASET_ATTEMPTS || config.clock.now() >= deadline {
            return Err(Error::new(
                ErrorKind::Dataset,
                "dataset_read",
                "Dataset could not be read or confirmed before the request budget/deadline",
            ));
        }
        attempts += 1;
        let response = match config.transport.send(&req) {
            Ok(response) => response,
            Err(error)
                if matches!(
                    error.kind,
                    crate::transport::TransportErrorKind::Timeout
                        | crate::transport::TransportErrorKind::Connection
                ) =>
            {
                if attempts == MAX_DATASET_ATTEMPTS
                    || !wait_before_dataset_retry(config, backoff, deadline)
                {
                    return Err(Error::new(
                        ErrorKind::Dataset,
                        "dataset_read",
                        "Dataset request failed after bounded network retries",
                    ));
                }
                backoff = (backoff * 2).min(Duration::from_secs(30));
                continue;
            }
            Err(_) => {
                return Err(Error::new(
                    ErrorKind::Dataset,
                    "dataset_read",
                    "Dataset request failed with a non-retryable transport error",
                ));
            }
        };

        if response.status == 429 || (500..600).contains(&response.status) {
            if attempts == MAX_DATASET_ATTEMPTS {
                return Err(Error::new(
                    ErrorKind::Dataset,
                    "dataset_read",
                    format!(
                        "Dataset request returned HTTP {} after bounded retries",
                        response.status
                    ),
                ));
            }
            let delay = response
                .headers
                .get("retry-after")
                .and_then(|value| value.trim().parse::<u64>().ok())
                .map(Duration::from_secs)
                .unwrap_or(backoff);
            if !wait_before_dataset_retry(config, delay, deadline) {
                return Err(Error::new(
                    ErrorKind::Dataset,
                    "dataset_read",
                    "Dataset retry delay exceeds the remaining deadline",
                ));
            }
            backoff = (backoff * 2).min(Duration::from_secs(30));
            continue;
        }
        if !(200..300).contains(&response.status) {
            return Err(Error::new(
                ErrorKind::Dataset,
                "dataset_read",
                format!(
                    "Dataset request returned non-retryable HTTP {}",
                    response.status
                ),
            ));
        }

        let page = parse_dataset(&response.body, config.dataset_page_limit)?;
        if !page.items.is_empty() {
            return Ok(page);
        }
        empty_reads += 1;
        if empty_reads > EMPTY_DATASET_CONFIRMATIONS {
            return Ok(page);
        }
        if attempts == MAX_DATASET_ATTEMPTS
            || !wait_before_dataset_retry(config, empty_confirmation_delay, deadline)
        {
            return Err(Error::new(
                ErrorKind::Dataset,
                "dataset_confirm",
                "Dataset remained empty but could not be confirmed within the request budget/deadline",
            ));
        }
        empty_confirmation_delay *= 2;
    }
}

fn wait_before_dataset_retry(
    config: &Config,
    delay: Duration,
    deadline: std::time::Instant,
) -> bool {
    let now = config.clock.now();
    if now >= deadline || delay >= deadline.saturating_duration_since(now) {
        return false;
    }
    config.clock.sleep(delay);
    config.clock.now() < deadline
}
pub(crate) fn read_build_number(run: &Value) -> Option<String> {
    run.get("buildNumber").map(|v| {
        if let Some(s) = v.as_str() {
            s.to_owned()
        } else {
            v.to_string()
        }
    })
}
fn percent_encode(s: &str) -> String {
    let mut out = String::new();
    for b in s.bytes() {
        if b.is_ascii_alphanumeric() || b"-_.~".contains(&b) {
            out.push(b as char)
        } else {
            out.push_str(&format!("%{b:02X}"));
        }
    }
    out
}
