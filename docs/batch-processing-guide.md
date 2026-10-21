# Batch processing guide

There are two very different ways to process more than one Instagram URL with this Actor, and
they are easy to confuse. This guide describes both, and states exactly what the examples in
this repository do today.

| Approach | How many Actor Runs | Implemented here |
| --- | --- | --- |
| **CSV, one Run per URL** (`videoUrl` per row) | One Run per CSV row | Yes — Python and Node.js (Java, Go, Rust experimental) |
| **Native bulk** (`bulkUrls`, many URLs in one Run) | One Run for many URLs | **No** — planned as V2.1 `B01` |

The native mode is not implemented in this repository yet. Anything in this repository that says
"batch" refers to the first row of the table. Do not describe the CSV examples as using
`bulkUrls`; they do not.

Native bulk is also not automatically cheaper or faster — it changes how many Runs you start and
how results are mapped back to inputs, and its real performance has not been measured here.

## CSV batch: one Run per URL

### Input format

Use `sample-data/instagram-reel-urls.csv` as the starting point:

```csv
videoUrl
https://www.instagram.com/reel/your_reel_id/
https://www.instagram.com/p/your_post_id/
```

- One URL per row, under a `videoUrl` column header. A file without that column is rejected.
- Python reads the file as UTF-8 and tolerates a BOM. Node.js reads it as UTF-8 with a
  line-based parser: quoted fields containing embedded newlines are **not** supported.
- Rows whose `videoUrl` value is empty are skipped, not counted as failures.
- The CSV line number (2 for the first data row) becomes the `rowId`, so duplicate URLs remain
  traceable to their input row. Nothing is deduplicated for you.

### How the work is dispatched

- Each row creates its own Actor Run with a single-URL input (`videoUrl`, plus `sessionid` when
  configured).
- `MAX_CONCURRENCY` (default `3`) bounds how many Runs are in flight at once. Higher values mean
  more simultaneous billable Runs and more rate-limit exposure.
- Both language examples run the rows in parallel; result order in the output files may not match
  CSV order, which is why `rowId` exists.

### Commands

```bash
python examples/python/batch_csv.py [path/to/urls.csv]
node examples/nodejs/batch-csv.mjs [path/to/urls.csv]
```

With no argument, both use `sample-data/instagram-reel-urls.csv`.

### Result statuses

Every row gets exactly one of the eight statuses defined in
[error-handling-and-retries.md](error-handling-and-retries.md): `success`, `actor_error`,
`empty`, `no_transcript`, `unknown`, `transport_error`, `run_failed`, `creation_unknown`.

The printed summary contains a count for each status plus:

- `processed` — total rows processed;
- `failed` — `processed - success`.

Only `success` means a transcript was produced. An HTTP 200 with a non-empty `errMsg` is
`actor_error`, not a success.

### Output files

| File | Contents |
| --- | --- |
| `sample-output/generated/python-batch-results.jsonl` (or `nodejs-batch-results.jsonl`) | One sanitised result object per row, including `rowId`, `sourceUrl`, `runId`, `datasetId`, `status`, `error`, and the raw items |
| `sample-output/generated/python-batch-errors.csv` (or `nodejs-batch-errors.csv`) | Failure list with the columns `rowId,sourceUrl,runId,status,error` — business failures are included |
| `sample-output/generated/python-run-journal.jsonl` (or `nodejs-run-journal.jsonl`) | Append-only stage journal, one JSON line per state transition |

### Run ID records and recovery boundaries

- The Run ID of every row is written to the JSONL journal as soon as the Run is created, before
  polling and before the result file is written. The journal file is created with owner-only
  permissions (`0600`).
- A Run is created **at most once** per row. If polling or the Dataset read fails afterwards, the
  retry re-reads the same Run; it does not create a new one.
- If the POST outcome is unknown (timeout, dropped connection, unparsable 5xx body), the row is
  marked `creation_unknown` and no retry is attempted. Reconcile against your Apify run history
  first.
- **`--resume RUN_ID` is only available on the single-URL scripts** (`single_url.py`,
  `single-url.mjs`). The CSV batch scripts accept no resume flag and cannot restart from a
  chosen Run. If a batch dies part-way, the journal still holds the Run IDs and Dataset IDs, so
  you can re-read individual Runs with the single-URL scripts, but there is no batch-level
  checkpoint or replay.
- Failed rows are not retried automatically beyond the transport-level retries described in the
  error handling guide. Re-running the same CSV re-submits every row, which means paying again
  for rows that already succeeded.

### Operational notes

- Configuration (`APIFY_TOKEN`, `APIFY_ACTOR_ID`, optional `INSTAGRAM_SESSIONID`,
  `MAX_CONCURRENCY`) is read from the environment or the repository-root `.env`.
- Instagram URLs are runtime input: single-URL scripts take them as a CLI argument, batch scripts
  read them from a CSV file.
- Batch processing is billable per row. Estimate cost before running a large file, and start with
  a small slice.
- For larger jobs, add your own rate limiting and checkpointing around these scripts; the current
  examples keep results in memory until the end of the batch and do not implement a resumable
  queue.

## Native bulk (`bulkUrls`) — not implemented here

The Actor exposes a `bulkUrls` input that processes several URLs inside a single Run. That mode
is planned for this repository as task `B01` and **no example in this repository uses it yet**.

What is known and unknown about it at this point:

- It is a different input mode from the CSV flow above: one Run, many URLs, rather than many
  Runs. Switching modes changes how you map results back to inputs.
- Result ordering, partial-failure shape, duplicate-URL handling, and the exact input-to-output
  mapping are **unverified**. Until `B01` lands, do not assume that output index `n` corresponds
  to input URL `n`.
- A per-Run URL cap on the free plan is documented by the Actor; treat published plan limits as
  changeable and verify them against your own account before relying on them.
- Native bulk is not claimed to be cheaper or faster here.

When `B01` is implemented, this section will be replaced by a real example; until then the CSV
flow is the only batch path in this repository.

## Related

- [Error handling and retries](error-handling-and-retries.md) — statuses, exit codes, retry rules.
- [Input and output fields](input-output-fields.md) — per-mode fields and their unknowns.
- [Python examples](../examples/python/README.md) · [Node.js examples](../examples/nodejs/README.md)
