# Use Instagram Reels Transcript API with Node.js

These examples show how to call the Apify Actor
`apple_yang/instagram-transcripts-scraper` from Node.js using the **built-in global `fetch`**
plus `dotenv` for local configuration. They do **not** use the Apify JavaScript SDK — Run
creation, Run polling, and Dataset reads are explicit REST calls, because the reliability
behaviour below depends on controlling each stage separately. `p-limit` is used only to bound
batch concurrency.

**Verified scope.** On Actor Build `0.0.50`, Node.js has recorded live success for the single-URL
path and one Native Bulk Run using the three fixed Reel URLs in the TC02 fixture; all three bulk
results succeeded. This does not verify arbitrary bulk sizes, mixed success/failure cases, CSV
Batch against live URLs, Profile inputs, MCP clients, or the newer `enhancedcrawl` option. Build
`0.0.51` and later Builds are also outside this evidence. Python has separate live acceptance
records; they do not expand the Node.js evidence described here.

## What the examples do

- `single-url.mjs` — runs the Actor for one Instagram URL and reports a classified result.
- `native-bulk.mjs` — sends the repository's TC02 fixture as one Actor-native Bulk Run.
- `batch-csv.mjs` — reads URLs from a CSV and runs **one Actor Run per row**.
- `reliable-actor.mjs` — shared staged runner: REST transport, business-status classification,
  retry policy, JSONL journal, and result sanitisation. Importing it performs no I/O.
- All scripts load `.env` from the repository root.
- Results are written under `sample-output/generated/`.

### How the calls are made

| Stage | Implementation |
| --- | --- |
| Create Run | `POST https://api.apify.com/v2/acts/{owner~name}/runs` with `Authorization: Bearer <token>` |
| Poll Run | `GET /v2/actor-runs/{runId}` until `SUCCEEDED` / `FAILED` / `TIMED-OUT` / `ABORTED` |
| Read Dataset | `GET /v2/datasets/{datasetId}/items` (first page; an empty response is rechecked twice on the same Dataset) |
| Journal | One JSON line appended per stage to `sample-output/generated/nodejs-run-journal.jsonl`, file mode `0600` |
| Recovery | `--resume RUN_ID` re-reads the journal and re-polls the **existing** Run; it never re-creates one |

Run creation, polling, and Dataset reads are three separate stages with separate retry rules: a
failure after the Run exists only re-reads that Run. See
[../../docs/error-handling-and-retries.md](../../docs/error-handling-and-retries.md).

## Setup

Requires Node.js 18 or newer (the examples rely on the global `fetch`).

Run the install **inside `examples/nodejs`**, so npm picks up the lockfile that sits next to
`package.json`:

```bash
cd examples/nodejs
npm ci --ignore-scripts --no-audit --no-fund
cd ../..
```

`npm ci` installs exactly the versions pinned in `package-lock.json` (`dotenv 16.6.1`,
`p-limit 6.2.0`, `yocto-queue 1.2.2`) and refuses to modify it; `--ignore-scripts` skips package
lifecycle scripts (none of the three dependencies define one). Use `npm install` only when you
intend to change dependency ranges.

The lockfile pins `resolved` URLs to `registry.npmmirror.com`. That is a mirror, not the default
npm registry, so installs from another network must be able to reach it; if it is unreachable,
regenerate the lockfile against a registry you can reach instead of editing it by hand.

## Configure `.env`

From the repository root, create the file only if it does not already exist, so you never
overwrite your own settings:

```bash
test -f .env || cp .env.example .env
```

Then edit `.env`:

```bash
APIFY_TOKEN='your_apify_token_here'
APIFY_ACTOR_ID='apple_yang/instagram-transcripts-scraper'
INSTAGRAM_SESSIONID=''
MAX_CONCURRENCY=3
```

| Variable | Required | Used by | Notes |
| --- | --- | --- | --- |
| `APIFY_TOKEN` | Yes | all scripts | Sent as a Bearer header, never in a URL |
| `APIFY_ACTOR_ID` | No | all scripts | Defaults to `apple_yang/instagram-transcripts-scraper` |
| `INSTAGRAM_SESSIONID` | No | all scripts | Omitted when blank; explicitly set values are forwarded, but runtime effect is unverified |
| `MAX_CONCURRENCY` | No | `batch-csv.mjs` | Defaults to `3`; must parse as a positive integer or the script exits `2` |
| `INSTAGRAM_REEL_URL` | No | `single-url.mjs` | Fallback when no URL argument is given; prefer the CLI argument |
| `APIFY_MAX_TOTAL_CHARGE_USD` | No | all Node.js runners | Optional positive per-Run USD charge limit, sent as a Run API query option |
| `APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD` | No | all Node.js runners | Set to `1` to fail closed before POST when the limit is missing or invalid; use for approved controlled tests |
| `APIFY_BUILD` | No | all Node.js runners | Explicit numeric Build number (for example `0.0.50`). Tags such as `latest` are rejected. Sent as a Run API query option, never as Actor input |
| `APIFY_REQUIRE_BUILD` | No | all Node.js runners | Set to `1` to require `APIFY_BUILD` and to accept only the pinned Build `0.0.50`; the created Run's `buildNumber`/`buildId` must then match or the run is not accepted |

Quote values that contain special characters such as `&` or `?`. Never commit `.env` or real
tokens.

For a controlled test, set `APIFY_MAX_TOTAL_CHARGE_USD` to the approved per-Run limit and
`APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD=1`. The cap is a Run option, not Actor input. An API
rejection stops that attempt; the runner never retries the creation POST without the limit.
The platform may enforce an Actor-configured minimum, and the final charge can slightly
overshoot while a capped run is being stopped; verify both before treating a cap as a hard
budget guarantee.

## Run a single URL

Pass a **bare** public Instagram URL — no Markdown link syntax, no surrounding `[text](url)`, no
quotes copied from a rendered chat message. The argument is forwarded verbatim as the Actor's
`videoUrl`, so a wrapped value is sent as-is and fails as an invalid URL.

```bash
node examples/nodejs/single-url.mjs "https://www.instagram.com/reel/your_reel_id/"
```

The script prints one JSON line with `rowId`, `sourceUrl`, `runId`, `datasetId`, `status`, and
`error` (absent values are printed as `null`), and writes the sanitised Dataset items to:

```text
sample-output/generated/nodejs-single-url-response.json
```

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | `success` — at least one item has non-empty transcript text and no `errMsg` |
| `2` | Configuration or argument error (missing token, missing URL, unknown Run ID) |
| `4` | `actor_error` — the Actor returned a non-empty `errMsg` |
| `5` | `empty` — the Dataset contained no items |
| `6` | `no_transcript` — items exist but no transcript text |
| `7` | `unknown` — unexpected structure or unsupported text type |
| `8` | `transport_error` — API/network failure or overall deadline exceeded |
| `9` | `run_failed` — the Run ended `FAILED`, `TIMED-OUT`, or `ABORTED` |
| `10` | `creation_unknown` — the POST outcome is unknown; reconcile before retrying |

Only exit code `0` means a transcript was produced.

## Run the Native Bulk example

`native-bulk.mjs` reads `tests/fixtures/live/tc02-native-bulk.json` and sends its three `bulkUrls`
in one Actor Run. With the required environment configured, run:

```bash
node examples/nodejs/native-bulk.mjs
```

This command creates one Actor Run. The script also accepts `--resume RUN_ID` to recover a Run
already recorded in the Node.js journal; it does not accept URL arguments or split the fixture
into multiple Runs. The recorded live success covers only those three fixed URLs on Build
`0.0.50`; arbitrary sizes and mixed outcomes remain unverified.

## Resume an existing Run

```bash
node examples/nodejs/single-url.mjs --resume RUN_ID
```

This looks the Run up in `sample-output/generated/nodejs-run-journal.jsonl`, verifies its Actor
ID and input association, reuses its `sourceUrl` and `datasetId`, and issues **no** new
Run-creation request. If the journal is missing, mismatched, or corrupt, the script exits with
code `2`. Each call is bounded by a 15-minute overall deadline.

## Run batch CSV processing

```bash
node examples/nodejs/batch-csv.mjs                        # uses sample-data/instagram-reel-urls.csv
node examples/nodejs/batch-csv.mjs path/to/urls.csv       # or your own file
```

- The CSV must contain a `videoUrl` column; rows with an empty value are skipped.
- **Each row creates its own Actor Run.** This is not the Actor's native `bulkUrls` mode.
- `MAX_CONCURRENCY` bounds how many Runs are in flight at once (default `3`). Higher values
  increase cost and rate-limit exposure.
- The CSV line number is kept as `rowId`, so duplicate URLs are still traceable to the input row.
- The CSV reader is deliberately simple and line-based: quoted fields containing embedded
  newlines are not supported. One URL per line is the supported format.

Outputs:

```text
sample-output/generated/nodejs-batch-results.jsonl   # one sanitised result per row
sample-output/generated/nodejs-batch-errors.csv      # rowId, sourceUrl, runId, status, error
```

The script prints a JSON summary containing every status count plus `processed` and `failed`,
where `failed = processed - success`. Exit code is `0` when every row succeeded, `1` when at
least one row did not, and `2` for configuration errors.

**CSV Batch has no `--resume`.** `single-url.mjs` and `native-bulk.mjs` support resuming a specific Run recorded in the journal.

## Security

Do not hard-code `APIFY_TOKEN` or `INSTAGRAM_SESSIONID`. Keep secrets in `.env` or your
deployment secret manager, and never commit `.env`. Persisted results pass through a sanitiser
that drops credential-like keys and redacts common credential assignments. Journal and result
files use owner-only `0600` permissions, but stored Actor output should still be treated as sensitive.

## Verifying behaviour offline

The repository's tests exercise these code paths without network access or credentials:

```bash
node --test tests/node/*.test.mjs
```
