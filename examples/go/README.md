# Use Instagram Reels Transcript API with Go

These examples show how to call the Apify Actor `apple_yang/instagram-transcripts-scraper` from Go using `net/http`, `encoding/json`, and `godotenv`.

## Requirements

- Go 1.22 or newer

## Setup

From this directory:

```bash
go mod tidy
```

## Configure `.env`

From the repository root:

```bash
cp .env.example .env
```

Edit `.env` and set your Apify token and Reel URL:

```bash
APIFY_TOKEN='your_apify_token_here'
INSTAGRAM_REEL_URL='https://www.instagram.com/reel/your_reel_id/'
```

Quote values that contain special characters such as `&` or `?`.

Optionally set `INSTAGRAM_SESSIONID` if your integration requires it. Never commit `.env`.

## Run a single URL

Use `INSTAGRAM_REEL_URL` from `.env`:

```bash
go run single_url.go
```

Or pass a URL directly:

```bash
go run single_url.go "https://www.instagram.com/reel/your_reel_id/"
```

Output is saved to:

```text
sample-output/generated/go-single-url-response.json
```

## Run batch CSV processing

Use the default CSV:

```bash
go run batch_csv.go
```

Or pass a custom CSV path:

```bash
go run batch_csv.go path/to/urls.csv
```

The CSV must include a `videoUrl` column.

Batch processing calls the Actor once per URL and may generate billable Apify usage. `MAX_CONCURRENCY` defaults to `3`; higher concurrency can increase cost and rate-limit risk.

Batch outputs are saved to:

```text
sample-output/generated/go-batch-results.jsonl
sample-output/generated/go-batch-errors.csv
```

## Security

Do not hard-code `APIFY_TOKEN` or `INSTAGRAM_SESSIONID`. Keep secrets in `.env` or your deployment secret manager, and never commit `.env`.
