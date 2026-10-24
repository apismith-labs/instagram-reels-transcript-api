//! Offline-testable native Bulk planning, execution, attribution, and result contract.
use crate::{
    config::Config,
    error::{Error, ErrorKind, Result},
    execute::{get_dataset_page, poll_run, post_run, read_build_number},
    journal::JournalRecord,
    sanitize::{diagnostic, redact_text, sanitize_value},
    status::BuildVerification,
    validators::validate_video_url,
};
use reqwest::Url;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    hash::{Hash, Hasher},
};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MediaType {
    Reel,
    Post,
}

#[derive(Clone, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Identity {
    pub media_type: MediaType,
    pub shortcode: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskStatus {
    Success,
    Empty,
    Unknown,
    Error,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Attribution {
    ExactUrl,
    TypedFallback,
    None,
    ConflictingEvidence,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExtraReason {
    Unmatched,
    Ambiguous,
    Duplicate,
    InvalidItem,
    ConflictingEvidence,
    TaskUnresolved,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BulkTaskResult {
    pub identity: Identity,
    pub source_indexes: Vec<usize>,
    pub source_urls: Vec<String>,
    pub status: TaskStatus,
    pub error_code: Option<String>,
    pub attribution: Attribution,
    pub raw_items: Vec<Value>,
    pub text: Option<String>,
    pub segments: Vec<Value>,
    pub error: Option<String>,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExtraItem {
    pub reason: ExtraReason,
    pub affected_task_indexes: Vec<usize>,
    pub raw_item: Value,
    pub diagnostic: Option<String>,
}

#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BulkCounts {
    pub success: usize,
    pub empty: usize,
    pub unknown: usize,
    pub error: usize,
    pub extra_items: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BatchStatus {
    Success,
    PartialSuccess,
    Empty,
    Unknown,
    Error,
    InputError,
    CreationUnknown,
    OutputError,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BulkResult {
    pub status: BatchStatus,
    pub error_code: Option<String>,
    pub error: Option<String>,
    pub run_id: Option<String>,
    pub dataset_id: Option<String>,
    pub run_status: Option<String>,
    pub build_number: Option<String>,
    pub build_id: Option<String>,
    pub build_verification: BuildVerification,
    pub dataset_complete: bool,
    /// Null means preflight did not produce a complete plan; otherwise this is its unique task count.
    pub planned_task_count: Option<usize>,
    pub counts: BulkCounts,
    pub results: Vec<BulkTaskResult>,
    pub extra_items: Vec<ExtraItem>,
}

impl BulkResult {
    pub fn exit_code(&self) -> i32 {
        match self.status {
            BatchStatus::Success | BatchStatus::Empty => 0,
            BatchStatus::PartialSuccess
            | BatchStatus::Unknown
            | BatchStatus::InputError
            | BatchStatus::OutputError => 2,
            BatchStatus::CreationUnknown => 10,
            BatchStatus::Error => match self.error_code.as_deref() {
                Some("create_rejected") => 4,
                Some("transport_error") => 8,
                Some("dataset_error" | "attribution_error" | "build_mismatch") => 7,
                Some("run_failed") => 9,
                Some("journal_error") => 2,
                _ => 1,
            },
        }
    }

    pub fn operation_error(
        code: &str,
        message: &str,
        planned: Option<usize>,
        run: Option<String>,
        dataset: Option<String>,
    ) -> Self {
        let status = match code {
            "input_error" => BatchStatus::InputError,
            "creation_unknown" => BatchStatus::CreationUnknown,
            "output_error" => BatchStatus::OutputError,
            "create_rejected" | "journal_error" | "transport_error" | "dataset_error"
            | "attribution_error" | "run_failed" | "build_mismatch" => BatchStatus::Error,
            _ => BatchStatus::Error,
        };
        Self {
            status,
            error_code: Some(code.into()),
            error: Some(diagnostic(message)),
            run_id: run,
            dataset_id: dataset,
            run_status: None,
            build_number: None,
            build_id: None,
            build_verification: BuildVerification::Unknown,
            dataset_complete: false,
            planned_task_count: planned,
            counts: BulkCounts::default(),
            results: vec![],
            extra_items: vec![],
        }
    }
}

#[derive(Clone, Default)]
pub struct BulkOptions {
    pub results_limit: Option<usize>,
    pub skip_pinned_posts: Option<bool>,
    pub include_shares_count: Option<bool>,
}

#[derive(Clone)]
pub struct PlannedTask {
    pub identity: Identity,
    pub source_indexes: Vec<usize>,
    pub source_urls: Vec<String>,
}

#[derive(Clone)]
pub struct BulkPlan {
    pub tasks: Vec<PlannedTask>,
    pub actor_urls: Vec<String>,
}

pub fn plan_bulk(urls: &[String]) -> Result<BulkPlan> {
    if urls.is_empty() {
        return Err(Error::new(
            ErrorKind::Input,
            "input_validation",
            "Native Bulk requires at least one URL",
        ));
    }
    let mut tasks: Vec<PlannedTask> = Vec::new();
    let mut by_identity: HashMap<Identity, usize> = HashMap::new();
    let mut parsed_all = Vec::with_capacity(urls.len());
    for raw in urls {
        let canonical = validate_video_url(raw)?;
        let (identity, normalized) = parse_valid_url(&canonical).expect("validated URL parses");
        parsed_all.push((identity, normalized));
    }
    for (source_index, (identity, _)) in parsed_all.iter().enumerate() {
        if let Some(index) = by_identity.get(identity).copied() {
            tasks[index].source_indexes.push(source_index);
            tasks[index].source_urls.push(urls[source_index].clone());
        } else {
            let index = tasks.len();
            by_identity.insert(identity.clone(), index);
            tasks.push(PlannedTask {
                identity: identity.clone(),
                source_indexes: vec![source_index],
                source_urls: vec![urls[source_index].clone()],
            });
        }
    }
    let actor_urls = tasks
        .iter()
        .map(|task| task.source_urls[0].clone())
        .collect();
    Ok(BulkPlan { tasks, actor_urls })
}

fn parse_valid_url(input: &str) -> Option<(Identity, String)> {
    let url = Url::parse(input).ok()?;
    let parts: Vec<_> = url.path().split('/').collect();
    let media_type = match *parts.get(1)? {
        "reel" | "reels" => MediaType::Reel,
        "p" => MediaType::Post,
        _ => return None,
    };
    let shortcode = parts.get(2)?.to_string();
    let kind = match media_type {
        MediaType::Reel => {
            if parts[1] == "reels" {
                "reels"
            } else {
                "reel"
            }
        }
        MediaType::Post => "p",
    };
    Some((
        Identity {
            media_type,
            shortcode: shortcode.clone(),
        },
        format!("https://instagram.com/{kind}/{shortcode}"),
    ))
}

pub(crate) fn execute_bulk(config: &Config, urls: &[String], options: BulkOptions) -> BulkResult {
    let plan = match plan_bulk(urls) {
        Ok(p) => p,
        Err(e) => return BulkResult::operation_error("input_error", &e.message, None, None, None),
    };
    let n = plan.tasks.len();
    if options.results_limit == Some(0) {
        return BulkResult::operation_error(
            "input_error",
            "resultsLimit must be a positive integer",
            Some(n),
            None,
            None,
        );
    }
    let input = actor_input(&plan, &options);
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    input.to_string().hash(&mut hasher);
    let intent = JournalRecord {
        stage: "intent".into(),
        mode: "native_bulk".into(),
        actor_id: config.actor_id.clone(),
        source_url: None,
        run_id: None,
        dataset_id: None,
        run_status: None,
        build_number: Some(config.build_number.clone()),
        build_id: Some(config.build_id.clone()),
        build_verification: "pending".into(),
        cap: Some(config.charge_cap.clone()),
        input_digest: Some(format!("{:016x}", hasher.finish())),
        context: Some(json!({"mode":"native_bulk","input":input})),
        error: None,
    };
    if let Err(e) = config.journal.append(&intent) {
        return BulkResult::operation_error("journal_error", &e.message, Some(n), None, None);
    }
    let post = match post_run(config, &input) {
        Ok(v) => v,
        Err(e) => {
            let code = if e.kind == ErrorKind::CreateRejected {
                "create_rejected"
            } else {
                "creation_unknown"
            };
            return BulkResult::operation_error(code, &e.message, Some(n), e.run_id, e.dataset_id);
        }
    };
    let run_id = match post
        .get("id")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
    {
        Some(v) => v.to_owned(),
        None => {
            return BulkResult::operation_error(
                "creation_unknown",
                "create response omitted Run ID; do not retry",
                Some(n),
                None,
                None,
            )
        }
    };
    let mut created = intent.clone();
    created.stage = "run_created".into();
    created.run_id = Some(run_id.clone());
    if config.journal.append(&created).is_err() {
        return BulkResult::operation_error(
            "journal_error",
            "could not persist Run-created journal record",
            Some(n),
            Some(run_id),
            None,
        );
    }
    let deadline = config.clock.now() + config.poll_timeout;
    let run = match poll_run(config, &run_id, deadline) {
        Ok(v) => v,
        Err(e) => {
            return BulkResult::operation_error(
                "transport_error",
                &e.message,
                Some(n),
                Some(run_id),
                None,
            )
        }
    };
    let run_status = run
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("UNKNOWN")
        .to_owned();
    let dataset_id = run
        .get("defaultDatasetId")
        .and_then(Value::as_str)
        .filter(|v| !v.is_empty())
        .map(str::to_owned);
    let build_number = read_build_number(&run);
    let build_id = run
        .get("buildId")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let build_matches = build_number.as_deref() == Some(config.build_number.as_str())
        && build_id.as_deref() == Some(config.build_id.as_str());
    let mut terminal = created.clone();
    terminal.stage = "run_terminal".into();
    terminal.run_status = Some(run_status.clone());
    terminal.dataset_id = dataset_id.clone();
    terminal.build_number = build_number.clone();
    terminal.build_id = build_id.clone();
    terminal.build_verification = if build_matches {
        "verified"
    } else {
        "mismatch"
    }
    .into();
    if config.journal.append(&terminal).is_err() {
        return BulkResult::operation_error(
            "journal_error",
            "could not persist terminal Run journal record",
            Some(n),
            Some(run_id),
            dataset_id,
        );
    }
    if run_status != "SUCCEEDED" {
        let mut result = blank_result(Some(n));
        result.status = BatchStatus::Error;
        result.error = Some(diagnostic(&format!(
            "Actor Run ended with status {run_status}"
        )));
        result.error_code = Some("run_failed".into());
        result.run_id = Some(run_id);
        result.dataset_id = dataset_id;
        result.run_status = Some(run_status);
        result.build_number = build_number;
        result.build_id = build_id;
        result.build_verification = if build_matches {
            BuildVerification::Verified
        } else {
            BuildVerification::Mismatch
        };
        result.results = plan
            .tasks
            .iter()
            .map(|t| task_error(t, "run_failed", Attribution::None, "Actor Run failed"))
            .collect();
        result.counts = counts_for(&result.results, &[]);
        return result;
    }
    if !build_matches {
        let mut result = blank_result(Some(n));
        result.status = BatchStatus::Error;
        result.error_code = Some("build_mismatch".into());
        result.error = Some("Actor Build identity did not match the configured Build".into());
        result.run_id = Some(run_id);
        result.dataset_id = dataset_id;
        result.run_status = Some(run_status);
        result.build_number = build_number;
        result.build_id = build_id;
        result.build_verification = BuildVerification::Mismatch;
        result.results = plan
            .tasks
            .iter()
            .map(|t| {
                task_error(
                    t,
                    "build_mismatch",
                    Attribution::None,
                    "Build identity mismatch",
                )
            })
            .collect();
        result.counts = counts_for(&result.results, &[]);
        return result;
    }
    let Some(dataset_id) = dataset_id else {
        return BulkResult::operation_error(
            "dataset_error",
            "successful Run omitted Dataset ID",
            Some(n),
            Some(run_id),
            None,
        );
    };
    let page = match get_dataset_page(config, &dataset_id, deadline) {
        Ok(p) => p,
        Err(e) => {
            return BulkResult::operation_error(
                "dataset_error",
                &e.message,
                Some(n),
                Some(run_id),
                Some(dataset_id),
            )
        }
    };
    let mut result = attribute_bulk(&plan, &page.items, page.complete);
    result.run_id = Some(run_id.clone());
    result.dataset_id = Some(dataset_id.clone());
    result.run_status = Some(run_status);
    result.build_number = build_number;
    result.build_id = build_id;
    result.build_verification = BuildVerification::Verified;
    result.dataset_complete = page.complete;
    let mut classified = terminal;
    classified.stage = "classified".into();
    classified.build_verification = "verified".into();
    if config.journal.append(&classified).is_err() {
        return BulkResult::operation_error(
            "journal_error",
            "could not persist classified journal record",
            Some(n),
            Some(run_id),
            Some(dataset_id),
        );
    }
    result
}

/// Resume an existing Native Bulk Run using GET requests only.
pub(crate) fn resume_bulk(config: &Config, run_id: &str, urls: &[String]) -> BulkResult {
    let plan = match plan_bulk(urls) {
        Ok(p) => p,
        Err(e) => {
            return BulkResult::operation_error(
                "input_error",
                &e.message,
                None,
                Some(run_id.into()),
                None,
            )
        }
    };
    let record = match config.journal.latest(run_id) {
        Ok(Some(r)) => r,
        Ok(None) => {
            return BulkResult::operation_error(
                "journal_error",
                "no journal record exists for this Run ID",
                Some(plan.tasks.len()),
                Some(run_id.into()),
                None,
            )
        }
        Err(e) => {
            return BulkResult::operation_error(
                "journal_error",
                &e.message,
                Some(plan.tasks.len()),
                Some(run_id.into()),
                None,
            )
        }
    };
    if record.run_id.as_deref() != Some(run_id) || record.mode != "native_bulk" {
        return BulkResult::operation_error(
            "journal_error",
            "journal mode or Run ID does not match Native Bulk resume",
            Some(plan.tasks.len()),
            Some(run_id.into()),
            None,
        );
    }
    let Some(context) = record.context.as_ref() else {
        return BulkResult::operation_error(
            "journal_error",
            "journal input is missing",
            Some(plan.tasks.len()),
            Some(run_id.into()),
            None,
        );
    };
    let input_context = context.get("inputContext").unwrap_or(context);
    let input = if input_context.get("mode").and_then(Value::as_str) == Some("native_bulk") {
        input_context.get("input").unwrap_or(&Value::Null)
    } else {
        context
    };
    let Some(input_object) = input.as_object() else {
        return BulkResult::operation_error(
            "journal_error",
            "journal Native Bulk input is incomplete",
            Some(plan.tasks.len()),
            Some(run_id.into()),
            None,
        );
    };
    if input_object.keys().any(|key| {
        ![
            "bulkUrls",
            "resultsLimit",
            "skipPinnedPosts",
            "includeSharesCount",
        ]
        .contains(&key.as_str())
    }) || input_object
        .get("resultsLimit")
        .is_some_and(|v| !v.as_u64().is_some_and(|n| n > 0))
        || input_object
            .get("skipPinnedPosts")
            .is_some_and(|v| !v.is_boolean())
        || input_object
            .get("includeSharesCount")
            .is_some_and(|v| !v.is_boolean())
    {
        return BulkResult::operation_error(
            "journal_error",
            "journal Native Bulk input contains unsupported or invalid fields",
            Some(plan.tasks.len()),
            Some(run_id.into()),
            None,
        );
    }
    let journal_urls: Vec<String> = input
        .get("bulkUrls")
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_default();
    if journal_urls != plan.actor_urls {
        return BulkResult::operation_error(
            "journal_error",
            "provided bulk URLs do not exactly match journal input",
            Some(plan.tasks.len()),
            Some(run_id.into()),
            None,
        );
    }
    let deadline = config.clock.now() + config.poll_timeout;
    let run = match poll_run(config, run_id, deadline) {
        Ok(v) => v,
        Err(e) => {
            return BulkResult::operation_error(
                "transport_error",
                &e.message,
                Some(plan.tasks.len()),
                Some(run_id.into()),
                None,
            )
        }
    };
    let run_status = run
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("UNKNOWN")
        .to_owned();
    let dataset_id = run
        .get("defaultDatasetId")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let build_number = read_build_number(&run);
    let build_id = run
        .get("buildId")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let verified = build_number.as_deref() == Some(config.build_number.as_str())
        && build_id.as_deref() == Some(config.build_id.as_str());
    let mut run_terminal = record;
    run_terminal.stage = "run_terminal".into();
    run_terminal.run_status = Some(run_status.clone());
    run_terminal.dataset_id = dataset_id.clone();
    run_terminal.build_number = build_number.clone();
    run_terminal.build_id = build_id.clone();
    run_terminal.build_verification = if verified {
        "verified"
    } else if build_number.is_some() || build_id.is_some() {
        "mismatch"
    } else {
        "unknown"
    }
    .into();
    run_terminal.error = if run_status != "SUCCEEDED" {
        Some(diagnostic(&format!(
            "Actor Run ended with status {run_status}"
        )))
    } else if !verified {
        Some(diagnostic(
            "Actor Build identity did not match the configured Build",
        ))
    } else {
        None
    };
    if let Err(e) = config.journal.append(&run_terminal) {
        return BulkResult::operation_error(
            "journal_error",
            &e.message,
            Some(plan.tasks.len()),
            Some(run_id.into()),
            dataset_id,
        );
    }
    if run_status != "SUCCEEDED" {
        return BulkResult::operation_error(
            "run_failed",
            &format!("Actor Run ended with status {run_status}"),
            Some(plan.tasks.len()),
            Some(run_id.into()),
            dataset_id,
        );
    }
    if !verified {
        return BulkResult::operation_error(
            "build_mismatch",
            "Actor Build identity did not match the configured Build",
            Some(plan.tasks.len()),
            Some(run_id.into()),
            dataset_id,
        );
    }
    let Some(dataset_id) = dataset_id else {
        return BulkResult::operation_error(
            "dataset_error",
            "successful Run omitted Dataset ID",
            Some(plan.tasks.len()),
            Some(run_id.into()),
            None,
        );
    };
    let page = match get_dataset_page(config, &dataset_id, deadline) {
        Ok(p) => p,
        Err(e) => {
            return BulkResult::operation_error(
                "dataset_error",
                &e.message,
                Some(plan.tasks.len()),
                Some(run_id.into()),
                Some(dataset_id),
            )
        }
    };
    let mut result = attribute_bulk(&plan, &page.items, page.complete);
    result.run_id = Some(run_id.into());
    result.dataset_id = Some(dataset_id.clone());
    result.run_status = Some(run_status.clone());
    result.build_number = build_number.clone();
    result.build_id = build_id.clone();
    result.build_verification = BuildVerification::Verified;
    result.dataset_complete = page.complete;
    let mut classified = run_terminal;
    classified.stage = "classified".into();
    classified.error = result.error.clone();
    if let Err(e) = config.journal.append(&classified) {
        return BulkResult::operation_error(
            "journal_error",
            &e.message,
            Some(plan.tasks.len()),
            Some(run_id.into()),
            Some(dataset_id),
        );
    }
    result
}

fn blank_result(planned: Option<usize>) -> BulkResult {
    BulkResult {
        status: BatchStatus::InputError,
        error_code: None,
        error: None,
        run_id: None,
        dataset_id: None,
        run_status: None,
        build_number: None,
        build_id: None,
        build_verification: BuildVerification::Unknown,
        dataset_complete: false,
        planned_task_count: planned,
        counts: BulkCounts::default(),
        results: vec![],
        extra_items: vec![],
    }
}
fn task_error(
    task: &PlannedTask,
    code: &str,
    attribution: Attribution,
    message: &str,
) -> BulkTaskResult {
    BulkTaskResult {
        identity: task.identity.clone(),
        source_indexes: task.source_indexes.clone(),
        source_urls: task.source_urls.clone(),
        status: TaskStatus::Error,
        error_code: Some(code.into()),
        attribution,
        raw_items: vec![],
        text: None,
        segments: vec![],
        error: Some(diagnostic(message)),
    }
}

#[derive(Clone)]
enum Evidence {
    Assigned(usize, Attribution),
    Extra(ExtraReason, Vec<usize>, Attribution, String),
}

pub(crate) fn attribute_bulk(plan: &BulkPlan, items: &[Value], complete: bool) -> BulkResult {
    let mut pending: Vec<Vec<(usize, Value, Attribution)>> = vec![Vec::new(); plan.tasks.len()];
    let mut forced_unknown: HashMap<usize, (Attribution, String)> = HashMap::new();
    let mut extras: Vec<ExtraItem> = Vec::new();
    for item in items {
        let evidence = identify_item(plan, item);
        match evidence {
            Evidence::Assigned(task, attr) => pending[task].push((0, sanitize_value(item), attr)),
            Evidence::Extra(reason, affected, attr, message) => {
                for index in &affected {
                    mark_forced_unknown(&mut forced_unknown, *index, attr, &message);
                }
                extras.push(ExtraItem {
                    reason,
                    affected_task_indexes: affected,
                    raw_item: sanitize_value(item),
                    diagnostic: Some(diagnostic(&message)),
                });
            }
        }
    }
    let mut unresolved_task_items = Vec::new();
    let mut rows = Vec::with_capacity(plan.tasks.len());
    for (index, task) in plan.tasks.iter().enumerate() {
        let candidates = &pending[index];
        if candidates.len() > 1 {
            let duplicate_attribution = duplicate_evidence_attribution(candidates);
            let (attribution, message) = forced_unknown.get(&index).cloned().unwrap_or((
                duplicate_attribution,
                "multiple Dataset items identify the same task".to_owned(),
            ));
            for (_, raw, _) in candidates {
                extras.push(ExtraItem {
                    reason: ExtraReason::Duplicate,
                    affected_task_indexes: vec![index],
                    raw_item: raw.clone(),
                    diagnostic: Some("multiple physical items identify one task".into()),
                });
            }
            rows.push(task_unknown(task, attribution, &message));
            continue;
        }
        if let Some((attr, message)) = forced_unknown.get(&index) {
            if let Some((_, raw, _)) = candidates.first() {
                unresolved_task_items.push(ExtraItem {
                    reason: ExtraReason::TaskUnresolved,
                    affected_task_indexes: vec![index],
                    raw_item: raw.clone(),
                    diagnostic: Some(
                        "previously attributable item belongs to an unresolved task".into(),
                    ),
                });
            }
            rows.push(task_unknown(task, *attr, message));
            continue;
        }
        if let Some((_, raw, attr)) = candidates.first() {
            let err = raw
                .get("errMsg")
                .and_then(Value::as_str)
                .filter(|s| !s.trim().is_empty());
            if let Some(message) = err {
                rows.push(task_from_item(
                    task,
                    raw,
                    *attr,
                    TaskStatus::Error,
                    Some("actor_error"),
                    Some(message),
                ));
            } else if let Some(text) = raw
                .get("text")
                .and_then(Value::as_str)
                .filter(|s| !s.trim().is_empty())
            {
                let mut row = task_from_item(task, raw, *attr, TaskStatus::Success, None, None);
                row.text = Some(redact_text(text));
                row.segments = raw
                    .get("segments")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default();
                rows.push(row);
            } else {
                rows.push(task_from_item(
                    task,
                    raw,
                    *attr,
                    TaskStatus::Error,
                    Some("no_transcript"),
                    Some("Dataset item did not contain transcript text"),
                ));
            }
        } else if complete {
            rows.push(task_empty(task));
        } else {
            rows.push(task_unknown(
                task,
                Attribution::None,
                "Dataset may be incomplete",
            ));
        }
    }
    extras.extend(unresolved_task_items);
    let counts = counts_for(&rows, &extras);
    let status = aggregate(&counts, rows.len(), complete, extras.len());
    BulkResult {
        status,
        error_code: None,
        error: None,
        run_id: None,
        dataset_id: None,
        run_status: None,
        build_number: None,
        build_id: None,
        build_verification: BuildVerification::Unknown,
        dataset_complete: complete,
        planned_task_count: Some(plan.tasks.len()),
        counts,
        results: rows,
        extra_items: extras,
    }
}

// Attribution reports the strongest evidence observed among all duplicate items.
// Exact URL evidence wins a mixed exact/typed-fallback group; otherwise the group
// is typed_fallback. This does not make duplicate data successful.
fn duplicate_evidence_attribution(candidates: &[(usize, Value, Attribution)]) -> Attribution {
    if candidates
        .iter()
        .any(|(_, _, attribution)| *attribution == Attribution::ExactUrl)
    {
        Attribution::ExactUrl
    } else {
        Attribution::TypedFallback
    }
}

fn task_from_item(
    task: &PlannedTask,
    raw: &Value,
    attribution: Attribution,
    status: TaskStatus,
    code: Option<&str>,
    message: Option<&str>,
) -> BulkTaskResult {
    BulkTaskResult {
        identity: task.identity.clone(),
        source_indexes: task.source_indexes.clone(),
        source_urls: task.source_urls.clone(),
        status,
        error_code: code.map(str::to_owned),
        attribution,
        raw_items: vec![raw.clone()],
        text: None,
        segments: vec![],
        error: message.map(diagnostic),
    }
}
fn task_unknown(task: &PlannedTask, attribution: Attribution, message: &str) -> BulkTaskResult {
    BulkTaskResult {
        identity: task.identity.clone(),
        source_indexes: task.source_indexes.clone(),
        source_urls: task.source_urls.clone(),
        status: TaskStatus::Unknown,
        error_code: Some("unknown".into()),
        attribution,
        raw_items: vec![],
        text: None,
        segments: vec![],
        error: Some(diagnostic(message)),
    }
}
fn task_empty(task: &PlannedTask) -> BulkTaskResult {
    BulkTaskResult {
        identity: task.identity.clone(),
        source_indexes: task.source_indexes.clone(),
        source_urls: task.source_urls.clone(),
        status: TaskStatus::Empty,
        error_code: None,
        attribution: Attribution::None,
        raw_items: vec![],
        text: None,
        segments: vec![],
        error: None,
    }
}

fn identify_item(plan: &BulkPlan, item: &Value) -> Evidence {
    if !item.is_object() {
        return Evidence::Extra(
            ExtraReason::InvalidItem,
            vec![],
            Attribution::None,
            "Dataset item is not an object".into(),
        );
    }
    let shortcode = ["shortCode", "shortcode", "short_code"]
        .iter()
        .find_map(|key| {
            item.get(*key)
                .and_then(Value::as_str)
                .filter(|s| !s.is_empty())
        });
    let explicit_media = item
        .get("mediaType")
        .or_else(|| item.get("media_type"))
        .and_then(Value::as_str)
        .and_then(|v| match v.to_ascii_lowercase().as_str() {
            "reel" | "reels" => Some(MediaType::Reel),
            "post" | "p" => Some(MediaType::Post),
            _ => None,
        });
    let raw_url = item
        .get("url")
        .and_then(Value::as_str)
        .filter(|v| !v.is_empty());
    if item
        .get("url")
        .is_some_and(|value| !value.is_null() && !value.is_string())
    {
        return Evidence::Extra(
            ExtraReason::InvalidItem,
            affected_tasks(plan, shortcode, explicit_media),
            Attribution::None,
            "Dataset item URL is not a string".into(),
        );
    }
    let url_identity = if let Some(url) = raw_url {
        match validate_video_url(url)
            .ok()
            .and_then(|v| parse_valid_url(&v))
        {
            Some(v) => Some(v),
            None => {
                return Evidence::Extra(
                    ExtraReason::InvalidItem,
                    affected_tasks(plan, shortcode, explicit_media),
                    Attribution::None,
                    "Dataset item URL is invalid".into(),
                )
            }
        }
    } else {
        None
    };
    let (url_typed, url_norm) = url_identity
        .as_ref()
        .map(|(id, url)| (Some(id), Some(url)))
        .unwrap_or((None, None));
    if let Some(url_id) = url_typed {
        let conflict = shortcode.is_some_and(|code| code != url_id.shortcode)
            || explicit_media.is_some_and(|media| media != url_id.media_type);
        let exact_matches: Vec<usize> = if let Some(norm) = url_norm {
            plan.tasks
                .iter()
                .enumerate()
                .filter(|(_, task)| {
                    task.source_urls.iter().any(|s| {
                        parse_valid_url(s).is_some_and(|(_, normalized)| &normalized == norm)
                    })
                })
                .map(|(i, _)| i)
                .collect()
        } else {
            vec![]
        };
        let code = shortcode.unwrap_or(url_id.shortcode.as_str());
        let media = explicit_media.unwrap_or(url_id.media_type);
        let typed_matches: Vec<usize> = plan
            .tasks
            .iter()
            .enumerate()
            .filter(|(_, task)| {
                task.identity.media_type == media && task.identity.shortcode == code
            })
            .map(|(index, _)| index)
            .collect();
        if conflict {
            let mut affected = exact_matches;
            for (index, task) in plan.tasks.iter().enumerate() {
                if task.identity == *url_id && !affected.contains(&index) {
                    affected.push(index);
                }
            }
            for i in typed_matches {
                if !affected.contains(&i) {
                    affected.push(i);
                }
            }
            if shortcode.is_some() && explicit_media.is_none() {
                for (i, t) in plan.tasks.iter().enumerate() {
                    if Some(t.identity.shortcode.as_str()) == shortcode && !affected.contains(&i) {
                        affected.push(i);
                    }
                }
            }
            affected.sort_unstable();
            return Evidence::Extra(
                ExtraReason::ConflictingEvidence,
                affected,
                Attribution::ConflictingEvidence,
                "Dataset URL and typed identity evidence conflict".into(),
            );
        }
        if exact_matches.len() == 1 {
            return Evidence::Assigned(exact_matches[0], Attribution::ExactUrl);
        }
        if exact_matches.len() > 1 {
            return Evidence::Extra(
                ExtraReason::Ambiguous,
                exact_matches,
                Attribution::None,
                "Valid item URL matches multiple input tasks".into(),
            );
        }
        if let [index] = typed_matches.as_slice() {
            return Evidence::Assigned(*index, Attribution::TypedFallback);
        }
        if typed_matches.len() > 1 {
            return Evidence::Extra(
                ExtraReason::Ambiguous,
                typed_matches,
                Attribution::None,
                "Validated URL identity is ambiguous".into(),
            );
        }
        return Evidence::Extra(
            ExtraReason::Unmatched,
            vec![],
            Attribution::None,
            "Valid item URL does not match an input task".into(),
        );
    }
    let Some(code) = shortcode else {
        return Evidence::Extra(
            ExtraReason::InvalidItem,
            vec![],
            Attribution::None,
            "Dataset item has no usable identity".into(),
        );
    };
    if let Some(media) = explicit_media {
        let matches: Vec<usize> = plan
            .tasks
            .iter()
            .enumerate()
            .filter(|(_, t)| t.identity.media_type == media && t.identity.shortcode == code)
            .map(|(i, _)| i)
            .collect();
        return match matches.as_slice() {
            [index] => Evidence::Assigned(*index, Attribution::TypedFallback),
            [] => Evidence::Extra(
                ExtraReason::Unmatched,
                vec![],
                Attribution::None,
                "Reliable typed identity does not match an input task".into(),
            ),
            _ => Evidence::Extra(
                ExtraReason::Ambiguous,
                matches,
                Attribution::None,
                "Typed identity is ambiguous".into(),
            ),
        };
    }
    let affected = plan
        .tasks
        .iter()
        .enumerate()
        .filter_map(|(i, t)| (t.identity.shortcode == code).then_some(i))
        .collect();
    Evidence::Extra(
        ExtraReason::Ambiguous,
        affected,
        Attribution::None,
        "Shortcode-only Dataset evidence cannot establish media type".into(),
    )
}

fn affected_tasks(
    plan: &BulkPlan,
    shortcode: Option<&str>,
    media: Option<MediaType>,
) -> Vec<usize> {
    plan.tasks
        .iter()
        .enumerate()
        .filter_map(|(index, task)| {
            let same_shortcode = shortcode == Some(task.identity.shortcode.as_str());
            let same_type = media.is_none_or(|value| value == task.identity.media_type);
            (same_shortcode && same_type).then_some(index)
        })
        .collect()
}

fn counts_for(rows: &[BulkTaskResult], extras: &[ExtraItem]) -> BulkCounts {
    let mut counts = BulkCounts::default();
    for row in rows {
        match row.status {
            TaskStatus::Success => counts.success += 1,
            TaskStatus::Empty => counts.empty += 1,
            TaskStatus::Unknown => counts.unknown += 1,
            TaskStatus::Error => counts.error += 1,
        }
    }
    counts.extra_items = extras.len();
    counts
}

fn mark_forced_unknown(
    states: &mut HashMap<usize, (Attribution, String)>,
    index: usize,
    attribution: Attribution,
    message: &str,
) {
    states
        .entry(index)
        .and_modify(|existing| {
            if existing.0 != Attribution::ConflictingEvidence
                || attribution == Attribution::ConflictingEvidence
            {
                *existing = (attribution, message.to_owned());
            }
        })
        .or_insert_with(|| (attribution, message.to_owned()));
}

fn aggregate(c: &BulkCounts, n: usize, complete: bool, extra_count: usize) -> BatchStatus {
    if n > 0
        && complete
        && extra_count == 0
        && c.unknown == 0
        && c.error == 0
        && c.success + c.empty == n
        && c.success > 0
    {
        return BatchStatus::Success;
    }
    if n > 0
        && complete
        && extra_count == 0
        && c.success == 0
        && c.unknown == 0
        && c.error == 0
        && c.empty == n
    {
        return BatchStatus::Empty;
    }
    if n > 0 && c.success == 0 && c.empty == 0 && c.unknown == 0 && c.error == n {
        return BatchStatus::Error;
    }
    if n > 0 && c.success == 0 && c.empty == 0 && c.unknown > 0 {
        return BatchStatus::Unknown;
    }
    if c.success + c.empty > 0 {
        return BatchStatus::PartialSuccess;
    }
    BatchStatus::Unknown
}

pub(crate) fn actor_input(plan: &BulkPlan, options: &BulkOptions) -> Value {
    let mut value = json!({"bulkUrls": plan.actor_urls});
    if let Some(v) = options.results_limit {
        value["resultsLimit"] = json!(v);
    }
    if let Some(v) = options.skip_pinned_posts {
        value["skipPinnedPosts"] = json!(v);
    }
    if let Some(v) = options.include_shares_count {
        value["includeSharesCount"] = json!(v);
    }
    value
}

#[cfg(test)]
mod tests;
