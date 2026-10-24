use clap::{Parser, Subcommand};
use instagram_transcripts::{
    bulk::{BatchStatus, BulkOptions, BulkResult},
    error::Error,
    output::{write_json, write_result},
    sanitize::diagnostic,
    status::{Status, TranscriptResult},
    validators::validate_video_url,
    Client, Config,
};
use std::{path::PathBuf, process};

#[derive(Parser)]
#[command(
    name = "instagram-transcripts",
    version,
    about = "Safely fetch a transcript from the pinned Instagram Actor build"
)]
struct Args {
    #[command(subcommand)]
    command: Command,
}
#[derive(Subcommand)]
enum Command {
    Single {
        url: String,
        #[arg(long, default_value = "./output")]
        output_dir: PathBuf,
        #[arg(long, default_value = "memory")]
        journal: String,
        #[arg(long)]
        max_total_charge_usd: Option<String>,
        #[arg(long)]
        require_charge_cap: bool,
    },
    /// Execute one Actor-native bulk Run for multiple Reel/Post URLs.
    NativeBulk {
        urls: Vec<String>,
        #[arg(long, default_value = "./output")]
        output_dir: PathBuf,
        #[arg(long, default_value = "memory")]
        journal: String,
        #[arg(long, default_value_t = 12)]
        results_limit: usize,
        #[arg(long, default_value_t = false)]
        skip_pinned_posts: bool,
        #[arg(long, default_value_t = false)]
        include_shares_count: bool,
        #[arg(long)]
        max_total_charge_usd: Option<String>,
        #[arg(long)]
        require_charge_cap: bool,
    },
}

fn main() {
    let code = run();
    if code != 0 {
        process::exit(code);
    }
}
fn run() -> i32 {
    let args = Args::parse();
    match args.command {
        Command::Single {
            url,
            output_dir,
            journal,
            max_total_charge_usd,
            require_charge_cap,
        } => run_single(
            url,
            output_dir,
            journal,
            max_total_charge_usd,
            require_charge_cap,
        ),
        Command::NativeBulk {
            urls,
            output_dir,
            journal,
            results_limit,
            skip_pinned_posts,
            include_shares_count,
            max_total_charge_usd,
            require_charge_cap,
        } => run_native_bulk(
            urls,
            output_dir,
            journal,
            results_limit,
            skip_pinned_posts,
            include_shares_count,
            max_total_charge_usd,
            require_charge_cap,
        ),
    }
}

fn run_single(
    url: String,
    output_dir: PathBuf,
    journal: String,
    max_total_charge_usd: Option<String>,
    _require_charge_cap: bool,
) -> i32 {
    if journal != "memory" {
        eprintln!("ResultStatus: configuration_error; outputFile=(none); G1 supports only an in-memory journal");
        return 2;
    }
    if let Err(error) = validate_video_url(&url) {
        eprintln!("ResultStatus: configuration_error; outputFile=(none); {error}");
        return error.exit_code();
    }
    let token = match std::env::var("APIFY_TOKEN") {
        Ok(v) if !v.trim().is_empty() => v,
        _ => {
            eprintln!("ResultStatus: configuration_error; outputFile=(none); APIFY_TOKEN must be provided in the process environment");
            return 2;
        }
    };
    let cap = max_total_charge_usd.or_else(|| std::env::var("APIFY_MAX_TOTAL_CHARGE_USD").ok());
    let mut builder = Config::builder().token(token);
    if let Ok(actor) = std::env::var("APIFY_ACTOR_ID") {
        builder = builder.actor_id(actor);
    }
    if let Ok(session) = std::env::var("INSTAGRAM_SESSIONID") {
        builder = builder.session_id(Some(session));
    }
    if let Some(cap) = cap {
        builder = builder.max_total_charge_usd(cap);
    }
    let config = match builder.build() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("ResultStatus: configuration_error; outputFile=(none); {e}");
            return e.exit_code();
        }
    };
    let client = Client::new(config);
    match client.get_transcript(&url) {
        Ok(result) => match write_result(&output_dir, &result) {
            Ok(path) => {
                let summary = serde_json::json!({"status":result.status,"runId":result.run_id,"datasetId":result.dataset_id,"outputFile":path});
                println!("{summary}");
                status_exit(result.status)
            }
            Err(e) => {
                eprintln!("{}", output_error_summary(&result, &e));
                e.exit_code()
            }
        },
        Err(e) => {
            let run = e
                .run_id
                .as_deref()
                .map(|id| format!("; runId={id}"))
                .unwrap_or_default();
            eprintln!(
                "ResultStatus: {}; outputFile=(none){}; {}",
                error_status(e.kind),
                run,
                e
            );
            e.exit_code()
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn run_native_bulk(
    urls: Vec<String>,
    output_dir: PathBuf,
    journal: String,
    results_limit: usize,
    skip_pinned_posts: bool,
    include_shares_count: bool,
    max_total_charge_usd: Option<String>,
    _require_charge_cap: bool,
) -> i32 {
    if journal != "memory" {
        let summary = BulkResult::operation_error(
            "input_error",
            "G1 supports only an in-memory journal",
            None,
            None,
            None,
        );
        eprintln!(
            "{}",
            serde_json::to_string(&summary)
                .unwrap_or_else(|_| "{\"status\":\"input_error\"}".into())
        );
        return 2;
    }
    let _plan = match instagram_transcripts::bulk::plan_bulk(&urls) {
        Ok(p) => p,
        Err(e) => {
            let summary = BulkResult::operation_error("input_error", &e.message, None, None, None);
            eprintln!(
                "{}",
                serde_json::to_string(&summary)
                    .unwrap_or_else(|_| "{\"status\":\"input_error\"}".into())
            );
            return 2;
        }
    };
    if results_limit == 0 {
        let summary = BulkResult::operation_error(
            "input_error",
            "results-limit must be positive",
            Some(_plan.tasks.len()),
            None,
            None,
        );
        eprintln!(
            "{}",
            serde_json::to_string(&summary)
                .unwrap_or_else(|_| "{\"status\":\"input_error\"}".into())
        );
        return 2;
    }
    let token = match std::env::var("APIFY_TOKEN") {
        Ok(v) if !v.trim().is_empty() => v,
        _ => {
            let summary = BulkResult::operation_error(
                "input_error",
                "APIFY_TOKEN must be provided in the process environment",
                Some(_plan.tasks.len()),
                None,
                None,
            );
            eprintln!(
                "{}",
                serde_json::to_string(&summary)
                    .unwrap_or_else(|_| "{\"status\":\"input_error\"}".into())
            );
            return 2;
        }
    };
    let cap = max_total_charge_usd.or_else(|| std::env::var("APIFY_MAX_TOTAL_CHARGE_USD").ok());
    let mut builder = Config::builder().token(token);
    if let Ok(actor) = std::env::var("APIFY_ACTOR_ID") {
        builder = builder.actor_id(actor);
    }
    if let Ok(session) = std::env::var("INSTAGRAM_SESSIONID") {
        builder = builder.session_id(Some(session));
    }
    if let Some(cap) = cap {
        builder = builder.max_total_charge_usd(cap);
    }
    let config = match builder.build() {
        Ok(c) => c,
        Err(e) => {
            let summary = BulkResult::operation_error(
                "input_error",
                &e.message,
                Some(_plan.tasks.len()),
                None,
                None,
            );
            eprintln!(
                "{}",
                serde_json::to_string(&summary)
                    .unwrap_or_else(|_| "{\"status\":\"input_error\"}".into())
            );
            return e.exit_code();
        }
    };
    let client = Client::new(config);
    let result = client.get_transcripts(
        &urls,
        BulkOptions {
            results_limit: Some(results_limit),
            skip_pinned_posts: Some(skip_pinned_posts),
            include_shares_count: Some(include_shares_count),
        },
    );
    if matches!(
        result.status,
        BatchStatus::InputError | BatchStatus::CreationUnknown
    ) || (matches!(result.status, BatchStatus::Error) && result.results.is_empty())
    {
        println!(
            "{}",
            serde_json::to_string(&result)
                .unwrap_or_else(|_| "{\"status\":\"output_error\"}".into())
        );
        return result.exit_code();
    }
    let value = match serde_json::to_value(&result) {
        Ok(v) => v,
        Err(_) => {
            eprintln!("BatchStatus: output_error; errorCode=output_error; could not serialize batch result");
            return 2;
        }
    };
    match write_json(&output_dir, "native-bulk", &value) {
        Ok(path) => {
            println!(
                "{}",
                serde_json::json!({"status":result.status,"runId":result.run_id,"datasetId":result.dataset_id,"outputFile":path,"counts":result.counts})
            );
            result.exit_code()
        }
        Err(error) => {
            let failed = BulkResult::operation_error(
                "output_error",
                &error.message,
                result.planned_task_count,
                result.run_id,
                result.dataset_id,
            );
            eprintln!(
                "{}",
                serde_json::to_string(&failed)
                    .unwrap_or_else(|_| "{\"status\":\"output_error\"}".into())
            );
            2
        }
    }
}

fn output_error_summary(result: &TranscriptResult, error: &Error) -> String {
    let run = result
        .run_id
        .as_deref()
        .map(|id| format!("; runId={}", diagnostic(id)))
        .unwrap_or_default();
    let dataset = result
        .dataset_id
        .as_deref()
        .map(|id| format!("; datasetId={}", diagnostic(id)))
        .unwrap_or_default();
    format!(
        "ResultStatus: output_error; outputFile=(none){run}{dataset}; {}",
        diagnostic(&error.message)
    )
}

fn error_status(kind: instagram_transcripts::ErrorKind) -> &'static str {
    use instagram_transcripts::ErrorKind::*;
    match kind {
        Input | Configuration => "configuration_error",
        Transport => "transport_error",
        Protocol | Dataset | Attribution | BuildMismatch => "unknown",
        CreationUnknown => "creation_unknown",
        CreateRejected => "actor_error",
        RunFailed => "run_failed",
        Journal => "journal_error",
        Output => "output_error",
    }
}
fn status_exit(s: Status) -> i32 {
    match s {
        Status::Success => 0,
        Status::ActorError => 4,
        Status::Empty => 5,
        Status::NoTranscript => 6,
        Status::Unknown => 7,
        Status::TransportError => 8,
        Status::RunFailed => 9,
        Status::CreationUnknown => 10,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use instagram_transcripts::status::{AttributionVerification, BuildVerification};

    #[test]
    fn output_failure_summary_retains_run_and_dataset_ids_safely() {
        let dir = tempfile::tempdir().unwrap();
        let output_path = dir.path().join("not-a-directory");
        std::fs::write(&output_path, "occupied").unwrap();
        let mut result = TranscriptResult::empty(
            "https://www.instagram.com/reel/abc/",
            Status::Success,
            "dataset_classification",
            None,
        );
        result.run_id = Some("synthetic-run-r2".into());
        result.dataset_id = Some("synthetic-dataset-r2".into());
        result.build_verification = BuildVerification::Verified;
        result.attribution_verification = AttributionVerification::Verified;

        let error = write_result(&output_path, &result).unwrap_err();
        let summary = output_error_summary(&result, &error);
        assert!(summary.contains("ResultStatus: output_error"));
        assert!(summary.contains("runId=synthetic-run-r2"));
        assert!(summary.contains("datasetId=synthetic-dataset-r2"));
        assert!(summary.contains("could not create output directory"));
        assert!(!summary.contains("synthetic secret"));
    }

    #[test]
    fn native_bulk_cli_accepts_multiple_urls_and_safety_options() {
        let args = Args::try_parse_from([
            "instagram-transcripts",
            "native-bulk",
            "https://instagram.com/reel/A",
            "https://instagram.com/p/A",
            "--results-limit",
            "12",
            "--max-total-charge-usd",
            "0.10",
            "--require-charge-cap",
        ])
        .expect("native-bulk CLI arguments parse");
        match args.command {
            Command::NativeBulk {
                urls,
                results_limit,
                max_total_charge_usd,
                require_charge_cap,
                ..
            } => {
                assert_eq!(urls.len(), 2);
                assert_eq!(results_limit, 12);
                assert_eq!(max_total_charge_usd.as_deref(), Some("0.10"));
                assert!(require_charge_cap);
            }
            _ => panic!("expected native-bulk command"),
        }
    }
}
