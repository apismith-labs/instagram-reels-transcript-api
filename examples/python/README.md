# Use Instagram Reels Transcript API with Python

These examples show how to call the Apify Actor `apple_yang/instagram-transcripts-scraper` with the official Apify Python API client.

## What the examples do

- `single_url.py` runs the Actor for one Instagram Reel URL.
- `batch_csv.py` reads Reel URLs from CSV and calls the Actor once per URL.
- Both examples load `.env` from the repository root.
- Both examples save raw output under `sample-output/generated/`.

## Setup

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r examples/python/requirements.txt
```

## Configure `.env`

```bash
cp .env.example .env
```

Edit `.env` and set your Apify token and Reel URL:

```bash
APIFY_TOKEN='your_apify_token_here'
INSTAGRAM_REEL_URL='https://www.instagram.com/reel/your_reel_id/'
```

Quote values that contain special characters such as `&` or `?`.

Optionally set `INSTAGRAM_SESSIONID` if your integration requires it. Never commit `.env` or real tokens.

## Run a single URL

Use `INSTAGRAM_REEL_URL` from `.env`:

```bash
python examples/python/single_url.py
```

Or pass a URL directly:

```bash
python examples/python/single_url.py "https://www.instagram.com/reel/your_reel_id/"
```

Output is saved to:

```text
sample-output/generated/python-single-url-response.json
```

## Run batch CSV processing

Use the default CSV:

```bash
python examples/python/batch_csv.py
```

Or pass a custom CSV path:

```bash
python examples/python/batch_csv.py path/to/urls.csv
```

The CSV must include a `videoUrl` column.

Batch processing calls the Actor once per URL and may generate billable Apify usage. `MAX_CONCURRENCY` defaults to `3`; higher concurrency can increase cost and rate-limit risk.

Batch outputs are saved to:

```text
sample-output/generated/python-batch-results.jsonl
sample-output/generated/python-batch-errors.csv
```

## Security

Do not hard-code `APIFY_TOKEN` or `INSTAGRAM_SESSIONID`. Keep secrets in `.env` or your deployment secret manager, and never commit `.env`.
