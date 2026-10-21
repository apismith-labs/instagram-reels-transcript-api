# Use Instagram Reels Transcript API with Python

These examples target Python 3.10+ and show how to call the Apify Actor
`apple_yang/instagram-transcripts-scraper` from Python using **plain HTTP requests from the
standard library** (`urllib.request`) plus `python-dotenv` for local configuration. They do
**not** use the Apify Python SDK — Run creation, Run polling, and Dataset reads are explicit REST
calls, because the reliability behaviour below depends on controlling each stage separately.

## What the examples do

- `single_url.py` — runs the Actor for one explicitly supplied Instagram URL and reports a classified result.
- `batch_csv.py` — reads an explicitly supplied CSV and runs **one Actor Run per non-empty row**.
- `client.py` — reusable `get_transcript()`, `get_transcripts()`, and `get_profile_posts()` functions.
- `quickstart_single.py`, `quickstart_bulk.py`, `quickstart_profile.py` — CLI examples for the three Actor input modes.
- `reliable_actor.py` — shared staged runner: REST transport, business-status classification,
  retry policy, JSONL journal, and result sanitisation. It performs no I/O at import time.
- `single_url.py` can load `.env` for local configuration. The reusable API, Quick Starts, and CSV Batch do not load `.env`; they read `APIFY_TOKEN` from the process environment when a call is made.
- Single URL CLI output and its journal use `sample-output/generated/`. CSV Batch writes a unique result beside the explicitly supplied CSV unless `--output` is set; its journal is created beside that result.

### How the calls are made

| Stage | Implementation |
| --- | --- |
| Create Run | `POST https://api.apify.com/v2/acts/{owner~name}/runs` with `Authorization: Bearer <token>` |
| Poll Run | `GET /v2/actor-runs/{runId}` until `SUCCEEDED` / `FAILED` / `TIMED-OUT` / `ABORTED` |
| Read Dataset | `GET /v2/datasets/{datasetId}/items` (first page; an empty response is rechecked twice on the same Dataset) |
| Journal | One JSON line appended per stage; Single URL uses `sample-output/generated/python-run-journal.jsonl`, CSV Batch uses the result directory |
| Recovery | `--resume RUN_ID` re-reads the journal and re-polls the **existing** Run; it never re-creates one |

Run creation, polling, and Dataset reads are three separate stages with separate retry rules: a
failure after the Run exists only re-reads that Run. See
[../../docs/error-handling-and-retries.md](../../docs/error-handling-and-retries.md).

## Setup

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r examples/python/requirements.txt
```

`python-dotenv` is used by the legacy `single_url.py` CLI and the read-only Usage helper; install
the listed requirement when using those tools. The reusable `client.py` and `reliable_actor.py`
pair, Quick Starts, and CSV Batch use only the Python standard library. No Apify SDK is used.

## Reusable Python API

`get_transcript()` is the direct function interface for applications. Set the token in the
process environment, then call the function with one explicit Reel URL:

```bash
export APIFY_TOKEN='your_apify_token_here'
python examples/python/quickstart_single.py --help
python examples/python/quickstart_single.py 'https://www.instagram.com/reels/your_reel_id/'
```

In Python code:

```python
from examples.python.client import get_transcript

result = get_transcript('https://www.instagram.com/reels/your_reel_id/')
if result.status == 'success':
    print(result.text)
    print(f'{len(result.segments)} segments')
else:
    print(result.status, result.error)

original_item = result.items[0] if result.items else {}
```

For copy-based integration, copy **both** `client.py` and `reliable_actor.py` into the same
directory in your application and import `from client import get_transcript`. The import works
from a different working directory and does not depend on this repository's paths. The reusable
API does not read `.env` automatically; a host application may load its own environment file
before calling it. An explicit `token=` argument takes precedence over `APIFY_TOKEN`.

The returned `TranscriptResult` has these fields:

| Field | Meaning |
| --- | --- |
| `status` | `success`, `actor_error`, `empty`, `no_transcript`, `unknown`, or `run_failed` for ordinary outcomes |
| `text` | Transcript text when available; otherwise `None` |
| `segments` | Transcript segment list, or an empty list |
| `items` | Original Actor Dataset items, including metadata fields such as title, duration, timestamp, and unknown fields |
| `run_id` / `dataset_id` | IDs for the created Run and its Dataset |
| `source_url` | The URL passed to the function |
| `error` | Business error detail, or `None` |
| `dataset_complete` | `False` when the configured page limit may have truncated the Dataset; otherwise `True` when known |
| `succeeded` | Convenience property equivalent to `status == 'success'` |

Configuration problems (bad URL, missing token, invalid Build, timeout, or charge-cap settings)
raise `ConfigurationError`. A malformed or Build-mismatched result raises `ProtocolError` and
includes known Run/Dataset IDs. A definite retrieval failure raises `TranscriptTransportError`;
if a Run ID is available, inspect that existing Run before making another call. An ambiguous
Run-creation outcome raises `CreationUnknownError`; do not blindly retry it. Actor business
outcomes such as `actor_error`, `empty`, `no_transcript`, and `run_failed` are returned as result
statuses rather than raised exceptions.

Build defaults to the approved `0.0.50` and is verified against Build ID
`aJLRmMdQapLQRT4sJ`. An optional `max_total_charge_usd=` applies to one Run; set
`require_charge_cap=True` to fail before creation if the cap is absent. The reusable API uses an
in-memory journal by default and creates no audit files. Pass a journal explicitly only when the
calling application wants to persist recovery records.

### CLI and function interface

`quickstart_single.py` and `single_url.py` are command-line examples: they parse arguments, print
human-readable output, and return process exit codes. `get_transcript()` is for imported
application code: it accepts normal Python values, returns a `TranscriptResult`, and raises
specific exceptions for configuration, protocol, transport, or ambiguous-creation problems.
Neither interface takes a URL from `.env` implicitly.

## Native Bulk (one Run for multiple URLs)

`get_transcripts()` sends every URL as one Actor-native `bulkUrls` input in **one** Run. It does
not call `get_transcript()` repeatedly and does not use the CSV Batch orchestrator. Configure the
token in your process environment, then pass two or more explicit URLs to the quickstart:

macOS/Linux:

```bash
export APIFY_TOKEN="YOUR_TOKEN"
python3 examples/python/quickstart_bulk.py \
  "https://www.instagram.com/reels/first_reel/" \
  "https://www.instagram.com/reels/second_reel/"
```

Windows PowerShell:

```powershell
$env:APIFY_TOKEN = "YOUR_TOKEN"
py examples/python/quickstart_bulk.py `
  "https://www.instagram.com/reels/first_reel/" `
  "https://www.instagram.com/reels/second_reel/"
```

Use `--help` to see optional flags. The quickstart has no default URL and sends no request when
arguments are missing. Optional booleans take explicit `true` or `false` values, for example
`--skip-pinned-posts false`. From application code:

```python
from examples.python.client import get_transcripts

result = get_transcripts(
    ["https://www.instagram.com/reels/first_reel/",
     "https://www.instagram.com/reels/second_reel/"],
    results_limit=12,
    skip_pinned_posts=False,
    include_shares_count=False,
)
for item in result.results:
    print(item.url, item.status, item.text)
    if item.status == "actor_error":
        print(item.error)
```

`get_transcripts()` accepts `urls` plus keyword options `token`, `actor_id`, `build`, `timeout`,
`max_total_charge_usd`, `require_charge_cap`, `dataset_limit`, `results_limit`,
`skip_pinned_posts`, `include_shares_count`, and injectable `transport` / `journal` seams. URLs
must be bare HTTPS Instagram Reel URLs, with no query, fragment, Markdown syntax, duplicates,
or ambiguous repeated shortcode. Actor options are passed in camelCase (`resultsLimit`,
`skipPinnedPosts`, `includeSharesCount`); they are omitted unless supplied.

`BulkResult` contains `status`, per-input `results`, `extra_results`, `run_id`, `dataset_id`,
`dataset_complete`, `counts`, `raw_items`, and `error`. Each per-input `BulkItemResult` contains
`url`, `status`, `text`, `segments`, original mapped `items`, and `error`. Per-item statuses are
`success_transcript`, `actor_error`, `no_transcript`, `missing_result`, `duplicate_result`, or
`unknown`. A success remains readable in a partial result. Overall status is `all_success` only
when every input has one successful mapping and the Dataset is known complete; otherwise it is
`partial_success`, `all_failed`, or `unknown`. Unmapped output items are preserved in
`extra_results` and `raw_items`.

The Runner explicitly requests one Dataset page (`dataset_limit`, default 100). If the page is
full, `dataset_complete` is false and overall status is `unknown`; an input absent from an
incomplete page is also `unknown`, not `missing_result`. This is a bounded single-page strategy,
not general pagination. Dataset cardinality for Native Bulk and the precise Bulk scope of
`resultsLimit` remain unverified. Native Bulk still creates one potentially billable Run; a URL
count or client timeout is not a total spend limit. Use an approved per-Run charge cap where
required.

One real Python Native Bulk acceptance on Build `0.0.50` passed for the three fixed TC02 URLs;
this does not validate arbitrary batch sizes or mixed success/failure results. `dataset_complete=True`
(serialized as `datasetComplete=true` in relevant records) means only that this single-page
Dataset read did not reach its configured item limit. It does not prove that every input produced
a result or that pagination was performed; use `all_success` together with each input's status to
judge Native Bulk coverage.

For copy-based integration, copy `client.py` and `reliable_actor.py` into the same application
directory and import `from client import get_transcripts`; the pair uses the standard library and
does not depend on the current working directory. Pass `token=` explicitly or set `APIFY_TOKEN`.
The reusable API reads neither `.env` nor credentials during import. The shell commands above are
documentation examples only.

## Profile posts (metadata, not transcripts)

Profile mode collects post metadata and does not transcribe posts. The Quick Start accepts one or
more explicit usernames and has no default account:

macOS/Linux:

```bash
export APIFY_TOKEN="YOUR_TOKEN"
python3 examples/python/quickstart_profile.py example_account
python3 examples/python/quickstart_profile.py example_one example_two --results-limit 5
```

Windows PowerShell:

```powershell
$env:APIFY_TOKEN = "YOUR_TOKEN"
py examples/python/quickstart_profile.py example_account
py examples/python/quickstart_profile.py example_one example_two --results-limit 5
```

Use `--help` for date and boolean options. `only-posts-newer-than` accepts a `YYYY-MM-DD` date
or a relative period such as `7 days`; the documented full ISO timestamp conflicts with the
audited schema pattern, so this client rejects ISO timestamps pending runtime verification.
Optional booleans accept explicit `true` or `false`. The examples use documentation placeholders,
not an automatically selected test account.

From Python code:

```python
from examples.python.client import get_profile_posts

result = get_profile_posts("example_account", results_limit=5)
for post in result.posts:
    print(post.url, post.type, post.video_duration)
    print(post.raw)  # all original Actor fields, including fields this client does not know
```

`get_profile_posts()` accepts a username string or a list/tuple and the keyword options
`token`, `actor_id`, `build`, `timeout`, `max_total_charge_usd`, `require_charge_cap`,
`dataset_limit`, `results_limit`, `only_posts_newer_than`, `skip_pinned_posts`,
`include_shares_count`, and injectable `transport` / `journal` seams. A single call submits the
whole username list as one native `usernames` Actor Input and creates at most one Run. The function
uses the same fixed Build and exception/transport protections as the Single URL and Native Bulk
APIs. It reads no `.env` and no credentials during import; pass `token=` or set `APIFY_TOKEN` in
the process environment. Copy `client.py` and `reliable_actor.py` together for direct integration
from another project directory.

`ProfileResult` exposes `status`, `posts`, `usernames`, `run_id`, `dataset_id`,
`dataset_complete`, `error`, and `raw_items`. Each `ProfilePost` exposes `url`, `type`,
`owner_username`, `caption`, `timestamp`, `video_url`, `video_duration`, `status`, `error`, and
`raw`. `owner_username` is read only from Actor `ownerUsername`; it is never filled from transcript
field `userName`. `timestamp` is preserved without parsing because its Profile unit/meaning is
unverified. `type` values and media fields are optional/unknown; image, video, and carousel posts
may have different fields. Missing `text` or `segments` is normal and does not cause Profile
failure.

Overall statuses are `success` (recognizable metadata for returned posts), `empty` (complete
Dataset with no posts), `actor_error` (an item has non-empty `errMsg`), `unknown` (incomplete
Dataset, malformed/unrecognized record, or uncertain multi-account ownership), and `run_failed`
(the Actor Run ended unsuccessfully). Configuration, transport, Build, and ambiguous creation
errors use the same exception types documented for `get_transcript()`; do not retry
`CreationUnknownError` blindly. For multiple usernames, the client associates posts only by an
exact requested `ownerUsername`; it never guesses from Dataset order or substitutes `userName`.
Unattributed records remain available in `posts`/`raw_items` with `unknown` status.

The meaning of `resultsLimit` across multiple accounts remains **unknown**; setting a value is not
a promise of a per-account or overall cap. The Profile API reads one Dataset page (default 100)
and reports `dataset_complete=False`/`unknown` if that page is full. Profile is separate from
Transcript mode: use a separate approved `videoUrl` or `bulkUrls` call if a post needs a
transcript. One real Profile acceptance on Build `0.0.50` used the single account `lovepegz` with
`resultsLimit=1` and returned one post metadata item. This does not validate the full TC03 Fixture,
multi-account attribution, date filtering, or pinned-post behavior. Profile returns post metadata,
not transcripts.

## Configure `.env`

The legacy `single_url.py` CLI and read-only Usage helper can load this file. The reusable
functions, Quick Starts, and CSV Batch read process environment variables only. Create the file
only if it does not already exist, so you never overwrite your own settings:

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
| `APIFY_TOKEN` | Yes for real calls | CLI examples and `get_transcript()` | The Single URL CLI may load repository `.env`; `batch_csv.py` and reusable functions require a process environment value or explicit `token=`. Sent as a Bearer header, never in a URL |
| `APIFY_ACTOR_ID` | No | all scripts | Defaults to `apple_yang/instagram-transcripts-scraper` |
| `INSTAGRAM_SESSIONID` | No | `single_url.py` | The reusable client and CSV Batch do not read a session value; Actor behavior for this field remains unverified |
| `MAX_CONCURRENCY` | No | `batch_csv.py` | Defaults to `3`; `--concurrency` overrides it; must be a positive integer |
| `APIFY_BUILD` | No | `single_url.py` | CLI defaults to approved Build `0.0.50`; reusable functions also default to it and accept an explicit `build=` argument |
| `APIFY_MAX_TOTAL_CHARGE_USD` | No | Python runners and reusable functions | Optional positive per-Run USD charge limit, sent as a Run API query option |
| `APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD` | No | Python runners and reusable functions | Set to `1` to fail closed before POST when the limit is missing or invalid; use for approved controlled tests |

Quote values that contain special characters such as `&` or `?`. Never commit `.env` or real
tokens.

For a controlled test, set `APIFY_MAX_TOTAL_CHARGE_USD` to the approved per-Run limit and
`APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD=1`. The cap is a Run option, not Actor input. An API
rejection stops that attempt; the runner never retries the creation POST without the limit.
The platform may enforce an Actor-configured minimum, and the final charge can slightly
overshoot while a capped run is being stopped; verify both before treating a cap as a hard
budget guarantee.

## Run a single URL

The URL is required as a command-line argument. The script never reads a URL from `.env`; an
empty invocation prints usage and exits with code `2` without creating a Run. `--help` is safe
and prints the supported options.

```bash
python examples/python/single_url.py --help
python examples/python/single_url.py "https://www.instagram.com/reel/your_reel_id/"
```

The script pins the approved Build `0.0.50` by default (override with `APIFY_BUILD`, which is
accepted only when it remains `0.0.50` in this controlled example), sends it as a Run query
parameter, and checks the actual Build Number and ID before reading the Dataset. It also asks for
up to 100 items on the first Dataset page; if that page is full, it reports `unknown` and
`datasetComplete: false` rather than claiming the result is complete.

On success, stdout and the output file use the same JSON object shape. `transcript` contains the
text directly, `segments` contains the segment array from the first item with non-empty text, `segmentsCount` is its length,
and `items` retains the sanitised original Actor items and metadata. For example (synthetic):

```json
{
  "status": "success",
  "transcript": "Synthetic transcript text",
  "segmentsCount": 2,
  "segments": [{"text": "Synthetic segment"}],
  "items": [{"text": "Synthetic transcript text", "segments": [{"text": "Synthetic segment"}]}]
}
```

Failures use the same keys with `transcript: null`, an empty `segments` array, and a readable
`error`. This changes the old output-file format (success array versus failure object); scripts
that consumed the previous file should now read the stable object and use its `items` array for
the original Dataset items.

The sanitised JSON object is written to:

```text
sample-output/generated/python-single-url-response.json
```

For scripts, load the output JSON and read `data["transcript"]`; use `data["segmentsCount"]` for
the segment count and `data["items"]` when you need the remaining Actor fields.

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

### Resume an existing Run

If the result file could not be written, or you need to re-read a Run you already paid for:

```bash
python examples/python/single_url.py --resume RUN_ID
```

This looks the Run up in `sample-output/generated/python-run-journal.jsonl`, verifies its Actor
ID and input association, reuses its `sourceUrl` and `datasetId`, and issues **no** new
Run-creation request. If the journal is missing, mismatched, or corrupt, the command exits with
code `2`. Each call is bounded by a 15-minute overall deadline.

## Run CSV Batch

The CSV Batch entry requires an explicit file path. Every non-empty `videoUrl` data row is one
independent Actor Run. This differs from Native Bulk, where multiple URLs are sent together in one
`bulkUrls` input and create one Run total.

Python CSV Batch has offline validation only. Its `--dry-run` path does not create Runs, but real
per-row Actor Run behavior has not been live-tested; do not infer CSV Batch live acceptance from
Single URL, Native Bulk, or Profile results.

Minimal CSV:

```csv
videoUrl
https://www.instagram.com/reels/your_reel_id/
```

macOS/Linux:

```bash
export APIFY_TOKEN="your_apify_token"
python3 examples/python/batch_csv.py "sample-data/instagram-reel-urls.csv" --dry-run
python3 examples/python/batch_csv.py "sample-data/instagram-reel-urls.csv" --concurrency 2
```

Windows PowerShell:

```powershell
$env:APIFY_TOKEN = "your_apify_token"
py examples/python/batch_csv.py "sample-data/instagram-reel-urls.csv" --dry-run
py examples/python/batch_csv.py "sample-data/instagram-reel-urls.csv" --concurrency 2
```

Use `python examples/python/batch_csv.py --help` (or `py`/`python3`) to see all options. The
CSV path is required; no default file or URL from `.env` is selected. `--dry-run` validates the
complete file and reports the number of rows and maximum possible Runs without reading a Token or
creating Runs. An actual run prints a warning with the maximum Run count before submission.

The file must be UTF-8 and contain a `videoUrl` header. UTF-8 BOM and common newline styles are
supported; blank URL rows are skipped. Every non-empty URL is validated before any Run starts, and
errors include the CSV line number. Paths with spaces or non-ASCII characters are supported.
Relative input paths are resolved from the current directory.

`--concurrency` overrides `MAX_CONCURRENCY`; both require a positive integer and default to `3`.
Concurrency is the maximum number of simultaneous requests in flight, not the total Run count. A
CSV with N valid URLs can create up to N separate Runs and may incur charges for each one. Choose a
small concurrency to limit simultaneous work and rate pressure; it does not cap total charges.

The JSON output is written to a unique file beside the explicitly supplied CSV by default, so a
copied example does not depend on the repository layout. Pass `--output "path with spaces/results.json"`
to choose a destination; existing output files are never overwritten. The journal is created next
to the selected result file. The stable document contains top-level `schemaVersion`, `mode`, `status`,
`processed`, `requested`, `concurrency`, `counts`, and `rows`. Each row records `inputRow`,
`sourceUrl`, `status`, `runId`, `datasetId`, full `transcript`, `segments`, `segmentsCount`,
`items` (the sanitized original Actor items), `datasetComplete`, and `error`. Failed, empty,
unknown, and creation-unknown rows use the same fields, with unavailable values set to `null` or
empty arrays. Results retain the transcript and full segments for application processing; credential
fields are removed/redacted before saving.

Exit code `0` means all rows succeeded, `1` means at least one row did not succeed, and `2` means
input/configuration/output setup failed before the batch could start. A row whose POST outcome is
unknown is recorded as `creation_unknown`; do not blindly rerun that URL until you reconcile the
Run. The append-only journal retains known Run IDs when result-file writing fails. CSV Batch does
not provide a batch resume command.

## Security

Do not hard-code `APIFY_TOKEN` or `INSTAGRAM_SESSIONID`. Keep secrets in `.env` or your
deployment secret manager, and never commit `.env`. Persisted results pass through a sanitiser
that drops credential-like keys and redacts common credential assignments. On POSIX, journal and
result files are created with owner-only `0600` permissions. On Windows they inherit the current
user's directory ACL because POSIX mode bits are not a Windows ACL; keep output directories private.
Stored Actor output should always be treated as sensitive.

## Verifying behaviour offline

The repository's tests exercise these code paths without network access or credentials:

```bash
python -m unittest discover -s tests/python -v
```
