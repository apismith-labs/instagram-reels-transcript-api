# Instagram Reels Transcript API with Node.js

These examples call `apple_yang/instagram-transcripts-scraper` through the repository's staged
REST runner. They require Node.js 18 or newer. The examples do not use the Apify SDK.

The Node.js integration now includes Single URL, Actor Native Bulk, Profile metadata, CSV Batch,
and reusable application functions. The new Profile path and client API are covered by offline
Mocks only; this batch adds no live Actor validation.

## Install and configure

From `examples/nodejs`, install the locked dependencies:

```bash
npm ci --ignore-scripts --no-audit --no-fund
```

CLI examples load `APIFY_TOKEN` from the process environment and, for local convenience, the
repository-root `.env`. The reusable `client.mjs` does not load `.env`; pass `token` or set
`APIFY_TOKEN` in the process environment. Never commit or log credentials.

```bash
export APIFY_TOKEN="your_apify_token"
```

Every new Run explicitly uses `restartOnError=false`. The runners default to Build `0.0.50` and
verify the actual Build number and ID before accepting Dataset results. Configure
`APIFY_MAX_TOTAL_CHARGE_USD` for an optional per-Run cap; set
`APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD=1` to reject Run creation if the cap is absent or invalid.
The cap is sent as a Run option, not Actor input, and does not guarantee an absolute final
account-billing ceiling. A rejected cap is not removed or retried.

## Single URL

Provide the URL explicitly. The CLI does not fall back to `INSTAGRAM_REEL_URL`.

```bash
node examples/nodejs/single-url.mjs "https://www.instagram.com/reel/your_reel_id/"
```

On success, the JSON summary includes the result status and Run/Dataset IDs. Sanitized details
are saved to a unique file under `sample-output/generated/`; an existing output is never
overwritten. The summary prints the selected `outputFile` path. Only status `success` means a
non-empty transcript was returned.

### Single URL exit codes

| Code | Meaning |
| --- | --- |
| `0` | `success` — a non-empty transcript was returned without `errMsg` |
| `2` | Invalid arguments, configuration, missing token, resume lookup, or output write failure |
| `4` | `actor_error` — an item contains a non-empty `errMsg` |
| `5` | `empty` — the Dataset contains no items |
| `6` | `no_transcript` — items exist but no non-empty transcript was returned |
| `7` | `unknown` — the result could not be classified reliably |
| `8` | `transport_error` — a transport or deadline error occurred |
| `9` | `run_failed` — the Actor Run ended unsuccessfully |
| `10` | `creation_unknown` — the POST outcome is uncertain; reconcile before any retry |

Argument and configuration failures are printed as a concise error. If writing the output fails
after a Run, the summary includes the known Run and Dataset IDs before exit code `2` is returned.

## Native Bulk

Pass one or more bare Reel URLs. They become one `bulkUrls` input and one Actor Run; this is not
CSV Batch. Duplicate URLs/aliases and invalid URLs are rejected before creation.

```bash
node examples/nodejs/native-bulk.mjs \
  "https://www.instagram.com/reel/first_id/" \
  "https://www.instagram.com/reel/second_id/"
```

The CLI retains the established input defaults `resultsLimit=12`, `skipPinnedPosts=false`, and
`includeSharesCount=false`. Override them with `--results-limit N`,
`--skip-pinned-posts true|false`, and `--include-shares-count true|false`. All URLs remain in the
same Run. The sanitized result uses a unique filename; run metadata is appended to a separate
JSONL archive. The Native Bulk CLI can
resume an existing Run only when supplied `--resume RUN_ID` followed by the same URLs and input
options recorded in the journal; a mismatch fails without creating a replacement Run.

Bulk mapping uses exact URL identity first and a unique shortcode fallback only when an output
omits its URL. Missing, duplicate, conflicting, extra, or unmappable items remain visible in
per-input statuses or `extraResults`. `all_success` requires a complete Dataset and every input
to have one successful transcript. Dataset reads are bounded to one page; this is not general
pagination support.

## Profile post metadata

Profile returns post metadata, not transcripts. Items do not need `text` or `segments` to be
valid Profile results. Account attribution uses `ownerUsername`; `userName` is not substituted.
For multiple accounts, posts without an exact owner match remain unknown.

```bash
node examples/nodejs/profile.mjs account_name --results-limit 1
node examples/nodejs/profile.mjs account_a account_b --results-limit 5
node examples/nodejs/profile.mjs account_name --only-posts-newer-than "7 days" --skip-pinned-posts
```

Supported options are `--results-limit`, `--only-posts-newer-than`, `--skip-pinned-posts`, and
`--include-shares-count`. Usernames must be explicit. The multi-account scope of `resultsLimit`
and the Actor's exact accepted date-filter forms are not fully verified. Profile metadata is
preserved in the output file, including raw Actor fields; the CLI summary omits transcript
content.

Profile CLI exit codes are `0` success, `4` Actor error, `5` empty Dataset, `7` unknown result,
`8` transport error, `9` failed Run, and `10` unknown Run-creation outcome. Argument and
configuration errors exit `2`. The Native Bulk CLI uses `0` for `all_success`, `11` for
`partial_success`, `12` for `all_failed`, and `13` for `unknown` (transport and
creation-unknown errors use their corresponding `8` and `10` codes).

## Reusable API

Import the functions from an application without triggering network access, reading `.env`, or
creating files. Calls use async/await and validate input before credentials or transport setup.

```js
import { getTranscript, getTranscripts, getProfilePosts } from './examples/nodejs/client.mjs';

const one = await getTranscript('https://www.instagram.com/reel/your_reel_id/');
console.log(one.status, one.text, one.segments.length);

const bulk = await getTranscripts([
  'https://www.instagram.com/reel/first_id/',
  'https://www.instagram.com/reel/second_id/',
]);
console.log(bulk.bulkStatus, bulk.results);

const profile = await getProfilePosts('account_name', { resultsLimit: 1 });
console.log(profile.status, profile.posts.map((post) => ({ url: post.url, type: post.type, raw: post.raw })));
```

Pass an explicit `token` when needed. The optional configuration includes `actorId`, `build`,
`maxTotalChargeUsd`, `requireChargeCap`, `requestTimeoutMs`, `pollingTimeoutMs`,
`datasetPageLimit`, `maxAttempts`, `transport`, `journal`, and `sleepFn`. The default Build is
`0.0.50`; actual Build identity is always checked. A required charge cap fails closed before POST
when missing or invalid. An injected transport implements
`request(method, path, body, timeoutMs, query)`.

Each result has a stable object shape with mode/status, input identity, Run ID, Dataset ID, error,
Build evidence, and raw output where applicable. Transcript results expose their transcript
`executionStatus`; Profile results expose the actual Apify terminal `runStatus` instead, because
Profile metadata does not require transcript text. `getTranscript()` exposes `text`, `segments`,
and `items`; `getTranscripts()` exposes per-input `results`, `extraResults`, and `counts`;
`getProfilePosts()` exposes `posts`, each retaining `raw`. Profile has `success`, `actor_error`,
`empty`, or `unknown` business status. Typed exceptions distinguish configuration/protocol
problems, transport failures, and `creation_unknown`. Do not blindly retry an unknown creation
outcome.

## CSV Batch

CSV Batch creates one independent Actor Run for each non-empty `videoUrl` row. It is not Native
Bulk, and its Run count can equal the number of valid rows. The CSV path is mandatory.
Native Bulk submits its entire URL list in one Run, while CSV Batch can create one Run per row;
the two modes therefore have different Run-count and potential-cost profiles.

```bash
node examples/nodejs/batch-csv.mjs path/to/urls.csv --dry-run
node examples/nodejs/batch-csv.mjs path/to/urls.csv --concurrency 2
```

`--dry-run` validates every row and reports the possible Run count without reading credentials
or creating Runs. Output files use unique names. A row error is retained while completed rows
remain available. CSV Batch has no resume command.

## Security and recovery

- Never hard-code, commit, or print an Apify token. CLI examples load the repository-root `.env`
  for local convenience; importing `client.mjs` does not load `.env`. The reusable API accepts an
  explicit `token` or reads `APIFY_TOKEN` from the process environment.
- The REST transport sends the token in an `Authorization: Bearer` header, not in the URL. Output
  sanitization removes credential-like fields before persistence.
- Generated result files and journals request mode `0600` on POSIX systems. On Windows, the
  implementation uses the inherited file ACL; it does not configure or independently verify a
  restrictive Windows ACL.
- Actor Run creation POST is never retried, including after HTTP 429 or an ambiguous timeout.
  `creation_unknown` requires reconciliation of the request context before any manual retry.
- The default Build is `0.0.50`; the runner verifies the returned Build number and Build ID before
  accepting Dataset results. `restartOnError=false` is explicitly sent for each new Run.
- `APIFY_MAX_TOTAL_CHARGE_USD` is an optional per-Run charge cap. Setting
  `APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD=1` makes a missing or invalid cap fail before Run creation.
  The API can reject a cap, and this option is not an absolute account-level billing guarantee.
- Native Bulk submits many URLs in one Run. CSV Batch creates one independent Run per valid row,
  so its Run count and potential costs grow with the number of rows.

## Recovery and validation scope

Run creation POST is never automatically retried, including after HTTP 429 or an ambiguous
timeout. After a known Run ID exists, retries query that same Run or Dataset. Single URL and
Native Bulk can resume journaled Runs; Profile and CSV Batch do not expose resume. If journal
persistence fails after a POST, stop and reconcile the known Run before doing anything else.

Previously recorded Node.js Live evidence covers Single URL and one three-URL Native Bulk case
on Build `0.0.50`; it does not validate the new Profile implementation, arbitrary Bulk sizes,
mixed Bulk outcomes, or CSV Batch. This batch adds offline tests, not a new live acceptance.

Run the offline Node.js tests from the repository root:

```bash
node scripts/run_node_ci_tests.mjs
```
