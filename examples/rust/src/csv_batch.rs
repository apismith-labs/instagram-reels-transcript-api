//! Pure CSV planning and sequential fail-closed execution.
use crate::{
    config::Config,
    error::ErrorKind,
    sanitize::{diagnostic, sanitize_value},
    status::TranscriptResult,
    validators::{validate_charge_cap, validate_video_url},
};
use serde::{Serialize, Serializer};
use serde_json::Value;
use std::{collections::HashMap, fmt};

const MAX_REQUESTED_CONCURRENCY: usize = 32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CsvRow {
    pub row_id: usize,
    pub source_url: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PlannedRow {
    pub row_id: usize,
    pub source_url: String,
    pub valid: bool,
    pub error: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CsvPlan {
    pub mode: String,
    pub rows: Vec<PlannedRow>,
    pub maximum_actor_runs: usize,
    pub concurrency: usize,
    pub actor_build: String,
    pub require_charge_cap: bool,
    pub per_run_cap_usd: Option<String>,
    pub estimated_maximum_run_caps_total_usd: Option<f64>,
    pub csv_path: Option<String>,
}

#[derive(Clone, Debug, Default)]
pub struct CsvExecuteOptions {
    pub concurrency: usize,
    pub csv_path: Option<String>,
}

#[derive(Clone)]
pub struct CsvRowResult {
    pub row_id: usize,
    pub source_url: String,
    pub status: String,
    pub run_id: Option<String>,
    pub dataset_id: Option<String>,
    pub result: Option<TranscriptResult>,
    pub error: Option<String>,
}

#[derive(Clone)]
pub struct CsvBatchResult {
    pub status: String,
    pub stopped: bool,
    pub planned_rows: usize,
    pub processed_rows: usize,
    pub unattempted_rows: Vec<usize>,
    pub concurrency: usize,
    pub counts: CsvCounts,
    pub rows: Vec<CsvRowResult>,
    pub raw_items: Vec<Value>,
    pub error: Option<String>,
}

#[derive(Clone, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CsvCounts {
    pub success: usize,
    pub failed: usize,
    pub unknown: usize,
    pub skipped: usize,
}

impl fmt::Debug for CsvBatchResult {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let json = serde_json::to_value(self)
            .map(|v| sanitize_value(&v))
            .unwrap_or(Value::Null);
        f.debug_tuple("CsvBatchResult").field(&json).finish()
    }
}

impl Serialize for CsvBatchResult {
    fn serialize<S>(&self, serializer: S) -> std::result::Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        #[derive(Serialize)]
        #[serde(rename_all = "camelCase")]
        struct Safe<'a> {
            status: &'a str,
            stopped: bool,
            planned_rows: usize,
            processed_rows: usize,
            unattempted_rows: &'a [usize],
            concurrency: usize,
            counts: &'a CsvCounts,
            rows: &'a [CsvRowResult],
            raw_items: &'a [Value],
            error: &'a Option<String>,
        }
        let value = serde_json::to_value(Safe {
            status: &self.status,
            stopped: self.stopped,
            planned_rows: self.planned_rows,
            processed_rows: self.processed_rows,
            unattempted_rows: &self.unattempted_rows,
            concurrency: self.concurrency,
            counts: &self.counts,
            rows: &self.rows,
            raw_items: &self.raw_items,
            error: &self.error,
        })
        .map_err(serde::ser::Error::custom)?;
        sanitize_value(&value).serialize(serializer)
    }
}

impl Serialize for CsvRowResult {
    fn serialize<S>(&self, serializer: S) -> std::result::Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        #[derive(Serialize)]
        #[serde(rename_all = "camelCase")]
        struct Safe<'a> {
            row_id: usize,
            source_url: &'a str,
            status: &'a str,
            run_id: &'a Option<String>,
            dataset_id: &'a Option<String>,
            result: &'a Option<TranscriptResult>,
            error: &'a Option<String>,
        }
        let v = serde_json::to_value(Safe {
            row_id: self.row_id,
            source_url: &self.source_url,
            status: &self.status,
            run_id: &self.run_id,
            dataset_id: &self.dataset_id,
            result: &self.result,
            error: &self.error,
        })
        .map_err(serde::ser::Error::custom)?;
        sanitize_value(&v).serialize(serializer)
    }
}

/// Parse a small RFC-4180-compatible CSV input, retaining physical source row numbers.
pub fn parse_csv(input: &str) -> crate::error::Result<Vec<CsvRow>> {
    let input = input.strip_prefix('\u{feff}').unwrap_or(input);
    let records = parse_records(input)?;
    let (header_line, headers) = records.first().ok_or_else(|| input_error("CSV is empty"))?;
    let url_column = headers
        .iter()
        .position(|v| v == "url" || v == "videourl")
        .ok_or_else(|| input_error("CSV requires a url or videoUrl header"))?;
    let mut rows = Vec::new();
    for (line, fields) in records.iter().skip(1) {
        if fields.iter().all(|v| v.trim().is_empty()) {
            continue;
        }
        let source_url = fields
            .get(url_column)
            .cloned()
            .ok_or_else(|| input_error(&format!("CSV row {line} is missing the URL column")))?;
        rows.push(CsvRow {
            row_id: *line.max(header_line),
            source_url,
        });
    }
    Ok(rows)
}

fn parse_records(input: &str) -> crate::error::Result<Vec<(usize, Vec<String>)>> {
    let mut records = Vec::new();
    let mut fields = Vec::new();
    let mut field = String::new();
    let mut quoted = false;
    let mut quote_closed = false;
    let mut chars = input.chars().peekable();
    let mut line = 1usize;
    let mut start = 1usize;
    while let Some(ch) = chars.next() {
        match ch {
            '"' if quoted && chars.peek() == Some(&'"') => {
                chars.next();
                field.push('"');
            }
            '"' if quoted => {
                quoted = false;
                quote_closed = true;
            }
            '"' if field.is_empty() && !quote_closed => quoted = true,
            '"' => return Err(input_error("CSV contains a quote in an unquoted field")),
            ',' if !quoted => {
                fields.push(std::mem::take(&mut field));
                quote_closed = false;
            }
            '\n' if !quoted => {
                fields.push(std::mem::take(&mut field));
                records.push((start, std::mem::take(&mut fields)));
                line += 1;
                start = line;
                quote_closed = false;
            }
            '\r' if !quoted => {
                if chars.peek() == Some(&'\n') {
                    chars.next();
                }
                fields.push(std::mem::take(&mut field));
                records.push((start, std::mem::take(&mut fields)));
                line += 1;
                start = line;
                quote_closed = false;
            }
            '\n' => {
                field.push(ch);
                line += 1;
            }
            _ if quote_closed => {
                return Err(input_error(
                    "CSV contains characters after a closing quote before the delimiter",
                ));
            }
            _ => field.push(ch),
        }
    }
    if quoted {
        return Err(input_error("CSV contains an unterminated quoted field"));
    }
    if !field.is_empty() || !fields.is_empty() {
        fields.push(field);
        records.push((start, fields));
    }
    if records.is_empty() {
        return Err(input_error("CSV is empty"));
    }
    let header = records[0]
        .1
        .iter()
        .map(|v| v.trim().to_ascii_lowercase())
        .collect();
    records[0].1 = header;
    Ok(records)
}

pub fn plan_csv(
    rows: &[CsvRow],
    csv_path: Option<String>,
    cap: Option<&str>,
    concurrency: usize,
) -> crate::error::Result<CsvPlan> {
    if concurrency == 0 || concurrency > MAX_REQUESTED_CONCURRENCY {
        return Err(input_error("concurrency must be between 1 and 32"));
    }
    let cap = cap.map(|c| validate_charge_cap(Some(c))).transpose()?;
    let planned: Vec<_> = rows
        .iter()
        .map(|row| match validate_video_url(&row.source_url) {
            Ok(_) => PlannedRow {
                row_id: row.row_id,
                source_url: row.source_url.clone(),
                valid: true,
                error: None,
            },
            Err(_) => PlannedRow {
                row_id: row.row_id,
                source_url: row.source_url.clone(),
                valid: false,
                error: Some("invalid Instagram URL".into()),
            },
        })
        .collect();
    let maximum_actor_runs = planned.iter().filter(|r| r.valid).count();
    let estimated_maximum_run_caps_total_usd = cap
        .as_deref()
        .and_then(|s| s.parse::<f64>().ok())
        .map(|v| v * maximum_actor_runs as f64);
    Ok(CsvPlan {
        mode: "plan".into(),
        rows: planned,
        maximum_actor_runs,
        concurrency: 1,
        actor_build: crate::config::EXPECTED_BUILD_NUMBER.into(),
        require_charge_cap: true,
        per_run_cap_usd: cap,
        estimated_maximum_run_caps_total_usd,
        csv_path,
    })
}

pub fn run_csv(config: &Config, rows: &[CsvRow], _options: CsvExecuteOptions) -> CsvBatchResult {
    let planned_rows = rows.len();
    let concurrency = 1usize;
    let prior_outcomes = match config.journal.all() {
        Ok(records) => {
            let mut latest = HashMap::new();
            for record in records.into_iter().filter(|r| r.mode == "csv") {
                let identity = match context_csv_identity(record.context.as_ref()) {
                    Ok(identity) => identity,
                    Err(()) => {
                        return stopped_result(
                            planned_rows,
                            concurrency,
                            rows.iter().map(|r| r.row_id).collect(),
                            "CSV Journal contains an incomplete or malformed row identity".into(),
                        )
                    }
                };
                latest.insert(identity, record);
            }
            latest
        }
        Err(error) => {
            return stopped_result(
                planned_rows,
                concurrency,
                rows.iter().map(|r| r.row_id).collect(),
                error.message,
            )
        }
    };
    let mut counts = CsvCounts::default();
    let mut output_rows = Vec::new();
    let mut unattempted_rows = Vec::new();
    let mut stopped = false;
    let mut batch_error = None;
    let mut stop_status: Option<&str> = None;
    let mut raw_items = Vec::new();
    for (index, row) in rows.iter().enumerate() {
        let normalized_url =
            validate_video_url(&row.source_url).unwrap_or_else(|_| row.source_url.clone());
        let exact_identity = (Some(row.row_id), normalized_url.clone());
        let legacy_identity = (None, normalized_url);
        if prior_outcomes
            .get(&exact_identity)
            .is_some_and(|record| record.stage == "classified_success")
        {
            counts.skipped += 1;
            output_rows.push(CsvRowResult {
                row_id: row.row_id,
                source_url: row.source_url.clone(),
                status: "skipped_existing_success".into(),
                run_id: None,
                dataset_id: None,
                result: None,
                error: None,
            });
            continue;
        }
        // An intent without a safe terminal classification can mean the process
        // stopped around the create POST. Do not create a second Run for it.
        if let Some(prior) = prior_outcomes
            .get(&exact_identity)
            .or_else(|| prior_outcomes.get(&legacy_identity))
            .filter(|prior| {
                matches!(
                    prior.stage.as_str(),
                    "intent" | "run_created" | "run_terminal" | "creation_unknown"
                )
            })
        {
            counts.unknown += 1;
            stopped = true;
            stop_status = Some("creation_unknown");
            batch_error = Some(
                "prior CSV Run state is incomplete; reconcile the existing Run before retrying"
                    .into(),
            );
            output_rows.push(CsvRowResult {
                row_id: row.row_id,
                source_url: row.source_url.clone(),
                status: "creation_unknown".into(),
                run_id: prior.run_id.clone(),
                dataset_id: prior.dataset_id.clone(),
                result: None,
                error: batch_error.clone(),
            });
            unattempted_rows.extend(rows.iter().skip(index + 1).map(|r| r.row_id));
            break;
        }
        match crate::execute::get_csv_transcript(config, &row.source_url, row.row_id) {
            Ok(result) => {
                let status = serde_json::to_value(result.status)
                    .ok()
                    .and_then(|v| v.as_str().map(str::to_owned))
                    .unwrap_or_else(|| "unknown".into());
                if result.status == crate::status::Status::Success {
                    counts.success += 1;
                } else {
                    counts.failed += 1;
                }
                raw_items.extend(result.raw_items.iter().cloned());
                output_rows.push(CsvRowResult {
                    row_id: row.row_id,
                    source_url: row.source_url.clone(),
                    status,
                    run_id: result.run_id.clone(),
                    dataset_id: result.dataset_id.clone(),
                    result: Some(result),
                    error: None,
                });
            }
            Err(error) => {
                let global_stop =
                    matches!(error.kind, ErrorKind::CreationUnknown | ErrorKind::Journal);
                if global_stop {
                    if error.kind == ErrorKind::Journal {
                        counts.failed += 1;
                    } else {
                        counts.unknown += 1;
                    }
                    stopped = true;
                    batch_error = Some(diagnostic(&error.message));
                    stop_status = Some(if error.kind == ErrorKind::Journal {
                        "journal_error"
                    } else {
                        "creation_unknown"
                    });
                } else {
                    counts.failed += 1;
                }
                let row_status = if global_stop && error.kind == ErrorKind::Journal {
                    "journal_error".to_owned()
                } else if global_stop {
                    "creation_unknown".to_owned()
                } else {
                    format!("{:?}", error.kind).to_ascii_lowercase()
                };
                output_rows.push(CsvRowResult {
                    row_id: row.row_id,
                    source_url: row.source_url.clone(),
                    status: row_status,
                    run_id: error.run_id.clone(),
                    dataset_id: error.dataset_id.clone(),
                    result: None,
                    error: Some(diagnostic(&error.message)),
                });
                if global_stop {
                    unattempted_rows.extend(rows.iter().skip(index + 1).map(|r| r.row_id));
                    break;
                }
            }
        }
    }
    let status = stop_status.unwrap_or({
        if counts.failed == 0 && counts.unknown == 0 {
            "success"
        } else if counts.success > 0 {
            "partial_success"
        } else {
            "all_failed"
        }
    });
    CsvBatchResult {
        status: status.into(),
        stopped,
        planned_rows,
        processed_rows: output_rows.len(),
        unattempted_rows,
        concurrency,
        counts,
        rows: output_rows,
        raw_items,
        error: batch_error,
    }
}

fn context_csv_identity(
    context: Option<&Value>,
) -> std::result::Result<(Option<usize>, String), ()> {
    let context = context.ok_or(())?;
    let input_context = context.get("inputContext").unwrap_or(context);
    if input_context
        .get("mode")
        .is_some_and(|mode| mode.as_str() != Some("csv"))
    {
        return Err(());
    }
    let input = input_context
        .get("input")
        .and_then(Value::as_object)
        .ok_or(())?;
    let url = input
        .get("videoUrl")
        .and_then(Value::as_str)
        .filter(|url| !url.trim().is_empty())
        .ok_or(())?;
    let normalized_url = validate_video_url(url).map_err(|_| ())?;
    let row_id = match input.get("rowId") {
        None => None,
        Some(value) => {
            let value = value.as_u64().ok_or(())?;
            Some(usize::try_from(value).map_err(|_| ())?)
        }
    };
    Ok((row_id, normalized_url))
}
fn stopped_result(
    planned: usize,
    concurrency: usize,
    unattempted_rows: Vec<usize>,
    error: String,
) -> CsvBatchResult {
    CsvBatchResult {
        status: "journal_error".into(),
        stopped: true,
        planned_rows: planned,
        processed_rows: 0,
        unattempted_rows,
        concurrency,
        counts: CsvCounts::default(),
        rows: vec![],
        raw_items: vec![],
        error: Some(diagnostic(&error)),
    }
}
fn input_error(message: &str) -> crate::error::Error {
    crate::error::Error::new(ErrorKind::Input, "csv_plan", message)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        journal::{InMemoryJournal, Journal, JournalRecord},
        transport::{Request, Response, Transport, TransportError, TransportErrorKind},
        Config, Error,
    };
    use reqwest::Method;
    use serde_json::json;
    use std::sync::{
        atomic::{AtomicUsize, Ordering},
        Arc, Mutex,
    };

    struct Fake {
        responses: Mutex<Vec<std::result::Result<Response, TransportError>>>,
        posts: AtomicUsize,
    }
    impl Transport for Fake {
        fn send(&self, req: &Request) -> std::result::Result<Response, TransportError> {
            if req.method == Method::POST {
                self.posts.fetch_add(1, Ordering::SeqCst);
            }
            self.responses.lock().unwrap().remove(0)
        }
        fn guarantees_single_shot_post(&self) -> bool {
            true
        }
    }
    fn successful_responses(url: &str) -> Vec<std::result::Result<Response, TransportError>> {
        vec![
            Ok(Response::json(201, json!({"data":{"id":"csv-run"}}))),
            Ok(Response::json(
                200,
                json!({"data":{"status":"SUCCEEDED","defaultDatasetId":"csv-dataset","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}),
            )),
            Ok(Response::json(200, json!([{ "url":url, "text":"ok"}]))),
        ]
    }
    fn config(fake: Arc<Fake>, journal: Arc<InMemoryJournal>) -> Config {
        Config::builder()
            .token("synthetic")
            .max_total_charge_usd("0.10")
            .transport(fake)
            .journal(journal)
            .build()
            .unwrap()
    }
    fn csv_record(stage: &str, row_id: Option<usize>, url: &str) -> JournalRecord {
        let mut input = json!({"videoUrl":url});
        if let Some(row_id) = row_id {
            input["rowId"] = json!(row_id);
        }
        JournalRecord {
            stage: stage.into(),
            mode: "csv".into(),
            actor_id: "synthetic-actor".into(),
            source_url: Some(url.into()),
            run_id: Some("prior-csv-run".into()),
            dataset_id: Some("prior-csv-dataset".into()),
            run_status: None,
            build_number: Some("0.0.50".into()),
            build_id: Some("aJLRmMdQapLQRT4sJ".into()),
            build_verification: "pending".into(),
            cap: Some("0.10".into()),
            input_digest: None,
            context: Some(json!({"mode":"csv","input":input})),
            error: None,
        }
    }
    struct FaultJournal {
        records: Mutex<Vec<JournalRecord>>,
        fail_stage: Option<String>,
        fail_row_id: usize,
        fail_all: bool,
    }
    impl FaultJournal {
        fn new(fail_stage: Option<&str>, fail_row_id: usize) -> Self {
            Self {
                records: Mutex::new(Vec::new()),
                fail_stage: fail_stage.map(str::to_owned),
                fail_row_id,
                fail_all: false,
            }
        }
        fn all_failure() -> Self {
            Self {
                records: Mutex::new(Vec::new()),
                fail_stage: None,
                fail_row_id: 0,
                fail_all: true,
            }
        }
        fn row_id(record: &JournalRecord) -> Option<usize> {
            record
                .context
                .as_ref()?
                .get("input")?
                .get("rowId")?
                .as_u64()
                .and_then(|id| usize::try_from(id).ok())
        }
    }
    impl Journal for FaultJournal {
        fn append(&self, record: &JournalRecord) -> crate::error::Result<()> {
            if self.fail_stage.as_deref() == Some(record.stage.as_str())
                && Self::row_id(record) == Some(self.fail_row_id)
            {
                let error = Error::new(
                    ErrorKind::Journal,
                    "journal_test",
                    "synthetic Journal append failure",
                );
                return Err(match record.run_id.as_deref() {
                    Some(run_id) => error.with_run(run_id),
                    None => error,
                });
            }
            self.records.lock().unwrap().push(record.clone());
            Ok(())
        }
        fn latest(&self, run_id: &str) -> crate::error::Result<Option<JournalRecord>> {
            Ok(self
                .records
                .lock()
                .unwrap()
                .iter()
                .rev()
                .find(|record| record.run_id.as_deref() == Some(run_id))
                .cloned())
        }
        fn all(&self) -> crate::error::Result<Vec<JournalRecord>> {
            if self.fail_all {
                return Err(Error::new(
                    ErrorKind::Journal,
                    "journal_test",
                    "synthetic Journal read failure",
                ));
            }
            Ok(self.records.lock().unwrap().clone())
        }
    }
    #[test]
    fn csv_plan_is_pure_and_preserves_duplicate_rows() {
        let rows = parse_csv("\u{feff}videoUrl,name\r\nhttps://instagram.com/reel/a/,one\r\n\r\nhttps://instagram.com/reel/a/,two\r\n").unwrap();
        assert_eq!(rows.len(), 2);
        assert_ne!(rows[0].row_id, rows[1].row_id);
        let plan = plan_csv(&rows, None, Some("0.10"), 5).unwrap();
        assert_eq!(plan.maximum_actor_runs, 2);
        assert_eq!(plan.concurrency, 1);
        assert_eq!(plan.estimated_maximum_run_caps_total_usd, Some(0.2));
    }
    #[test]
    fn csv_rejects_missing_header_and_unclosed_quote() {
        assert!(parse_csv("name\na\n").is_err());
        assert!(parse_csv("url\n\"https://x").is_err());
        assert!(parse_csv("url\nnot\"quoted\n").is_err());
        assert!(parse_csv("url\n\"closed\"tail\n").is_err());
    }

    #[test]
    fn csv_parser_keeps_multiline_quoted_fields_and_physical_row_identity() {
        let rows = parse_csv("name,url\n\"first\nsecond\",https://instagram.com/reel/a\n\nhttps://instagram.com/reel/b,\n").unwrap();
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0].row_id, 2);
        assert_eq!(rows[0].source_url, "https://instagram.com/reel/a");
        assert_eq!(rows[1].row_id, 5);
    }

    #[test]
    fn csv_plan_rejects_zero_concurrency_and_invalid_charge_cap() {
        let rows = vec![CsvRow {
            row_id: 2,
            source_url: "https://instagram.com/reel/a".into(),
        }];
        assert!(plan_csv(&rows, None, Some("0"), 1).is_err());
        assert!(plan_csv(&rows, None, Some("0.10"), 0).is_err());
        assert!(plan_csv(&rows, None, Some("0.10"), 33).is_err());
    }
    #[test]
    fn csv_plan_marks_invalid_rows_without_network_or_credentials() {
        let rows = vec![CsvRow {
            row_id: 2,
            source_url: "not-url".into(),
        }];
        let plan = plan_csv(&rows, None, None, 1).unwrap();
        assert_eq!(
            plan.maximum_actor_runs, 0,
            "invalid rows must not be counted as billable Runs"
        );
        assert!(!plan.rows[0].valid);
    }

    #[test]
    fn csv_plan_counts_only_independently_valid_rows() {
        let rows = vec![
            CsvRow {
                row_id: 2,
                source_url: "https://instagram.com/reel/a".into(),
            },
            CsvRow {
                row_id: 3,
                source_url: "not-a-url".into(),
            },
            CsvRow {
                row_id: 4,
                source_url: "https://instagram.com/p/b".into(),
            },
        ];
        let plan = plan_csv(&rows, None, Some("0.10"), 1).unwrap();
        assert_eq!(
            plan.maximum_actor_runs, 2,
            "invalid rows must not be counted as billable Runs"
        );
        assert_eq!(plan.estimated_maximum_run_caps_total_usd, Some(0.20));
        assert_eq!(plan.rows.iter().filter(|r| r.valid).count(), 2);
    }

    #[test]
    fn csv_creation_unknown_stops_before_scheduling_later_rows() {
        let mut responses = vec![Err(TransportError::new(TransportErrorKind::Timeout))];
        responses.extend(successful_responses("https://instagram.com/reel/b"));
        let fake = Arc::new(Fake {
            responses: Mutex::new(responses),
            posts: AtomicUsize::new(0),
        });
        let rows = vec![
            CsvRow {
                row_id: 2,
                source_url: "https://instagram.com/reel/a".into(),
            },
            CsvRow {
                row_id: 3,
                source_url: "https://instagram.com/reel/b".into(),
            },
        ];
        let journal = Arc::new(InMemoryJournal::default());
        let cfg = config(fake.clone(), journal);
        let result = run_csv(&cfg, &rows, CsvExecuteOptions::default());
        assert!(
            result.stopped,
            "creation_unknown must stop later CSV scheduling"
        );
        assert_eq!(result.status, "creation_unknown");
        assert_eq!(result.unattempted_rows, [3]);
        assert_eq!(fake.posts.load(Ordering::SeqCst), 1);
        let retry = run_csv(&cfg, &rows, CsvExecuteOptions::default());
        assert_eq!(retry.status, "creation_unknown");
        assert_eq!(retry.unattempted_rows, [3]);
        assert_eq!(
            fake.posts.load(Ordering::SeqCst),
            1,
            "a later invocation must not recreate an uncertain Run"
        );
    }

    #[test]
    fn csv_success_is_not_recreated_on_a_later_batch_retry() {
        let url = "https://instagram.com/reel/a";
        let fake = Arc::new(Fake {
            responses: Mutex::new(successful_responses(url)),
            posts: AtomicUsize::new(0),
        });
        let journal = Arc::new(InMemoryJournal::default());
        let cfg = config(fake.clone(), journal);
        let rows = vec![CsvRow {
            row_id: 2,
            source_url: url.into(),
        }];
        let first = run_csv(&cfg, &rows, CsvExecuteOptions::default());
        assert_eq!(first.counts.success, 1);
        assert_eq!(fake.posts.load(Ordering::SeqCst), 1);
        let second = run_csv(&cfg, &rows, CsvExecuteOptions::default());
        assert_eq!(second.counts.skipped, 1);
        assert_eq!(fake.posts.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn csv_duplicate_rows_remain_distinct_and_success_is_skipped_by_row_id() {
        let url = "https://instagram.com/reel/duplicate";
        let mut responses = successful_responses(url);
        responses.extend(successful_responses(url));
        let fake = Arc::new(Fake {
            responses: Mutex::new(responses),
            posts: AtomicUsize::new(0),
        });
        let journal = Arc::new(InMemoryJournal::default());
        let cfg = config(fake.clone(), journal);
        let rows = vec![
            CsvRow {
                row_id: 2,
                source_url: url.into(),
            },
            CsvRow {
                row_id: 3,
                source_url: url.into(),
            },
        ];
        let first = run_csv(&cfg, &rows, CsvExecuteOptions::default());
        assert_eq!(
            first.counts.success, 2,
            "duplicate CSV rows are separate billable tasks"
        );
        assert_eq!(fake.posts.load(Ordering::SeqCst), 2);
        let second = run_csv(&cfg, &rows, CsvExecuteOptions::default());
        assert_eq!(second.counts.skipped, 2);
        assert_eq!(
            fake.posts.load(Ordering::SeqCst),
            2,
            "each successful row ID must be idempotently skipped"
        );
    }

    #[test]
    fn csv_prior_run_states_stop_without_reposting_and_preserve_run_identity() {
        for stage in ["intent", "run_created", "run_terminal", "creation_unknown"] {
            let url = "https://instagram.com/reel/prior";
            let journal = Arc::new(InMemoryJournal::default());
            journal.append(&csv_record(stage, Some(2), url)).unwrap();
            let rows = vec![
                CsvRow {
                    row_id: 2,
                    source_url: url.into(),
                },
                CsvRow {
                    row_id: 3,
                    source_url: "https://instagram.com/reel/later".into(),
                },
            ];
            let responses = rows
                .iter()
                .flat_map(|row| successful_responses(&row.source_url))
                .collect();
            let fake = Arc::new(Fake {
                responses: Mutex::new(responses),
                posts: AtomicUsize::new(0),
            });
            let cfg = config(fake.clone(), journal);
            let result = run_csv(&cfg, &rows, CsvExecuteOptions::default());
            assert_eq!(
                result.status, "creation_unknown",
                "unresolved prior CSV state must block replay without creating a new Run"
            );
            assert!(result.stopped);
            assert_eq!(result.rows[0].status, "creation_unknown");
            assert_eq!(result.rows[0].run_id.as_deref(), Some("prior-csv-run"));
            assert_eq!(
                result.rows[0].dataset_id.as_deref(),
                Some("prior-csv-dataset")
            );
            assert_eq!(result.unattempted_rows, [3]);
            assert_eq!(
                fake.posts.load(Ordering::SeqCst),
                0,
                "prior {stage} must not create another Run"
            );
        }
    }

    #[test]
    fn csv_classified_success_skips_only_exact_row_and_url_identity() {
        for (prior_row, prior_url, current_row, current_url) in [
            (
                2,
                "https://instagram.com/reel/a",
                2,
                "https://instagram.com/reel/b",
            ),
            (
                2,
                "https://instagram.com/reel/a",
                3,
                "https://instagram.com/reel/a",
            ),
        ] {
            let journal = Arc::new(InMemoryJournal::default());
            journal
                .append(&csv_record(
                    "classified_success",
                    Some(prior_row),
                    prior_url,
                ))
                .unwrap();
            let fake = Arc::new(Fake {
                responses: Mutex::new(successful_responses(current_url)),
                posts: AtomicUsize::new(0),
            });
            let cfg = config(fake.clone(), journal);
            let result = run_csv(
                &cfg,
                &[CsvRow {
                    row_id: current_row,
                    source_url: current_url.into(),
                }],
                CsvExecuteOptions::default(),
            );
            assert_eq!(
                result.counts.success, 1,
                "non-identical journal identity must not be skipped"
            );
            assert_eq!(fake.posts.load(Ordering::SeqCst), 1);
        }
        let url = "https://instagram.com/reel/exact";
        let journal = Arc::new(InMemoryJournal::default());
        journal
            .append(&csv_record("classified_success", Some(2), url))
            .unwrap();
        let fake = Arc::new(Fake {
            responses: Mutex::new(vec![]),
            posts: AtomicUsize::new(0),
        });
        let cfg = config(fake.clone(), journal);
        let result = run_csv(
            &cfg,
            &[CsvRow {
                row_id: 2,
                source_url: url.into(),
            }],
            CsvExecuteOptions::default(),
        );
        assert_eq!(result.counts.skipped, 1);
        assert_eq!(fake.posts.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn csv_legacy_success_is_not_fuzzy_skipped_and_legacy_pending_blocks() {
        let url = "https://instagram.com/reel/legacy";
        let journal = Arc::new(InMemoryJournal::default());
        journal
            .append(&csv_record("classified_success", None, url))
            .unwrap();
        let fake = Arc::new(Fake {
            responses: Mutex::new(successful_responses(url)),
            posts: AtomicUsize::new(0),
        });
        let cfg = config(fake.clone(), journal);
        let result = run_csv(
            &cfg,
            &[CsvRow {
                row_id: 2,
                source_url: url.into(),
            }],
            CsvExecuteOptions::default(),
        );
        assert_eq!(
            result.counts.success, 1,
            "legacy success without rowId must not fuzzy skip a new row"
        );
        assert_eq!(fake.posts.load(Ordering::SeqCst), 1);

        let journal = Arc::new(InMemoryJournal::default());
        journal.append(&csv_record("intent", None, url)).unwrap();
        let fake = Arc::new(Fake {
            responses: Mutex::new(vec![]),
            posts: AtomicUsize::new(0),
        });
        let cfg = config(fake.clone(), journal);
        let result = run_csv(
            &cfg,
            &[CsvRow {
                row_id: 2,
                source_url: url.into(),
            }],
            CsvExecuteOptions::default(),
        );
        assert_eq!(result.status, "creation_unknown");
        assert_eq!(fake.posts.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn csv_malformed_prior_journal_fails_closed_before_any_post() {
        let journal = Arc::new(InMemoryJournal::default());
        let mut malformed = csv_record("intent", Some(2), "https://instagram.com/reel/a");
        malformed.context = None;
        journal.append(&malformed).unwrap();
        let fake = Arc::new(Fake {
            responses: Mutex::new(vec![]),
            posts: AtomicUsize::new(0),
        });
        let cfg = config(fake.clone(), journal);
        let result = run_csv(
            &cfg,
            &[CsvRow {
                row_id: 2,
                source_url: "https://instagram.com/reel/a".into(),
            }],
            CsvExecuteOptions::default(),
        );
        assert_eq!(result.status, "journal_error");
        assert!(result.stopped);
        assert_eq!(result.unattempted_rows, [2]);
        assert_eq!(fake.posts.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn csv_journal_write_failures_stop_before_later_rows() {
        let rows = vec![
            CsvRow {
                row_id: 2,
                source_url: "https://instagram.com/reel/first".into(),
            },
            CsvRow {
                row_id: 3,
                source_url: "https://instagram.com/reel/fault".into(),
            },
            CsvRow {
                row_id: 4,
                source_url: "https://instagram.com/reel/never".into(),
            },
        ];
        for (failed_stage, expected_posts, expected_run_id) in [
            ("intent", 1, None),
            ("run_created", 2, Some("csv-run")),
            ("run_terminal", 2, Some("csv-run")),
        ] {
            let responses = rows
                .iter()
                .flat_map(|row| successful_responses(&row.source_url))
                .collect();
            let fake = Arc::new(Fake {
                responses: Mutex::new(responses),
                posts: AtomicUsize::new(0),
            });
            let journal = Arc::new(FaultJournal::new(Some(failed_stage), 3));
            let cfg = Config::builder()
                .token("synthetic")
                .max_total_charge_usd("0.10")
                .transport(fake.clone())
                .journal(journal)
                .build()
                .unwrap();
            let result = run_csv(&cfg, &rows, CsvExecuteOptions::default());
            assert!(
                result.stopped,
                "Journal failure must stop the whole CSV batch ({failed_stage})"
            );
            assert_eq!(
                result.status, "journal_error",
                "Journal failure must stop the whole CSV batch"
            );
            assert_eq!(result.unattempted_rows, [4]);
            assert_eq!(result.rows[0].status, "success");
            assert_eq!(result.rows[1].status, "journal_error");
            assert_eq!(result.rows[1].run_id.as_deref(), expected_run_id);
            assert_eq!(
                fake.posts.load(Ordering::SeqCst),
                expected_posts,
                "{failed_stage} append has a fixed POST count"
            );
        }
    }

    #[test]
    fn csv_journal_read_failure_stops_before_any_row_is_scheduled() {
        let fake = Arc::new(Fake {
            responses: Mutex::new(vec![]),
            posts: AtomicUsize::new(0),
        });
        let journal = Arc::new(FaultJournal::all_failure());
        let cfg = Config::builder()
            .token("synthetic")
            .max_total_charge_usd("0.10")
            .transport(fake.clone())
            .journal(journal)
            .build()
            .unwrap();
        let rows = [
            CsvRow {
                row_id: 2,
                source_url: "https://instagram.com/reel/a".into(),
            },
            CsvRow {
                row_id: 3,
                source_url: "https://instagram.com/reel/b".into(),
            },
        ];
        let result = run_csv(&cfg, &rows, CsvExecuteOptions::default());
        assert!(result.stopped);
        assert_eq!(result.status, "journal_error");
        assert_eq!(result.processed_rows, 0);
        assert_eq!(result.unattempted_rows, [2, 3]);
        assert_eq!(fake.posts.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn csv_batch_serialization_redacts_diagnostics_and_raw_actor_values() {
        let result = CsvBatchResult {
            status: "partial_success".into(),
            stopped: false,
            planned_rows: 1,
            processed_rows: 1,
            unattempted_rows: vec![],
            concurrency: 1,
            counts: CsvCounts {
                success: 0,
                failed: 1,
                unknown: 0,
                skipped: 0,
            },
            rows: vec![CsvRowResult {
                row_id: 2,
                source_url: "https://instagram.com/reel/a".into(),
                status: "actor_error".into(),
                run_id: None,
                dataset_id: None,
                result: None,
                error: Some("apiKey=CSV_SYNTHETIC_SECRET".into()),
            }],
            raw_items: vec![serde_json::json!({"errMsg":"password=CSV_RAW_SECRET"})],
            error: Some("Bearer CSV_TOP_SECRET".into()),
        };
        let encoded = serde_json::to_string(&result).unwrap();
        for secret in ["CSV_SYNTHETIC_SECRET", "CSV_RAW_SECRET", "CSV_TOP_SECRET"] {
            assert!(!encoded.contains(secret), "secret persisted: {secret}");
        }
        assert!(encoded.contains("partial_success"));
    }
}
