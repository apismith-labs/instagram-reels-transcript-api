use anyhow::{anyhow, bail, Context, Result};
use csv::{Reader, Writer};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::env;
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use tokio::sync::{Mutex, Semaphore};
use tokio::time::{sleep, Duration};

const DEFAULT_ACTOR_ID: &str = "apple_yang/instagram-transcripts-scraper";
const API_BASE_URL: &str = "https://api.apify.com/v2";
const MAX_RETRIES: usize = 2;

#[derive(Debug, Deserialize)]
struct ApiResponse<T> {
    data: T,
}

#[derive(Debug, Deserialize)]
struct RunInfo {
    id: Option<String>,
    status: Option<String>,
    #[serde(rename = "defaultDatasetId")]
    default_dataset_id: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct BatchRecord {
    source_url: String,
    status: String,
    item_count: usize,
    text: String,
    segments: Vec<Value>,
    err_msg: String,
    raw_items: Vec<Value>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ErrorRecord {
    source_url: String,
    error: String,
}

#[derive(Clone)]
struct Config {
    token: String,
    actor_id: String,
    sessionid: String,
}

#[tokio::main]
async fn main() -> Result<()> {
    let repo_root = find_repo_root()?;
    let _ = dotenvy::from_path(repo_root.join(".env"));

    let config = Config {
        token: require_env("APIFY_TOKEN")?,
        actor_id: env::var("APIFY_ACTOR_ID").unwrap_or_else(|_| DEFAULT_ACTOR_ID.to_string()),
        sessionid: env::var("INSTAGRAM_SESSIONID").unwrap_or_default(),
    };
    let max_concurrency = parse_max_concurrency()?;
    let csv_path = env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| repo_root.join("sample-data/instagram-reel-urls.csv"));
    let urls = read_urls(&csv_path)?;
    if urls.is_empty() {
        bail!("Error: CSV does not contain any videoUrl values.");
    }

    println!("Actor ID: {}", config.actor_id);
    println!("Total URLs: {}", urls.len());
    println!("Max concurrency: {max_concurrency}");
    // Higher concurrency may increase Apify usage cost and rate-limit risk.

    let output_dir = repo_root.join("sample-output/generated");
    fs::create_dir_all(&output_dir).context("Failed to create output directory")?;

    let client = Client::builder()
        .timeout(Duration::from_secs(600))
        .build()
        .context("Failed to create HTTP client")?;
    let semaphore = Arc::new(Semaphore::new(max_concurrency));
    let results = Arc::new(Mutex::new(Vec::<BatchRecord>::new()));
    let errors = Arc::new(Mutex::new(Vec::<ErrorRecord>::new()));
    let processed = Arc::new(AtomicUsize::new(0));
    let success = Arc::new(AtomicUsize::new(0));
    let failed = Arc::new(AtomicUsize::new(0));
    let total = urls.len();
    let mut handles = Vec::with_capacity(urls.len());

    for url in urls {
        let permit = semaphore.clone().acquire_owned().await?;
        let client = client.clone();
        let config = config.clone();
        let results = results.clone();
        let errors = errors.clone();
        let processed = processed.clone();
        let success = success.clone();
        let failed = failed.clone();

        handles.push(tokio::spawn(async move {
            let _permit = permit;
            match process_url(&client, &config, &url).await {
                Ok(record) => {
                    results.lock().await.push(record);
                    success.fetch_add(1, Ordering::Relaxed);
                }
                Err(error) => {
                    errors.lock().await.push(ErrorRecord {
                        source_url: url,
                        error: error.to_string(),
                    });
                    failed.fetch_add(1, Ordering::Relaxed);
                }
            }
            let done = processed.fetch_add(1, Ordering::Relaxed) + 1;
            println!(
                "Progress: total={} processed={} success={} failed={}",
                total,
                done,
                success.load(Ordering::Relaxed),
                failed.load(Ordering::Relaxed)
            );
        }));
    }

    for handle in handles {
        handle.await.context("Batch worker failed")?;
    }

    let results_path = output_dir.join("rust-batch-results.jsonl");
    let errors_path = output_dir.join("rust-batch-errors.csv");
    write_jsonl(&results_path, &results.lock().await)?;
    write_errors_csv(&errors_path, &errors.lock().await)?;

    println!("Results path: {}", results_path.display());
    println!("Errors path: {}", errors_path.display());

    Ok(())
}

async fn process_url(client: &Client, config: &Config, url: &str) -> Result<BatchRecord> {
    let mut last_error = None;
    for attempt in 0..=MAX_RETRIES {
        match call_actor_once(client, config, url).await {
            Ok(items) => return Ok(build_record(url, items)),
            Err(error) => {
                last_error = Some(error);
                if attempt < MAX_RETRIES {
                    sleep(Duration::from_secs(2_u64.pow(attempt as u32))).await;
                }
            }
        }
    }
    Err(last_error.unwrap_or_else(|| anyhow!("Unknown error")))
}

async fn call_actor_once(client: &Client, config: &Config, reel_url: &str) -> Result<Vec<Value>> {
    let run =
        start_actor_run(client, &config.token, &config.actor_id, reel_url, &config.sessionid)
            .await?;
    let run_id = run
        .id
        .ok_or_else(|| anyhow!("Actor run response did not include an id."))?;
    let finished_run = wait_for_run(client, &config.token, &run_id).await?;
    let status = finished_run.status.unwrap_or_default();
    if status != "SUCCEEDED" {
        bail!("Actor run finished with status {status}.");
    }
    let dataset_id = finished_run
        .default_dataset_id
        .ok_or_else(|| anyhow!("Actor run completed without a defaultDatasetId."))?;
    fetch_dataset_items(client, &config.token, &dataset_id).await
}

fn build_record(source_url: &str, items: Vec<Value>) -> BatchRecord {
    let text = first_string(&items, "text").unwrap_or_default();
    let segments = first_array(&items, "segments");
    let err_msg = first_string(&items, "errMsg").unwrap_or_default();
    let status = if !err_msg.is_empty() {
        "actor_error"
    } else if items.is_empty() {
        "empty"
    } else {
        "success"
    };

    BatchRecord {
        source_url: source_url.to_string(),
        status: status.to_string(),
        item_count: items.len(),
        text,
        segments,
        err_msg,
        raw_items: items,
    }
}

async fn start_actor_run(
    client: &Client,
    token: &str,
    actor_id: &str,
    reel_url: &str,
    sessionid: &str,
) -> Result<RunInfo> {
    let actor_id_for_url = actor_id.replace('/', "~");
    let url = format!("{API_BASE_URL}/acts/{actor_id_for_url}/runs");
    let body = json!({
        "videoUrl": reel_url,
        "sessionid": sessionid,
    });

    let response: ApiResponse<RunInfo> =
        send_json(client, token, reqwest::Method::POST, &url, Some(body)).await?;
    Ok(response.data)
}

async fn wait_for_run(client: &Client, token: &str, run_id: &str) -> Result<RunInfo> {
    for _ in 0..150 {
        let url = format!("{API_BASE_URL}/actor-runs/{run_id}");
        let response: ApiResponse<RunInfo> =
            send_json(client, token, reqwest::Method::GET, &url, None).await?;
        let status = response.data.status.as_deref().unwrap_or("");
        if matches!(status, "SUCCEEDED" | "FAILED" | "TIMED-OUT" | "ABORTED") {
            return Ok(response.data);
        }
        sleep(Duration::from_secs(2)).await;
    }
    bail!("Timed out waiting for Actor run to finish.")
}

async fn fetch_dataset_items(client: &Client, token: &str, dataset_id: &str) -> Result<Vec<Value>> {
    let url = format!("{API_BASE_URL}/datasets/{dataset_id}/items");
    send_json(client, token, reqwest::Method::GET, &url, None).await
}

async fn send_json<T: for<'de> Deserialize<'de>>(
    client: &Client,
    token: &str,
    method: reqwest::Method,
    url: &str,
    body: Option<Value>,
) -> Result<T> {
    let mut request = client
        .request(method, url)
        .bearer_auth(token)
        .header("Content-Type", "application/json");
    if let Some(body) = body {
        request = request.json(&body);
    }

    let response = request.send().await.context("Apify API request failed")?;
    let status = response.status();
    let text = response.text().await.context("Failed to read Apify API response")?;
    if !status.is_success() {
        bail!("HTTP {} from Apify API: {}", status.as_u16(), text);
    }
    serde_json::from_str(&text).context("Failed to parse Apify API response JSON")
}

fn read_urls(csv_path: &Path) -> Result<Vec<String>> {
    let mut reader = Reader::from_path(csv_path)
        .with_context(|| format!("Error: CSV file not found: {}", csv_path.display()))?;
    let headers = reader.headers()?.clone();
    let video_url_index = headers
        .iter()
        .position(|header| header == "videoUrl")
        .ok_or_else(|| anyhow!("Error: CSV must include a videoUrl column."))?;

    let mut urls = Vec::new();
    for record in reader.records() {
        let record = record?;
        if let Some(value) = record.get(video_url_index) {
            let trimmed = value.trim();
            if !trimmed.is_empty() {
                urls.push(trimmed.to_string());
            }
        }
    }
    Ok(urls)
}

fn write_jsonl(path: &Path, records: &[BatchRecord]) -> Result<()> {
    let file = File::create(path).context("Failed to create JSONL output file")?;
    let mut writer = BufWriter::new(file);
    for record in records {
        writeln!(writer, "{}", serde_json::to_string(record)?)?;
    }
    Ok(())
}

fn write_errors_csv(path: &Path, records: &[ErrorRecord]) -> Result<()> {
    let mut writer = Writer::from_path(path).context("Failed to create errors CSV")?;
    writer.write_record(["sourceUrl", "error"])?;
    for record in records {
        writer.serialize(record)?;
    }
    writer.flush()?;
    Ok(())
}

fn first_string(items: &[Value], field: &str) -> Option<String> {
    items
        .iter()
        .filter_map(|item| item.get(field)?.as_str())
        .find(|value| !value.is_empty())
        .map(ToString::to_string)
}

fn first_array(items: &[Value], field: &str) -> Vec<Value> {
    items
        .iter()
        .filter_map(|item| item.get(field)?.as_array())
        .next()
        .cloned()
        .unwrap_or_default()
}

fn require_env(name: &str) -> Result<String> {
    let value = env::var(name).unwrap_or_default();
    if value.trim().is_empty() {
        bail!("Error: {name} is required. Set it in .env or your environment.");
    }
    Ok(value)
}

fn parse_max_concurrency() -> Result<usize> {
    let raw = env::var("MAX_CONCURRENCY").unwrap_or_else(|_| "3".to_string());
    let value = raw
        .parse::<usize>()
        .context("Error: MAX_CONCURRENCY must be an integer.")?;
    if value == 0 {
        bail!("Error: MAX_CONCURRENCY must be at least 1.");
    }
    Ok(value)
}

fn find_repo_root() -> Result<PathBuf> {
    let mut current = env::current_dir().context("Failed to read current directory")?;
    loop {
        if current.join(".env.example").exists() && current.join("sample-data").exists() {
            return Ok(current);
        }
        if !current.pop() {
            break;
        }
    }
    bail!("Error: Could not locate repository root.")
}
