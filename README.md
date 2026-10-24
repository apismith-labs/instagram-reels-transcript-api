# Instagram Reels Transcript API — Developer Integration Examples

Runnable examples for the Apify Actor
[`apple_yang/instagram-transcripts-scraper`](https://apify.com/apple_yang/instagram-transcripts-scraper).
The Actor runs on Apify and produces the transcript or profile data; this repository provides
integration examples, not a hosted service or transcription engine.

The Python examples support single Reel transcription, Actor Native Bulk, Profile post metadata,
and CSV Batch. Native Bulk sends multiple URLs in one Run; CSV Batch starts one independent Run
per non-empty CSV row. Profile returns post metadata and does not create transcripts.

## Python Quick Start

Requires Python 3.10+ and an Apify account/token. `quickstart_single.py` and the reusable client
use only the Python standard library. Replace the sample URL with a public Reel URL you are
allowed to process. A real invocation creates a potentially billable Actor Run.

macOS/Linux:

```bash
export APIFY_TOKEN="your_apify_token"
python3 examples/python/quickstart_single.py --help
python3 examples/python/quickstart_single.py "https://www.instagram.com/reels/your_reel_id/"
```

Windows PowerShell:

```powershell
$env:APIFY_TOKEN = "your_apify_token"
py examples/python/quickstart_single.py --help
py examples/python/quickstart_single.py "https://www.instagram.com/reels/your_reel_id/"
```

On success, the command prints the transcript text, segment count, and selected item metadata.
In application code, `get_transcript(url)` returns `result.text` and `result.segments`:

```python
from examples.python.client import get_transcript

result = get_transcript("https://www.instagram.com/reels/your_reel_id/")
if result.status == "success":
    transcript = result.text
    segments = result.segments
else:
    print(result.status, result.error)
```

Set `APIFY_TOKEN` in the process environment as shown above, or pass `token="..."` to a
reusable function. The client does not read `.env` or credentials during import. Never commit or
log a real token; examples send it in a Bearer authorization header.

See the [Python guide](examples/python/README.md) for setup and complete examples of
[`get_transcript()`](examples/python/README.md#reusable-python-api),
[`get_transcripts()`](examples/python/README.md#native-bulk-one-run-for-multiple-urls),
[`get_profile_posts()`](examples/python/README.md#profile-posts-metadata-not-transcripts),
and [CSV Batch](examples/python/README.md#run-csv-batch).

## Other language examples

- [cURL](examples/curl/README.md) — synchronous single URL.
- [Node.js](examples/nodejs/README.md) — Single URL, Native Bulk, Profile metadata, CSV Batch, and reusable client functions.
- [Go](examples/go/README.md) — reusable Go 1.22+ Client, Single URL, Native Bulk, Profile metadata, safe CSV Batch, and journaled Single/Bulk Resume.
- [Java](examples/java/README.md) — Java 17 SDK and CLI for Single URL, Native Bulk, Profile metadata, CSV Batch, and single/bulk Resume. Controlled Java Live checks cover L1–L5; Profile was PARTIAL. It is not published to Maven Central.
- [Rust](examples/rust/README.md) — synchronous Rust SDK and CLI for Single URL, Native Bulk, Profile metadata, CSV planning/execution, and GET-only Single/Bulk Resume. These modes have offline coverage; external Actor compatibility for the new Profile/CSV/Resume paths has not been established.
- [All examples](#supported-integration-examples) and [field reference](docs/input-output-fields.md).

Node.js examples require Node 18+. The Go 1.22+ module provides a reusable Client, Single URL,
Native Bulk, Profile metadata, CSV Batch, and journal-backed Single/Bulk Resume. Go Full Feature
Parity describes the modes implemented in this repository; it does not mean every Python or
Node.js capability is available in Go. Controlled Go Live checks on Build 0.0.50 covered Single
URL, a three-URL Native Bulk run and its GET-only Resume, one Profile account with a one-post limit,
CSV dry-run, and one CSV row. Single URL returned transcript text and 15 segments; the three Bulk
items returned 15, 14, and 12 segments; Profile returned one post's metadata; and the CSV row
returned a transcript with 15 segments. These limited checks do not establish broad production
reliability or success for arbitrary inputs. Charge caps are per-Run request controls, not a
guarantee of the final account bill. Go Single Resume has offline coverage but no dedicated Live
acceptance. Java completed controlled Build 0.0.50 checks: Single URL, three-input Native Bulk, one-row CSV, and GET-only Single Resume passed; three-account Profile was PARTIAL (19 successes, one owner attribution unknown, one Actor error). These results are narrow and do not establish production-scale reliability or final billed cost. Rust now provides offline-tested Profile, CSV plan/execute, persistent JSONL Journal, and GET-only Resume paths; external Actor compatibility for these newly implemented modes has not been live-verified.

## Example Output

Each Dataset item looks roughly like this. **The record below is synthetic and hand-written for
documentation purposes — it is not the result of an Actor run, and field presence varies by
mode.** Treat it as an illustration of shape, not as a tested contract.

```json
[
  {
    "url": "https://www.instagram.com/reel/SYNTHETIC0001/",
    "code": "SYNTHETIC0001",
    "pk": "100000000000000001",
    "id": "100000000000000001_200000000000000002",
    "title": "Synthetic example title",
    "img": "https://example.invalid/thumbnail.jpg",
    "videoUrl": "https://example.invalid/media.mp4",
    "audioUrl": "https://example.invalid/media.m4a",
    "duration": 31.5,
    "createTime": 1740000000,
    "likeCount": 1234,
    "commentCount": 56,
    "userPk": "300000000000000003",
    "userName": "example_account",
    "text": "Synthetic transcript text used only to illustrate the output shape.",
    "segments": [
      { "start": 0.0, "end": 4.2, "text": "Synthetic transcript text used..." },
      { "start": 4.2, "end": 9.8, "text": "...only to illustrate the output shape." }
    ],
    "errMsg": "",
    "timestamp": "2026-01-01T00:00:00.000Z"
  }
]
```

Units are not guaranteed: `duration` is believed to be in seconds and `createTime` is believed to
be a Unix timestamp in seconds, but neither has been confirmed against a real run. `timestamp`
carries different semantics in transcript and profile output. Keep these values as returned
unless you have verified them yourself.

## Supported Integration Examples

| Language | Single URL | Native Bulk | Profile | CSV Batch | Directory |
| --- | --- | --- | --- | --- | --- |
| Python | Yes | Yes | Yes | Yes | [examples/python/](examples/python/) |
| Node.js | Yes | Yes | Yes* | Yes | [examples/nodejs/](examples/nodejs/) |
| cURL | Yes | No | No | No | [examples/curl/](examples/curl/) |
| Java | Yes | Yes | Yes | Yes† | [examples/java/](examples/java/) |
| Go | Yes* | Yes | Yes | Yes* | [examples/go/](examples/go/) |
| Rust | Yes | Yes | Yes | Yes | [examples/rust/](examples/rust/) |

`*` Node.js Profile is implemented and covered by offline tests; it has no recorded live Actor
acceptance yet. `†` Java CSV defaults to a zero-Run plan; its one-row Live check passed, and `--execute` requires a positive per-Run cap.

`*` Go has controlled Live acceptance on Build 0.0.50 for Single URL, one three-input Native Bulk
run, a GET-only Resume of that Bulk run, one single-account Profile query (`resultsLimit=1`), CSV
dry-run, and one CSV row. The Go CSV result records its row outcome but does not expose
`datasetComplete`; this acceptance therefore does not independently establish CSV Dataset
completeness. Single Resume is offline-tested only. These checks do not establish arbitrary batch
sizes, multi-account Profile attribution, multi-row CSV behavior, generalized pagination, or
large-scale reliability. Go does not yet provide every Python/Node.js capability. Java's L1 Single URL, L2 three-URL Native Bulk, L4 one-row CSV, and L5 GET-only Single Resume checks passed. L3 three-account Profile was PARTIAL: 19 posts succeeded, one post's owner attribution could not be verified, and one account returned `crawed empty`; Java preserves those Actor items and does not change their source data. Mixed-failure Bulk, multi-row CSV, 100-item Dataset boundaries, and real creation-unknown recovery remain unverified. Java CSV `--execute` now requires a positive per-Run cap. Rust now has offline-tested Profile, CSV planning/execution, persistent JSONL Journal, and GET-only Resume paths; their external Actor compatibility is not yet live-verified. Rust requires a positive per-Run charge cap, CSV defaults to a zero-network plan, and Resume uses GET only. Rust preserves its frozen Bulk status/exit-code contract, which differs from some other language implementations. Details are in each language README and
[docs/error-handling-and-retries.md](docs/error-handling-and-retries.md).

CSV Batch is **not** the Actor's Native Bulk mode: each CSV row starts an independent Run. Python,
Node.js, Go, and Java also have Native Bulk examples that send `bulkUrls` in one Run. See
[docs/batch-processing-guide.md](docs/batch-processing-guide.md) for the distinction.

## Actor Capabilities

The Actor exposes three input modes. Choose exactly one per Run; do not mix them.

| Mode | Entry field | What it produces | Implemented examples |
| --- | --- | --- | --- |
| Single transcript | `videoUrl` | Transcript result for one public video/post URL | Python, Node.js, cURL, Java, Go, Rust |
| Native bulk transcript | `bulkUrls` | Python and Go each have one controlled three-URL Build `0.0.50` Live acceptance; arbitrary cardinality and mixed failures remain unverified | Python, Node.js, Go, Java, Rust |
| Profile posts | `usernames` | Python has one Build `0.0.50` Live acceptance for one account; Go has one single-account, one-post-limit Live acceptance; Java's three-account L3 check was PARTIAL (19 success, one owner unknown, one Actor error); Node.js has no Live acceptance; Rust has offline coverage only | Python, Node.js, Go, Java, Rust |
| CSV Batch | CSV `url` / `videoUrl` column | One independent Run per non-empty row; Go and Rust default to a zero-network plan and require explicit `--execute` plus a positive per-Run cap; Java defaults to a zero-Run plan and requires a positive per-Run cap for `--execute`; Java and Go each passed one-row Live checks; Rust has offline coverage only | Python, Node.js, Go, Java, Rust |

The Python/Node.js Single URL runners each have one recorded real acceptance on Build `0.0.50`,
limited to the TC01 URL subset. Python Native Bulk passed one real Run on Build `0.0.50` for the
three fixed TC02 URLs; this does not validate arbitrary batch sizes, general pagination, or mixed
success/failure results. Python Profile passed one real Run on Build `0.0.50` for `lovepegz` with
`resultsLimit=1`, returning one post metadata item; the full TC03 input, multi-account attribution,
date filtering, and pinned-post behavior remain unverified. Node.js Native Bulk also has a recorded
successful live Run. Node.js Profile is implemented but has not had a real Actor acceptance.
Go Native Bulk has one three-URL Live acceptance and a Resume check against that same Run; Go
Profile has one single-account, one-post-limit acceptance; Go CSV has a zero-Run dry-run and one
row-level Live acceptance. Java L1–L5 covered Single URL, Native Bulk (3 URLs), Profile (3 accounts),
one-row CSV, and GET-only Single Resume. L3 returned 19 successes, one owner attribution that
could not be verified, and one Actor error (`crawed empty`), so it remains PARTIAL. These are narrow
checks, not general coverage. The Go CSV aggregate
does not expose `datasetComplete`, so Dataset completeness was not independently asserted from
that result. Python CSV Batch remains offline-only: `--dry-run` is validated, but real
per-row CSV Runs have not been tested. Node.js CSV Batch has no live validation recorded. These
narrow results do not establish compatibility for other inputs or Builds.

Important boundaries:

- **Profile mode does not produce transcripts.** It collects post metadata. Turning that into
  transcripts is a separate second Run with `videoUrl` or `bulkUrls`.
- `videoUrl` is the required business parameter **for single mode only**. It is not a global
  required field for every mode.
- The Actor's input schema does not enforce "exactly one mode". These examples construct one
  mode-specific input; direct API callers should avoid mixing `videoUrl`, `bulkUrls`, and
  `usernames` in one Run.
- The output `videoUrl` is a media/CDN link, not a page URL. Do not feed it back in as input.
- `sessionid` is documented in the Actor README but absent from the pinned machine schema. Its
  runtime effect is unknown; the Python reusable API and Quick Starts omit it by default.

Field-level detail, including everything that is still unverified, is in
[docs/input-output-fields.md](docs/input-output-fields.md).

## Error Handling and Recovery

The Python and Node.js runners classify every call into one of eight states: `success`,
`actor_error`, `empty`, `no_transcript`, `unknown`, `transport_error`, `run_failed`, and
`creation_unknown`. An HTTP 200 with a populated `errMsg` is **not** a success, and a Run that
finished `SUCCEEDED` with no transcript text is reported as `no_transcript`, not as success.

Recovery rules implemented today:

- A Run-creation POST is not automatically retried, including after HTTP 429, because the
  platform's acceptance semantics are unverified. A 429 is recorded as `creation_unknown`; check
  the run history before deciding what to do.
- After the Run exists, all retries re-read that same Run and Dataset; they never re-POST.
- If the POST outcome is unknown (timeout, dropped connection, unparsable 5xx body), the call is
  marked `creation_unknown` and is **not** retried automatically — reconcile manually first.
- Every stage is appended to a JSONL journal so a Run ID can survive a failed result write. The
  Python Single URL CLI uses `sample-output/generated/`; Python CSV Batch places its result and
  journal beside the selected output; Node.js uses its generated-output directory. POSIX files
  use owner-only permissions, while Windows uses the current directory's inherited ACL.
- Single-URL scripts support `--resume RUN_ID`; **CSV batch scripts do not**.

Full state definitions, exit codes, journal fields, and the limits of these guarantees are in
[docs/error-handling-and-retries.md](docs/error-handling-and-retries.md).

## Pricing and Limitations

Pricing is defined by the Actor, not by this repository:
<https://apify.com/apple_yang/instagram-transcripts-scraper/pricing>

- The Actor has **more than one billing event** (a result/primary event and an audio-to-text
  event). The unit price shown on the Store page is not the total cost of a single video.
- Actual cost depends on your Apify plan and on which events a given Run triggers. Per-video
  event counts, failure charging, and whether native captions still trigger the audio event are
  all unverified.
- Bulk limits published by the Actor (for example a per-Run URL cap on the free plan) are Actor
  and plan limits that can change; they are not guarantees made by this repository.
- The synchronous endpoint used by the cURL example has a server-side response window (about
  300 seconds). Longer Runs need the asynchronous flow used by the Python and Node.js examples.
- A client timeout does not prove the request was rejected. Do not retry blindly: a retry can
  create a second billable Run. Check your Apify run history or usage first.
- Nothing here is "free to use": unlimited free usage is not implied by the examples being open
  source.

## Documentation

- [Input and output fields](docs/input-output-fields.md)
- [Batch processing guide](docs/batch-processing-guide.md)
- [Error handling and retries](docs/error-handling-and-retries.md)
- [Production integration checklist](docs/production-integration-checklist.md)
- [AI Agent use cases](docs/ai-agent-use-cases.md)
- [Prompt recipes for Reels analysis](docs/prompt-recipes-for-reels-analysis.md)
- MCP clients: [Apify MCP hub](docs/use-with-apify-mcp.md) ·
  [ChatGPT](docs/use-with-chatgpt-mcp.md) · [Claude](docs/use-with-claude-mcp.md) ·
  [Gemini CLI](docs/use-with-gemini-cli-mcp.md) · [Cursor and VS Code](docs/use-with-cursor-vscode-mcp.md)

An unrelated third-party web demo built on this API exists at
<https://www.transcript365.com>. It is not required for a first call, is not maintained by this
repository, and its availability has not been verified here.

## Repository layout

```text
.
├── docs/                     # field reference, batch, error handling, MCP guides
├── examples/
│   ├── curl/                 # synchronous single-URL shell example
│   ├── python/               # single URL, CSV batch, staged reliable runner
│   ├── nodejs/               # single URL, CSV batch, staged reliable runner
│   ├── java/                 # Java 17 SDK, CLI, and offline tests
│   ├── go/
│   └── rust/
├── tests/                    # offline tests: synthetic fixtures + mock transport
├── sample-data/              # example input CSV
├── sample-output/            # runtime output (generated files are git-ignored)
├── .env.example
└── README.md
```

## License

MIT. See [LICENSE](LICENSE).
