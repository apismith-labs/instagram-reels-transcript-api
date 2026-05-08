# Batch processing guide

This repository will include batch CSV examples for cURL, Python, Node.js, Java, and Go.

## Input CSV

Use `sample-data/instagram-reel-urls.csv` as the starting format:

```csv
videoUrl
https://www.instagram.com/reel/your_reel_id/
```

Each row should contain one Instagram Reel URL.

## Planned batch workflow

Each major language example will show how to:

1. Load Reel URLs from CSV.
2. Validate that each row contains a non-empty `videoUrl`.
3. Submit each URL to the Apify Actor `apple_yang/instagram-transcripts-scraper`.
4. Collect transcript results.
5. Record failed rows with the returned `errMsg` or client-side error.
6. Write structured output to `sample-output/`.

## Recommended output shape

For batch processing, keep one result object per input URL. Include the original row number or source URL so failed records can be traced back to the CSV.

Suggested fields for normalized batch output:

- `sourceUrl`
- `status`
- `text`
- `segments`
- `errMsg`
- `raw`

## Operational notes

Batch jobs should avoid hard-coded credentials. Read `APIFY_TOKEN` from the environment and keep `.env` out of version control.

For larger CSV files, add rate limiting, retries, checkpointing, and resumable output so a failed run does not require starting from the beginning.
