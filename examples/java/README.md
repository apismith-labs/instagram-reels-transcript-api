# Java 17 SDK and CLI

This directory is a source-integrated Java example for the Apify Actor `apple_yang/instagram-transcripts-scraper`. It provides a reusable Java 17 client and CLI for Single URL, Native Bulk, Profile metadata, CSV Batch, Single Resume, and Native Bulk Resume.

## Requirements and build

Install Java 17 and Maven. From this directory, build and test with:

```sh
mvn -B verify
java -jar target/instagram-reels-transcript-api-java-examples-0.1.0-shaded.jar --help
```

The project is not published to Maven Central. Use the repository source directly or run `mvn install` to place the artifact in your local Maven repository for development. The shaded JAR can also be built as a local executable.

## Reusable Java Client

Imports are safe: constructing the client does not read environment variables, load `.env`, or make network requests. Supply the token explicitly. Each creation method creates at most one Actor Run; CSV creates one Run per valid row.

```java
import com.apismith.instagram.transcriptapi.ClientConfig;
import com.apismith.instagram.transcriptapi.TranscriptClient;
import com.apismith.instagram.transcriptapi.RequestOptions;
import java.math.BigDecimal;

var client = new TranscriptClient(ClientConfig.builder()
    .token(System.getenv("APIFY_TOKEN"))
    .requireChargeCap(true)
    .maxTotalChargeUsd(new BigDecimal("0.10"))
    .build());

var one = client.getTranscript("https://www.instagram.com/reels/your_reel_id/");
var bulk = client.getTranscripts(java.util.List.of(
    "https://www.instagram.com/reels/first_id/",
    "https://www.instagram.com/reels/second_id/"));
var profile = client.getProfilePosts("public_username");
var plan = client.planCsv(java.util.List.of());
```

The SDK methods are `getTranscript(url)` / `getTranscript(url, RequestOptions)`, `getTranscripts(urls)` / `getTranscripts(urls, BulkOptions)`, `getProfilePosts(username)` / `getProfilePosts(usernames, ProfileOptions)`, `getTranscriptsFromCsv(rows)`, `planCsv(rows)`, `resumeTranscript(runId)`, and `resumeTranscripts(runId, urls)`. `validateUrl`, `validateBulkInput`, and `buildProfileInput` are local validation helpers. A request-level cap can be passed with `new RequestOptions(new BigDecimal("0.10"), true)`.

## Configuration and credentials

The Java CLI reads process environment variables only; it does not load `.env` or Keychain data.

| Variable | Meaning |
| --- | --- |
| `APIFY_TOKEN` | Required bearer token; keep it in a secret manager or process environment. |
| `APIFY_ACTOR_ID` | Optional Actor identifier; defaults to `apple_yang/instagram-transcripts-scraper`. |
| `APIFY_BUILD` | Optional assertion; only `0.0.50` is accepted. The request always pins this Build. |
| `APIFY_MAX_TOTAL_CHARGE_USD` | Optional per-Run charge cap. |
| `APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD` | Set to `1` to refuse Run creation without a positive cap; `0` disables this requirement. |
| `INSTAGRAM_SESSIONID` | Optional Single URL Actor input; not printed or included in Journal context. |

Never place tokens in source, command arguments, output files, or logs. A charge cap is a Run option, not a guarantee of the final account bill.

## Single URL

Provide the URL explicitly. A Run is created only after URL, Build, and requested charge-cap validation succeeds.

```sh
export APIFY_TOKEN="your-token"
java -jar target/instagram-reels-transcript-api-java-examples-0.1.0-shaded.jar single \
  "https://www.instagram.com/reels/your_reel_id/" \
  --require-charge-cap --max-total-charge-usd 0.10
```

## Native Bulk

Native Bulk submits all URLs in one Run through `bulkUrls`. Duplicate URLs and shortcode aliases are rejected. Optional Actor fields are omitted unless supplied.

```sh
java -jar target/instagram-reels-transcript-api-java-examples-0.1.0-shaded.jar bulk \
  "https://www.instagram.com/reels/first_id/" \
  "https://www.instagram.com/reels/second_id/" \
  --results-limit 12 --skip-pinned-posts false --include-shares-count false \
  --require-charge-cap --max-total-charge-usd 0.10
```

Bulk maps results by exact URL first; shortcode fallback is used only when the output item has no URL and the shortcode maps uniquely. Unmapped items are retained as extras. An incomplete one-page Dataset cannot be reported as `all_success`.

## Profile posts

Profile collects post metadata, not transcripts. It accepts one or more usernames and optional `resultsLimit`, `onlyPostsNewerThan`, `skipPinnedPosts`, and `includeSharesCount`. The date filter accepts `YYYY-MM-DD` or a relative count such as `2 weeks`; full ISO timestamps are rejected.

```sh
java -jar target/instagram-reels-transcript-api-java-examples-0.1.0-shaded.jar profile public_username \
  --results-limit 2 --only-posts-newer-than "2 weeks" \
  --require-charge-cap --max-total-charge-usd 0.10
```

Owner attribution uses `ownerUsername`; it does not substitute `userName`. Missing `text` or `segments` is expected in Profile mode. Profile Resume is not implemented.

## CSV Batch: plan first, execute explicitly

The CSV file must contain a `url` or `videoUrl` column. Parsing and URL validation happen before any Run. The default command is a zero-Run plan and does not read `APIFY_TOKEN`.

```sh
java -jar target/instagram-reels-transcript-api-java-examples-0.1.0-shaded.jar csv ../../sample-data/instagram-reel-urls.csv
```

The plan reports valid rows, maximum possible Runs, serial concurrency, Build, and any configured per-Run cap estimate. Each non-empty valid row would create its own independent Run. To opt into those billable requests, repeat the command with `--execute` and a positive cap supplied by `--max-total-charge-usd` or `APIFY_MAX_TOTAL_CHARGE_USD`; without one, execution is rejected before token access or any POST:

```sh
java -jar target/instagram-reels-transcript-api-java-examples-0.1.0-shaded.jar csv \
  ../../sample-data/instagram-reel-urls.csv --execute --max-total-charge-usd 0.10
```

Rows execute serially. A Journal write failure or unknown creation outcome stops later rows. Existing results are never overwritten; result JSON files use unique names.

## Single Resume and Native Bulk Resume

Resume requires a valid Journal record and exact original input identity. It performs GET requests only and creates zero new Runs.

```sh
java -jar target/instagram-reels-transcript-api-java-examples-0.1.0-shaded.jar single --resume RUN_ID
java -jar target/instagram-reels-transcript-api-java-examples-0.1.0-shaded.jar bulk --resume RUN_ID \
  "https://www.instagram.com/reels/first_id/" \
  --results-limit 12 --skip-pinned-posts false --include-shares-count false
```

Bulk Resume options must match the original Journal input. CSV Resume and Profile Resume are not implemented.

## Exit codes

### Single URL

| Code | Meaning |
| --- | --- |
| 0 | Transcript success |
| 2 | Invalid arguments/configuration |
| 4 | Actor item error |
| 5 | Empty Dataset |
| 6 | No transcript |
| 7 | Unknown result shape or attribution |
| 8 | Transport/protocol error |
| 9 | Run failed |
| 10 | Creation outcome unknown; reconcile before any new Run |

### Native Bulk

| Code | Meaning |
| --- | --- |
| 0 | All inputs have successful transcript results |
| 2 | Invalid arguments/configuration |
| 4–10 | Execution-level failure, using Single URL meanings |
| 11 | Partial success |
| 12 | All inputs have known failures |
| 13 | Dataset/attribution/result completeness is unknown |

### Profile

| Code | Meaning |
| --- | --- |
| 0 | Profile metadata collected |
| 2 | Invalid arguments/configuration |
| 4 | Actor item error |
| 5 | Valid empty result |
| 7 | Unknown attribution or result shape |
| 8 | Transport/protocol error |
| 9 | Run failed |
| 10 | Creation outcome unknown |

### CSV Batch

| Code | Meaning |
| --- | --- |
| 0 | Every processed row succeeded, or the validated plan is empty |
| 2 | Invalid arguments/configuration |
| 8 | Transport or Journal failure; later rows stop on Journal failure |
| 9 | Actor Run failed |
| 10 | Creation outcome unknown; later rows stop |
| 11 | Partial or all-known-failed batch, including row-level Actor/result failures |

## Charge protection, Build and HTTP safety

The client pins Build Number `0.0.50` and verifies Build ID `aJLRmMdQapLQRT4sJ` before reading a Dataset. It sends `build`, `restartOnError=false`, and, when configured, `maxTotalChargeUsd` as Run query options; these are not Actor input fields. The cap applies per Run and does not promise a final invoice ceiling.

The built-in JDK transport uses `HttpClient.Redirect.NEVER`. Run creation is attempted once, never retried, and a 307/308 response is not replayed. A timeout or ambiguous create response becomes `creation_unknown`; do not rerun until reconciling the Run history. GET requests retry transient transport failures, HTTP 429, and 5xx responses up to four attempts within the overall deadline, honoring `Retry-After` when supplied.

## Journal and recovery

The CLI defaults to the append-only `JsonlFileJournal` at `sample-output/generated/java-run-journal.jsonl`; override it with `--journal`. The SDK defaults to an `InMemoryJournal`, which is process-local and cannot support recovery after the process exits. Production SDK callers that need cross-process recovery should explicitly configure a persistent journal:

```java
import com.apismith.instagram.transcriptapi.ClientConfig;
import com.apismith.instagram.transcriptapi.JsonlFileJournal;
import com.apismith.instagram.transcriptapi.TranscriptClient;
import java.math.BigDecimal;
import java.nio.file.Path;

try (var journal = JsonlFileJournal.open(Path.of("sample-output/generated/java-sdk-journal.jsonl"))) {
    var client = new TranscriptClient(ClientConfig.builder()
        .token(System.getenv("APIFY_TOKEN"))
        .requireChargeCap(true)
        .maxTotalChargeUsd(new BigDecimal("0.10"))
        .journal(journal)
        .build());
    var result = client.getTranscript("https://www.instagram.com/reels/your_reel_id/");
    System.out.println(result.status());
}
```

The client does not close or delete a supplied Journal. Reopen the same JSONL file in a later process before calling a Resume method. Journal stages include `intent`, `run_created`, `run_finished`, `build_verified`, `resuming`, `creation_unknown`, and `complete`. `intent` is forced to disk before POST; failure blocks creation. The created Run and Dataset identities are persisted before polling. Malformed Journal lines fail closed. POSIX systems use owner-only `0600` permissions; Windows permissions are governed by the filesystem ACL and are not claimed to be POSIX `0600`.

## Result contract

The following tables describe the CLI's persisted JSON files. Nullable fields are present as JSON `null`; fields not marked nullable are always emitted. SDK methods return the corresponding Java records, except the CLI adds the `schemaVersion` and `mode` envelope and the CSV plan is a separate JSON shape.

### Single URL

| Field | JSON type | Nullable | Meaning |
| --- | --- | --- | --- |
| `schemaVersion` | number | No | Output schema version (`1`). |
| `mode` | string | No | `single_url`. |
| `status` | string | No | Transcript classification, such as `success`, `actor_error`, or `unknown`. |
| `runStatus` | string | Yes | Actual terminal Apify Run status when known. |
| `runId`, `datasetId`, `sourceUrl`, `actorId` | string | Yes | Run, Dataset, requested URL, and Actor identities. |
| `buildNumber`, `buildId`, `buildVerification`, `buildEvidenceSource` | string | Yes | Requested/observed Build identity and verification evidence. |
| `datasetComplete`, `datasetCompleteKnown` | boolean | No | Whether the single Dataset page is complete and whether that fact is known. |
| `text` | string | Yes | Transcript text for a successful result. |
| `segments` | array of JSON values | No | Timestamped segments; raw JSON values are retained. |
| `segmentsCount`, `itemCount` | number | No | Segment and returned Actor-item counts. |
| `rawItems` | array of JSON objects | No | Actor items with JSON scalar types preserved; recognized secret-named keys are removed and credential assignments in strings are redacted. |
| `error`, `stage` | string | Yes | Redacted diagnostic and execution stage. |
| `attributionVerification` | string | No | `verified`, `mismatch`, or `unknown`. |

### Native Bulk

| Field | JSON type | Nullable | Meaning |
| --- | --- | --- | --- |
| `schemaVersion`, `datasetComplete` | number, boolean | No | Schema version and single-page completeness. |
| `mode`, `status`, `executionStatus`, `attributionVerification` | string | No | `native_bulk`, aggregate state, execution state, and attribution state. |
| `runId`, `datasetId`, `error`, `stage` | string | Yes | Run/Dataset identities and diagnostics. |
| `counts` | object of integer values | No | Counts by item status. |
| `results` | array | No | One item per requested URL. Each has `url` (string), `status` (string), `text` (nullable string), `segments` and `items` (arrays), and `error` (nullable string). |
| `extras` | array | No | Unmatched items; each has `status`, `reason` (strings), and `item` (JSON object). |
| `rawItems` | array of JSON objects | No | Original Dataset items, with recognized secret-named keys removed and credential assignments in strings redacted. |

### Profile

| Field | JSON type | Nullable | Meaning |
| --- | --- | --- | --- |
| `schemaVersion` | number | No | Output schema version (`1`). |
| `mode`, `status`, `executionStatus` | string | No | `profile_posts`, Profile aggregation state, and Run execution state. |
| `runId`, `datasetId`, `error` | string | Yes | Run/Dataset identities and diagnostic. |
| `datasetComplete` | boolean | No | Single-page Dataset completeness. |
| `usernames` | array of strings | No | Requested usernames. |
| `posts` | array | No | Profile metadata; each post has nullable `url`, `type`, `ownerUsername`, `caption`, `timestamp`, `videoUrl`, `videoDuration`, and `error`; `status` is a string and `raw` is the original Actor object. |
| `rawItems` | array of JSON objects | No | Original Dataset items, with recognized secret-named keys removed and credential assignments in strings redacted. |

Profile metadata is not transcript output and does not require `text` or `segments`.

### CSV Batch

Without `--execute`, the CLI emits a plan (`mode=csv_batch_plan`) and creates no Runs. With `--execute`, it writes:

| Field | JSON type | Nullable | Meaning |
| --- | --- | --- | --- |
| `schemaVersion`, `plannedRows`, `processedRows`, `unattemptedRows`, `concurrency` | number | No | Schema version, row counts, and serial concurrency (`1`). |
| `mode`, `recordedAt`, `status` | string | No | `csv_batch_independent_runs`, timestamp, and aggregate row state. |
| `stopped` | boolean | No | Whether a Journal failure or unknown create outcome stopped later rows. |
| `counts` | object of integer values | No | Counts by row status. |
| `rows` | array | No | Each row has `row`, `sourceUrl`, `status`, `segmentsCount` (strings/numbers), `segments` and `rawItems` (arrays), plus nullable Run/Dataset IDs, `text`, `datasetComplete`, and `error`. |
| `rawItems` | array of JSON objects | No | Combined Actor items from processed rows. |
| `error` | string | Yes | Batch-level diagnostic. |

In Python's client, the transcript field is named `transcript`; Java uses `text`. Both expose `segments`. Java retains Actor JSON structure and scalar types in `rawItems`; output sanitization removes recognized credential-named keys and redacts recognized credential assignments in raw strings, without truncating other long raw text. Transcript, segments, captions, and identifiers remain unchanged unless they contain a recognized credential pattern. This matcher does not cover every possible secret form, and diagnostics continue to use bounded `safeError()` handling.

| Python field | Java field |
| --- | --- |
| `transcript` | `text` |
| `segments` | `segments` (raw JSON nodes preserved) |
| `raw_items` | `rawItems` |

Raw Actor fields and JSON types are preserved; identifiers such as `pk`, `id`, and `userPk` must remain strings. Dataset reads are single-page only (`limit=100`, `offset=0`); reaching the page limit marks results incomplete and does not imply pagination support.

## Errors and troubleshooting

`ConfigurationException` indicates invalid input or safety configuration; `ProtocolException` indicates an unexpected response; `TransportException` represents a known request/read failure; `CreationUnknownException` means a POST may have created a Run and must not be retried automatically. Business results use the statuses `success`, `actor_error`, `empty`, `no_transcript`, `unknown`, `transport_error`, `run_failed`, and `creation_unknown` as appropriate. Check Run ID, Dataset ID, Build identity, and Journal stage before deciding on recovery.

## Platform notes

Use `Path`-based paths and quote values appropriately in each shell. POSIX output and Journal files are restricted to owner read/write (`0600`); Windows uses platform ACLs. Bash/zsh exports use `export NAME=value`; PowerShell uses `$env:NAME = "value"`.

## Security summary

The client does not hard-code or load credentials. The built-in transport disables redirects, performs at most one create POST, persists Journal intent first, removes recognized secret-named output keys, and redacts recognized credential assignments in raw Actor strings and bounded diagnostics before writing unique result files. Other transcript, caption, and raw Actor text is preserved without truncation. Credential detection is pattern-based and cannot cover every possible secret form; treat Actor data as sensitive.

## Validation and live acceptance boundary

The Java SDK and CLI have offline Fake Transport coverage and completed these controlled Build `0.0.50` Live checks:

| Stage | Result | Scope |
| --- | --- | --- |
| L1 Single URL | PASS | One URL returned transcript text and segments. |
| L2 Native Bulk | PASS | Three URLs in one Run. |
| L3 Profile | PARTIAL | Three accounts: 19 posts succeeded, one post's owner attribution could not be verified, and `theownerswitch` returned Actor error `crawed empty`. |
| L4 CSV | PASS | One CSV row. |
| L5 Single Resume | PASS | GET-only resume of the L1 Run; no new Run was created. |

The L3 results reflect the Actor's original items. Java's contract fixes change their classification and error visibility, not the source Actor data. Profile mode returns post metadata, not transcripts. No final server-side billed amount has been verified.

These are narrow acceptance checks, not evidence of broad production reliability. Multi-row CSV Live, mixed-failure Bulk Live, 100-item Dataset boundaries, and real recovery from an ambiguous Run-creation outcome remain unverified. The `errMsg=""` success behavior is covered by offline tests and matches the observed Actor item contract.
