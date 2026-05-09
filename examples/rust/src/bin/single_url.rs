use anyhow::{anyhow, bail, Context, Result};
use reqwest::Client;
use serde::Deserialize;
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::path::PathBuf;
use tokio::time::{sleep, Duration};

const DEFAULT_ACTOR_ID: &str = "apple_yang/instagram-transcripts-scraper";
const API_BASE_URL: &str = "https://api.apify.com/v2";

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

#[tokio::main]
async fn main() -> Result<()> {
    let repo_root = find_repo_root()?;
    let _ = dotenvy::from_path(repo_root.join(".env"));

    let token = require_env("APIFY_TOKEN")?;
    let actor_id = env::var("APIFY_ACTOR_ID").unwrap_or_else(|_| DEFAULT_ACTOR_ID.to_string());
    let sessionid = env::var("INSTAGRAM_SESSIONID").unwrap_or_default();
    let _max_concurrency = env::var("MAX_CONCURRENCY").unwrap_or_else(|_| "3".to_string());
    let reel_url = env::args()
        .nth(1)
        .or_else(|| env::var("INSTAGRAM_REEL_URL").ok())
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| anyhow!("Error: Pass an Instagram Reel URL as a CLI argument."))?;

    println!("Actor ID: {actor_id}");
    println!("Running request...");

    let client = Client::builder()
        .timeout(Duration::from_secs(600))
        .build()
        .context("Failed to create HTTP client")?;

    let run = start_actor_run(&client, &token, &actor_id, &reel_url, &sessionid).await?;
    let run_id = run
        .id
        .ok_or_else(|| anyhow!("Error: Actor run response did not include an id."))?;
    let finished_run = wait_for_run(&client, &token, &run_id).await?;
    let status = finished_run.status.unwrap_or_default();
    if status != "SUCCEEDED" {
        bail!("Error: Actor run finished with status {status}.");
    }
    let dataset_id = finished_run
        .default_dataset_id
        .ok_or_else(|| anyhow!("Error: Actor run completed without a defaultDatasetId."))?;

    let items = fetch_dataset_items(&client, &token, &dataset_id).await?;

    let output_dir = repo_root.join("sample-output/generated");
    let output_file = output_dir.join("rust-single-url-response.json");
    fs::create_dir_all(&output_dir).context("Failed to create output directory")?;
    fs::write(
        &output_file,
        format!("{}\n", serde_json::to_string_pretty(&items)?),
    )
    .context("Failed to write output file")?;

    let text = first_string(&items, "text").unwrap_or_default();
    let segments_count = first_array_len(&items, "segments");
    let err_msg = first_string(&items, "errMsg").unwrap_or_default();

    println!("Output path: {}", output_file.display());
    println!("Items: {}", items.len());
    println!("Transcript characters: {}", text.chars().count());
    println!("Segments: {segments_count}");
    if !err_msg.is_empty() {
        println!("errMsg: {err_msg}");
    }

    Ok(())
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
    bail!("Error: Timed out waiting for Actor run to finish.")
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

fn first_string(items: &[Value], field: &str) -> Option<String> {
    items
        .iter()
        .filter_map(|item| item.get(field)?.as_str())
        .find(|value| !value.is_empty())
        .map(ToString::to_string)
}

fn first_array_len(items: &[Value], field: &str) -> usize {
    items
        .iter()
        .filter_map(|item| item.get(field)?.as_array())
        .next()
        .map_or(0, Vec::len)
}

fn require_env(name: &str) -> Result<String> {
    let value = env::var(name).unwrap_or_default();
    if value.trim().is_empty() {
        bail!("Error: {name} is required. Set it in .env or your environment.");
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
