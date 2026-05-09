# Use Instagram Reels Transcript API with Node.js

These examples show how to call the Apify Actor `apple_yang/instagram-transcripts-scraper` with the official Apify JavaScript API client.

## What the examples do

- `single-url.mjs` runs the Actor for one Instagram Reel URL.
- `batch-csv.mjs` reads Reel URLs from CSV and calls the Actor once per URL.
- Both examples load `.env` from the repository root.
- Both examples save output under `sample-output/generated/`.

## Setup

From this directory:

```bash
npm install
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

Optionally set `INSTAGRAM_SESSIONID` if your integration requires it. Never commit `.env` or real tokens.

## Run a single URL

Pass the Reel URL as runtime input:

```bash
node single-url.mjs "https://www.instagram.com/reel/your_reel_id/"
```

`INSTAGRAM_REEL_URL` is still accepted as an environment fallback, but do not put business input in `.env` for normal usage.

Output is saved to:

```text
sample-output/generated/nodejs-single-url-response.json
```

## Run batch CSV processing

Use the default CSV:

```bash
node batch-csv.mjs
```

Or pass a custom CSV path:

```bash
node batch-csv.mjs path/to/urls.csv
```

The CSV must include a `videoUrl` column.

Batch processing calls the Actor once per URL and may generate billable Apify usage. `MAX_CONCURRENCY` defaults to `3`; higher concurrency can increase cost and rate-limit risk.

Batch outputs are saved to:

```text
sample-output/generated/nodejs-batch-results.jsonl
sample-output/generated/nodejs-batch-errors.csv
```

## Security

Do not hard-code `APIFY_TOKEN` or `INSTAGRAM_SESSIONID`. Keep secrets in `.env` or your deployment secret manager, and never commit `.env`.
