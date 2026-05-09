# Use Instagram Reels Transcript API with Rust

These examples show how to call the Apify Actor `apple_yang/instagram-transcripts-scraper` from Rust using `tokio`, `reqwest`, `serde`, `dotenvy`, and `csv`.

## Requirements

- Rust 1.75 or newer
- Rust 2021 edition

## Setup

From this directory:

```bash
cargo build
```

## Configure `.env`

From the repository root:

```bash
cp .env.example .env
```

Edit `.env` and set configuration values:

```bash
APIFY_TOKEN='your_apify_token_here'
APIFY_ACTOR_ID='apple_yang/instagram-transcripts-scraper'
INSTAGRAM_SESSIONID=''
MAX_CONCURRENCY=3
```

Quote values that contain special characters such as `&` or `?`.

Do not put Instagram Reel URLs in `.env` for normal usage. Single URL examples take the URL as a CLI argument, and batch examples read URLs from CSV.

## Run a single URL

Pass the Reel URL as runtime input:

```bash
cargo run --bin single_url -- "https://www.instagram.com/reel/your_reel_id/"
```

Output is saved to:

```text
sample-output/generated/rust-single-url-response.json
```

## Run batch CSV processing

Use the default CSV:

```bash
cargo run --bin batch_csv
```

Or pass a custom CSV path:

```bash
cargo run --bin batch_csv -- path/to/urls.csv
```

The CSV must include a `videoUrl` column.

Batch processing calls the Actor once per URL and may generate billable Apify usage. `MAX_CONCURRENCY` defaults to `3`; higher concurrency can increase cost and rate-limit risk.

Batch outputs are saved to:

```text
sample-output/generated/rust-batch-results.jsonl
sample-output/generated/rust-batch-errors.csv
```

## Security

Do not hard-code `APIFY_TOKEN` or `INSTAGRAM_SESSIONID`. Keep secrets in `.env` or your deployment secret manager, and never commit `.env` or tokens.
