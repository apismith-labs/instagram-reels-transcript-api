# Batch processing guide

This guide outlines the planned batch processing approach for the examples in this repository.

This phase is scaffold only. Runnable batch examples will be added in the next phase.

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

For batch processing, keep one result object per input URL. Include the source URL so failed records can be traced back to the CSV.

Suggested normalized fields:

- `sourceUrl`
- `status`
- `text`
- `segments`
- `errMsg`
- `raw`

## Operational notes

Batch jobs should read `APIFY_TOKEN` from the environment.

For larger CSV files, add rate limiting, retries, checkpointing, and resumable output so a failed run does not require starting from the beginning.
