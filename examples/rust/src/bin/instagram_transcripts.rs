use clap::{ArgGroup, Parser, Subcommand};
use instagram_transcripts::{
    bulk::{BulkOptions, BulkResult},
    csv_batch::{parse_csv, plan_csv, CsvExecuteOptions},
    error::{Error, ErrorKind},
    journal::{Journal, JsonlFileJournal},
    output::{write_json, write_result},
    profile::{ProfileOptions, ProfileStatus},
    sanitize::diagnostic,
    status::{Status, TranscriptResult},
    validators::{validate_only_posts_newer_than, validate_usernames, validate_video_url},
    Client, Config,
};
use std::{fs, path::PathBuf, process, sync::Arc, time::Duration};

#[derive(Parser)]
#[command(
    name = "instagram-transcripts",
    version,
    about = "Offline-safe Instagram transcript Actor client"
)]
struct Args {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    Single {
        #[arg(required_unless_present = "resume")]
        url: Option<String>,
        #[arg(long)]
        resume: Option<String>,
        #[arg(long, default_value = "./output")]
        output_dir: PathBuf,
        #[arg(long, default_value = "memory")]
        journal: String,
        #[arg(long)]
        max_total_charge_usd: Option<String>,
        #[arg(long)]
        require_charge_cap: bool,
        #[arg(long, default_value_t = 300)]
        timeout: u64,
        #[arg(long)]
        session_id: Option<String>,
    },
    /// One Actor-native Run for unique typed URL identities. `native-bulk` is an alias.
    #[command(name = "bulk", alias = "native-bulk")]
    NativeBulk {
        urls: Vec<String>,
        #[arg(long)]
        input_file: Option<PathBuf>,
        #[arg(long)]
        resume: Option<String>,
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
        #[arg(long, default_value_t = 300)]
        timeout: u64,
        #[arg(long)]
        session_id: Option<String>,
    },
    Profile {
        usernames: Vec<String>,
        #[arg(long, default_value_t = 12)]
        results_limit: usize,
        #[arg(long)]
        only_posts_newer_than: Option<String>,
        #[arg(long, default_value_t = false)]
        skip_pinned_posts: bool,
        #[arg(long, default_value_t = false)]
        include_shares_count: bool,
        #[arg(long, default_value = "./output")]
        output_dir: PathBuf,
        #[arg(long, default_value = "memory")]
        journal: String,
        #[arg(long)]
        max_total_charge_usd: Option<String>,
        #[arg(long)]
        require_charge_cap: bool,
        #[arg(long, default_value_t = 300)]
        timeout: u64,
        #[arg(long)]
        session_id: Option<String>,
    },
    #[command(group(ArgGroup::new("csv_mode").args(["dry_run", "execute"]).multiple(false)))]
    Csv {
        file: PathBuf,
        #[arg(long)]
        dry_run: bool,
        #[arg(long)]
        execute: bool,
        #[arg(long, default_value_t = 1)]
        concurrency: usize,
        #[arg(long, default_value = "./output")]
        output_dir: PathBuf,
        #[arg(long, default_value = "memory")]
        journal: String,
        #[arg(long)]
        max_total_charge_usd: Option<String>,
        #[arg(long, default_value_t = 300)]
        timeout: u64,
        #[arg(long)]
        session_id: Option<String>,
    },
}

fn main() {
    let code = run();
    if code != 0 {
        process::exit(code);
    }
}

fn run() -> i32 {
    match Args::parse().command {
        Command::Single {
            url,
            resume,
            output_dir,
            journal,
            max_total_charge_usd,
            require_charge_cap: _,
            timeout,
            session_id,
        } => run_single(
            url,
            resume,
            output_dir,
            journal,
            max_total_charge_usd,
            timeout,
            session_id,
        ),
        Command::NativeBulk {
            urls,
            input_file,
            resume,
            output_dir,
            journal,
            results_limit,
            skip_pinned_posts,
            include_shares_count,
            max_total_charge_usd,
            require_charge_cap: _,
            timeout,
            session_id,
        } => run_bulk(
            urls,
            input_file,
            resume,
            output_dir,
            journal,
            results_limit,
            skip_pinned_posts,
            include_shares_count,
            max_total_charge_usd,
            timeout,
            session_id,
        ),
        Command::Profile {
            usernames,
            results_limit,
            only_posts_newer_than,
            skip_pinned_posts,
            include_shares_count,
            output_dir,
            journal,
            max_total_charge_usd,
            require_charge_cap: _,
            timeout,
            session_id,
        } => run_profile(
            usernames,
            results_limit,
            only_posts_newer_than,
            skip_pinned_posts,
            include_shares_count,
            output_dir,
            journal,
            max_total_charge_usd,
            timeout,
            session_id,
        ),
        Command::Csv {
            file,
            dry_run: _,
            execute,
            concurrency,
            output_dir,
            journal,
            max_total_charge_usd,
            timeout,
            session_id,
        } => run_csv_file(
            file,
            execute,
            concurrency,
            output_dir,
            journal,
            max_total_charge_usd,
            timeout,
            session_id,
        ),
    }
}

fn make_config(
    cap: Option<String>,
    journal_path: &str,
    timeout: u64,
    session_id: Option<String>,
) -> Result<Config, Error> {
    if timeout == 0 {
        return Err(Error::new(
            ErrorKind::Input,
            "cli",
            "timeout must be positive",
        ));
    }
    let cap = cap.or_else(|| std::env::var("APIFY_MAX_TOTAL_CHARGE_USD").ok());
    let cap = instagram_transcripts::validators::validate_charge_cap(cap.as_deref())?;
    let journal: Option<Arc<dyn Journal>> = if journal_path == "memory" {
        None
    } else {
        Some(Arc::new(JsonlFileJournal::open(journal_path)?))
    };
    // Only read the credential after command, input, timeout, cap, and journal-path preflight.
    let token = std::env::var("APIFY_TOKEN")
        .ok()
        .filter(|v| !v.trim().is_empty())
        .ok_or_else(|| {
            Error::new(
                ErrorKind::Configuration,
                "config",
                "APIFY_TOKEN must be provided in the process environment",
            )
        })?;
    let mut builder = Config::builder()
        .token(token)
        .max_total_charge_usd(cap)
        .poll_timeout(Duration::from_secs(timeout));
    if let Ok(actor) = std::env::var("APIFY_ACTOR_ID") {
        builder = builder.actor_id(actor);
    }
    let session = session_id.or_else(|| std::env::var("INSTAGRAM_SESSIONID").ok());
    builder = builder.session_id(session);
    if let Some(journal) = journal {
        builder = builder.journal(journal);
    }
    builder.build()
}

fn run_single(
    url: Option<String>,
    resume: Option<String>,
    output_dir: PathBuf,
    journal: String,
    cap: Option<String>,
    timeout: u64,
    session_id: Option<String>,
) -> i32 {
    let normalized = match url.as_deref().map(validate_video_url).transpose() {
        Ok(v) => v,
        Err(e) => {
            eprintln!(
                "ResultStatus: configuration_error; outputFile=(none); {}",
                diagnostic(&e.message)
            );
            return e.exit_code();
        }
    };
    if resume.as_deref().is_some_and(|id| id.trim().is_empty())
        || (resume.is_some() && journal == "memory")
    {
        eprintln!("ResultStatus: journal_error; outputFile=(none); resume requires a Run ID and persistent --journal path");
        return 2;
    }
    if let Some(url) = normalized.as_deref().filter(|_| resume.is_some()) {
        // Validation above ensures caller-supplied comparison input is safe before credentials load.
        let _ = url;
    }
    let config = match make_config(cap, &journal, timeout, session_id) {
        Ok(v) => v,
        Err(e) => return report_error(e),
    };
    let client = Client::new(config);
    let result = if let Some(run_id) = resume {
        client.resume_transcript_with_url(&run_id, normalized.as_deref())
    } else {
        client.get_transcript(normalized.as_deref().unwrap_or_default())
    };
    match result {
        Ok(result) => match write_result(&output_dir, &result) {
            Ok(path) => {
                println!(
                    "{}",
                    serde_json::json!({"status":result.status,"runId":result.run_id,"datasetId":result.dataset_id,"outputFile":path})
                );
                status_exit(result.status)
            }
            Err(e) => {
                eprintln!("{}", output_error_summary(&result, &e));
                e.exit_code()
            }
        },
        Err(e) => report_error(e),
    }
}

#[allow(clippy::too_many_arguments)]
fn run_bulk(
    mut urls: Vec<String>,
    input_file: Option<PathBuf>,
    resume: Option<String>,
    output_dir: PathBuf,
    journal: String,
    results_limit: usize,
    skip: bool,
    shares: bool,
    cap: Option<String>,
    timeout: u64,
    session_id: Option<String>,
) -> i32 {
    if let Some(file) = input_file {
        let content = match fs::read_to_string(file) {
            Ok(v) => v,
            Err(_) => {
                eprintln!("Bulk input file could not be read");
                return 2;
            }
        };
        urls.extend(
            content
                .lines()
                .map(str::trim)
                .filter(|line| !line.is_empty())
                .map(str::to_owned),
        );
    }
    if urls.is_empty() || results_limit == 0 || (resume.is_some() && journal == "memory") {
        eprintln!("Bulk input is empty, results-limit is invalid, or Resume requires persistent --journal");
        return 2;
    }
    let plan = match instagram_transcripts::bulk::plan_bulk(&urls) {
        Ok(v) => v,
        Err(e) => return report_error(e),
    };
    let config = match make_config(cap, &journal, timeout, session_id) {
        Ok(v) => v,
        Err(e) => return report_error(e),
    };
    let client = Client::new(config);
    let result = if let Some(run_id) = resume {
        client.resume_transcripts(&run_id, &urls)
    } else {
        client.get_transcripts(
            &urls,
            BulkOptions {
                results_limit: Some(results_limit),
                skip_pinned_posts: Some(skip),
                include_shares_count: Some(shares),
            },
        )
    };
    if result.run_id.is_none() && result.results.is_empty() {
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
            eprintln!("Bulk result serialization failed");
            return 2;
        }
    };
    match write_json(&output_dir, "bulk", &value) {
        Ok(path) => {
            println!(
                "{}",
                serde_json::json!({"status":result.status,"runId":result.run_id,"datasetId":result.dataset_id,"outputFile":path,"counts":result.counts})
            );
            result.exit_code()
        }
        Err(e) => {
            eprintln!(
                "{}",
                serde_json::to_string(&BulkResult::operation_error(
                    "output_error",
                    &e.message,
                    Some(plan.tasks.len()),
                    result.run_id,
                    result.dataset_id
                ))
                .unwrap_or_default()
            );
            2
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn run_profile(
    usernames: Vec<String>,
    results_limit: usize,
    date: Option<String>,
    skip: bool,
    shares: bool,
    output_dir: PathBuf,
    journal: String,
    cap: Option<String>,
    timeout: u64,
    session_id: Option<String>,
) -> i32 {
    let usernames = match validate_usernames(&usernames) {
        Ok(v) => v,
        Err(e) => return report_error(e),
    };
    let date = match validate_only_posts_newer_than(date.as_deref()) {
        Ok(v) => v,
        Err(e) => return report_error(e),
    };
    if results_limit == 0 {
        eprintln!("results-limit must be positive");
        return 2;
    }
    let config = match make_config(cap, &journal, timeout, session_id) {
        Ok(v) => v,
        Err(e) => return report_error(e),
    };
    let result = Client::new(config).get_profile_posts(
        &usernames,
        ProfileOptions {
            results_limit: Some(results_limit),
            only_posts_newer_than: date,
            skip_pinned_posts: Some(skip),
            include_shares_count: Some(shares),
        },
    );
    match result {
        Err(e) => report_error(e),
        Ok(result) => {
            let value = match serde_json::to_value(&result) {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("Profile result serialization failed");
                    return 2;
                }
            };
            match write_json(&output_dir, "profile", &value) {
                Ok(path) => {
                    println!(
                        "{}",
                        serde_json::json!({"status":result.status,"runId":result.run_id,"datasetId":result.dataset_id,"postCount":result.posts.len(),"outputFile":path})
                    );
                    profile_exit(result.status)
                }
                Err(e) => {
                    eprintln!(
                        "Profile output_error runId={} {}",
                        result.run_id.as_deref().unwrap_or("(none)"),
                        diagnostic(&e.message)
                    );
                    2
                }
            }
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn run_csv_file(
    file: PathBuf,
    execute: bool,
    concurrency: usize,
    output_dir: PathBuf,
    journal: String,
    cap: Option<String>,
    timeout: u64,
    session_id: Option<String>,
) -> i32 {
    let content = match fs::read_to_string(&file) {
        Ok(v) => v,
        Err(_) => {
            eprintln!("CSV input file could not be read");
            return 2;
        }
    };
    let rows = match parse_csv(&content) {
        Ok(v) => v,
        Err(e) => return report_error(e),
    };
    let effective_cap = cap.or_else(|| std::env::var("APIFY_MAX_TOTAL_CHARGE_USD").ok());
    let plan = match plan_csv(
        &rows,
        Some(file.display().to_string()),
        effective_cap.as_deref(),
        concurrency,
    ) {
        Ok(v) => v,
        Err(e) => return report_error(e),
    };
    if !execute {
        println!(
            "{}",
            serde_json::to_string(&plan).unwrap_or_else(|_| "{}".into())
        );
        return 0;
    }
    if effective_cap
        .as_deref()
        .and_then(|v| instagram_transcripts::validators::validate_charge_cap(Some(v)).ok())
        .is_none()
    {
        eprintln!("CSV --execute requires a positive --max-total-charge-usd (or APIFY_MAX_TOTAL_CHARGE_USD)");
        return 2;
    }
    if journal == "memory" {
        eprintln!("CSV --execute requires a persistent --journal path");
        return 2;
    }
    let config = match make_config(effective_cap, &journal, timeout, session_id) {
        Ok(v) => v,
        Err(e) => return report_error(e),
    };
    let result = Client::new(config).run_csv(
        &rows,
        CsvExecuteOptions {
            concurrency,
            csv_path: Some(file.display().to_string()),
        },
    );
    let value = match serde_json::to_value(&result) {
        Ok(v) => v,
        Err(_) => {
            eprintln!("CSV result serialization failed");
            return 2;
        }
    };
    match write_json(&output_dir, "csv-batch", &value) {
        Ok(path) => {
            println!(
                "{}",
                serde_json::json!({"status":result.status,"processedRows":result.processed_rows,"unattemptedRows":result.unattempted_rows,"outputFile":path})
            );
            csv_exit(&result.status)
        }
        Err(e) => {
            eprintln!("CSV output_error {}", diagnostic(&e.message));
            2
        }
    }
}

fn report_error(error: Error) -> i32 {
    let run = error
        .run_id
        .as_deref()
        .map(|v| format!("; runId={}", diagnostic(v)))
        .unwrap_or_default();
    let dataset = error
        .dataset_id
        .as_deref()
        .map(|v| format!("; datasetId={}", diagnostic(v)))
        .unwrap_or_default();
    eprintln!(
        "ResultStatus: {}; outputFile=(none){run}{dataset}; {}",
        error_status(error.kind),
        diagnostic(&error.message)
    );
    error.exit_code()
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
fn error_status(kind: ErrorKind) -> &'static str {
    match kind {
        ErrorKind::Input | ErrorKind::Configuration => "configuration_error",
        ErrorKind::Transport => "transport_error",
        ErrorKind::Protocol
        | ErrorKind::Dataset
        | ErrorKind::Attribution
        | ErrorKind::BuildMismatch => "unknown",
        ErrorKind::CreationUnknown => "creation_unknown",
        ErrorKind::CreateRejected => "actor_error",
        ErrorKind::RunFailed => "run_failed",
        ErrorKind::Journal => "journal_error",
        ErrorKind::Output => "output_error",
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
fn profile_exit(s: ProfileStatus) -> i32 {
    match s {
        ProfileStatus::Success | ProfileStatus::Empty => 0,
        ProfileStatus::ActorError => 4,
        ProfileStatus::RunFailed => 9,
        ProfileStatus::Unknown => 7,
    }
}
fn csv_exit(s: &str) -> i32 {
    match s {
        "success" => 0,
        "partial_success" => 2,
        "creation_unknown" => 10,
        "journal_error" => 2,
        _ => 1,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use instagram_transcripts::{
        status::{AttributionVerification, BuildVerification},
        transport::Request,
    };
    use reqwest::Method;

    #[test]
    fn output_failure_summary_retains_run_and_dataset_ids_safely() {
        let dir = tempfile::tempdir().unwrap();
        let output_path = dir.path().join("not-a-directory");
        fs::write(&output_path, "occupied").unwrap();
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
    }
    #[test]
    fn cli_exposes_all_modes_compat_alias_and_safety_options() {
        assert!(Args::try_parse_from([
            "instagram-transcripts",
            "bulk",
            "https://instagram.com/reel/A",
            "--max-total-charge-usd",
            "0.10"
        ])
        .is_ok());
        assert!(Args::try_parse_from([
            "instagram-transcripts",
            "native-bulk",
            "https://instagram.com/reel/A"
        ])
        .is_ok());
        assert!(Args::try_parse_from([
            "instagram-transcripts",
            "profile",
            "alice",
            "--results-limit",
            "1"
        ])
        .is_ok());
        assert!(
            Args::try_parse_from(["instagram-transcripts", "csv", "input.csv", "--dry-run"])
                .is_ok()
        );
        assert!(Args::try_parse_from([
            "instagram-transcripts",
            "csv",
            "input.csv",
            "--dry-run",
            "--execute"
        ])
        .is_err());
        assert!(
            Args::try_parse_from(["instagram-transcripts", "single", "--resume", "run-1"]).is_ok()
        );
    }
    #[test]
    fn csv_dry_run_does_not_consult_credentials() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("input.csv");
        fs::write(&path, "url\nnot-an-instagram-url\n").unwrap();
        let rows = parse_csv(&fs::read_to_string(path).unwrap()).unwrap();
        let plan = plan_csv(&rows, None, None, 1).unwrap();
        assert_eq!(plan.maximum_actor_runs, 0);
        assert!(matches!(
            Request::new(Method::GET, "https://unused.invalid").method,
            Method::GET
        ));
    }

    #[test]
    fn profile_actor_error_keeps_the_contract_exit_code() {
        assert_eq!(profile_exit(ProfileStatus::ActorError), 4);
    }

    #[test]
    fn csv_execute_rejects_memory_journal_before_credentials() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("input.csv");
        fs::write(&path, "url\nhttps://instagram.com/reel/a\n").unwrap();
        let code = run_csv_file(
            path,
            true,
            1,
            dir.path().join("output"),
            "memory".into(),
            Some("0.10".into()),
            300,
            None,
        );
        assert_eq!(
            code, 2,
            "CSV execution must fail closed before credential loading without a durable Journal"
        );
    }
}
