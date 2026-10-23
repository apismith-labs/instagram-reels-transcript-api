# Batch processing guide

There are two very different ways to process more than one Instagram URL with this Actor, and
they are easy to confuse. This guide describes both, and states exactly what the examples in
this repository do today.

| Approach | How many Actor Runs | Implemented here |
| --- | --- | --- |
| **CSV, one Run per URL** (`url` / `videoUrl` per row) | One Run per CSV row | Yes — Python, Node.js, Go (requires explicit `--execute`), and Java (plan-only by default; requires `--execute`) |
| **Native bulk** (`bulkUrls`, many URLs in one Run) | One Run for many URLs | Yes — Python, Node.js, Go, and Java |

CSV Batch and Native Bulk are separate modes. CSV Batch creates one Run per non-empty CSV row;
Native Bulk sends a `bulkUrls` array in one Run. See the [Python](../examples/python/README.md),
[Node.js](../examples/nodejs/README.md), [Go](../examples/go/README.md), and [Java](../examples/java/README.md) guides.

Native bulk is also not automatically cheaper or faster — it changes how many Runs you start and
how results are mapped back to inputs, and its real performance has not been measured here.

## CSV batch: one Run per URL

### Input format

Use `sample-data/instagram-reel-urls.csv` as a starting point and pass its path explicitly:

```csv
videoUrl
https://www.instagram.com/reel/your_reel_id/
https://www.instagram.com/p/your_post_id/
```

- One URL per row. Python/Node.js use the documented `videoUrl` header; Go accepts `url` or
  `videoUrl` to support the existing sample CSV.
  A file without that column is rejected.
- Python and Go read UTF-8 and tolerate a BOM. Node.js reads it as UTF-8 with a
  line-based parser: quoted fields containing embedded newlines are **not** supported.
- Empty rows are skipped. A non-empty row with a blank or invalid URL is rejected before any Run.
- The CSV line number (2 for the first data row) becomes the `rowId`, so duplicate URLs remain
  traceable to their input row. Nothing is deduplicated for you.

### How the work is dispatched

- Each row creates its own Actor Run with a single-URL input (`videoUrl`). Python/Node.js may add
  their documented `sessionid` option; the Go CLI does not use it. Java may add its explicitly configured `sessionid` only to the single-URL Actor input.
- `MAX_CONCURRENCY` (default `3`) bounds how many Runs are in flight at once. Higher values mean
  more simultaneous billable Runs and more rate-limit exposure.
- Python and Node.js run rows in parallel; result order in their output files may not match CSV order, which is why `rowId` exists.
- Go and Java execute rows serially and preserve input order.

### Commands

```bash
python examples/python/batch_csv.py "sample-data/instagram-reel-urls.csv"
node examples/nodejs/batch-csv.mjs "sample-data/instagram-reel-urls.csv"
(cd examples/go && go run ./cmd/batch-csv --dry-run ../../sample-data/instagram-reel-urls.csv)
(cd examples/java && java -jar target/instagram-reels-transcript-api-java-examples-0.1.0-shaded.jar csv ../../sample-data/instagram-reel-urls.csv)
(cd examples/java && java -jar target/instagram-reels-transcript-api-java-examples-0.1.0-shaded.jar csv ../../sample-data/instagram-reel-urls.csv --execute --require-charge-cap --max-total-charge-usd 0.10)
```

The CSV path is required for every command. There is no implicit sample-file fallback. Use
`--dry-run` to validate the file and display the planned number of independent Runs without creating
them. Go and Java default to a zero-Run plan; `--execute` is required before either CLI reads the token or starts one independent Run per row. Java `--execute` also requires a positive per-Run cap from `--max-total-charge-usd` or `APIFY_MAX_TOTAL_CHARGE_USD`. The Java example includes `--require-charge-cap` as an explicit guard; the positive cap is still required even without that flag. Java also accepts `url` or `videoUrl` headers.

### Result statuses

Every row gets exactly one of the eight statuses defined in
[error-handling-and-retries.md](error-handling-and-retries.md): `success`, `actor_error`,
`empty`, `no_transcript`, `unknown`, `transport_error`, `run_failed`, `creation_unknown`.

Python/Node.js summaries expose their documented status counts; Go JSON contains per-row status,
Run ID, Dataset ID, transcript, segments, raw Actor items, error, and aggregate counts. Summaries include:

- `processed` — total rows processed;
- `failed` — `processed - success`.

Only `success` means a transcript was produced. An HTTP 200 with a non-empty `errMsg` is
`actor_error`, not a success.

### Output files

| File | Contents |
| --- | --- |
| Python result JSON | Unique `python-batch-results-<UTC timestamp>.json` name beside the supplied CSV by default (or the explicit `--output` path); contains each row's status and result items |
| Node.js result JSONL | Unique `nodejs-batch-results-<UUID>.jsonl` under `sample-output/generated/`; one sanitised result object per row |
| Node.js errors CSV | Unique `nodejs-batch-errors-<UUID>.csv` under `sample-output/generated/`; failure rows use `rowId,sourceUrl,runId,status,error` |
| Go result JSON | Unique `go-csv-batch-<UTC timestamp>-<suffix>.json` under `sample-output/generated/`; retains per-row results and original Actor items |
| Python journal | `python-run-journal.jsonl` beside the result JSON (by default, beside the supplied CSV); append-only stage records |
| Node.js journal | `sample-output/generated/nodejs-run-journal.jsonl`; append-only stage records |

Generated result and error filenames are unique; the examples do not overwrite an earlier batch
result. Python stores failures in the result JSON rather than writing a separate errors CSV.

### Run ID records and recovery boundaries

- The Run ID of every row is written to the JSONL journal as soon as the Run is created, before
  polling and before the result file is written. The journal file is created with owner-only
  permissions (`0600`).
- A Run is created **at most once** per row. If polling or the Dataset read fails afterwards, recovery reads the same Run; it does not create a new one. Java does not automatically retry creation POSTs.
- If the POST outcome is unknown (timeout, dropped connection, unparsable 5xx body), the row is
  marked `creation_unknown` and no retry is attempted. Reconcile against your Apify run history
  first.
- `--resume RUN_ID` is available for Python Single URL and Go Single URL/Native Bulk when the
  exact original input and matching Journal record are supplied. Go Resume performs GET-only
  recovery; it does not support CSV checkpointing or Profile Resume.
- Failed rows are not retried automatically beyond the transport-level retries described in the
  error handling guide. Re-running the same CSV re-submits every row, which means paying again
  for rows that already succeeded.

### Operational notes

- Python/Node.js configuration may use their documented environment and dotenv behavior. Go reads
  `APIFY_TOKEN`, Actor/Build, and charge settings from the process environment only; it never loads
  `.env`.
- Instagram URLs are runtime input: single-URL scripts take them as a CLI argument, batch scripts
  read them from a CSV file.
- Batch processing is billable per row. Estimate cost before running a large file, and start with
  a small slice.
- For larger jobs, add your own rate limiting and checkpointing around these scripts; the current
  examples keep results in memory until the end of the batch and do not implement a resumable
  queue.

## Native bulk (`bulkUrls`)

Python, Node.js, and Go support Native Bulk: several Reel URLs are sent together in one Actor Run.
This differs from CSV Batch, where each non-empty row creates a separate Run. See the
language-specific guides linked above for current input limits, output mapping, and remaining
validation boundaries. Native Bulk is not claimed to be cheaper or faster here.

## Related

- [Error handling and retries](error-handling-and-retries.md) — statuses, exit codes, retry rules.
- [Input and output fields](input-output-fields.md) — per-mode fields and their unknowns.
- [Python examples](../examples/python/README.md) · [Node.js examples](../examples/nodejs/README.md) · [Go examples](../examples/go/README.md) · [Java examples](../examples/java/README.md)
