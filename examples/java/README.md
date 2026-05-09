# Use Instagram Reels Transcript API with Java

These examples show how to call the Apify Actor `apple_yang/instagram-transcripts-scraper` from Java using OkHttp, Jackson, and dotenv-java.

## Requirements

- Java 17
- Maven

## Setup

From this directory:

```bash
mvn compile
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

Optionally set `INSTAGRAM_SESSIONID` if your integration requires it. Never commit `.env`.

## Run a single URL

Pass the Reel URL as runtime input:

```bash
mvn exec:java -Dexec.mainClass=com.apismith.instagram.SingleUrl -Dexec.args="https://www.instagram.com/reel/your_reel_id/"
```

`INSTAGRAM_REEL_URL` is still accepted as an environment fallback, but do not put business input in `.env` for normal usage.

Output is saved to:

```text
sample-output/generated/java-single-url-response.json
```

## Run batch CSV processing

Use the default CSV:

```bash
mvn exec:java -Dexec.mainClass=com.apismith.instagram.BatchCsv
```

Or pass a custom CSV path:

```bash
mvn exec:java -Dexec.mainClass=com.apismith.instagram.BatchCsv -Dexec.args="path/to/urls.csv"
```

The CSV must include a `videoUrl` column.

Batch processing calls the Actor once per URL and may generate billable Apify usage. `MAX_CONCURRENCY` defaults to `3`; higher concurrency can increase cost and rate-limit risk.

Batch outputs are saved to:

```text
sample-output/generated/java-batch-results.jsonl
sample-output/generated/java-batch-errors.csv
```

## Security

Do not hard-code `APIFY_TOKEN` or `INSTAGRAM_SESSIONID`. Keep secrets in `.env` or your deployment secret manager, and never commit `.env`.
