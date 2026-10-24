# Rust SDK and Single URL CLI

This directory contains the Rust 2021 library crate `instagram_transcripts` and the `instagram-transcripts` command-line program. The SDK is synchronous. It is currently developed and verified with Rust 1.99.1; a minimum supported Rust version has not been promised.

The Rust SDK provides reusable Single URL, Actor-native Bulk, Profile metadata, CSV plan/execute, and GET-only Single/Bulk Resume APIs and CLI modes. Bulk validates and deduplicates `(media type, shortcode)` identities before one Run, preserving every source occurrence and conservatively attributing returned items. Profile returns post metadata, not transcripts. The [G2 identity and attribution contract](docs/g2_identity_contract.md) defines the stable identity, evidence, status, and result rules; the [G3 CSV and Resume contract](docs/g3_csv_resume_contract.md) defines recovery and CSV behavior. These new modes have offline FakeTransport coverage; external Actor compatibility for Profile/CSV/Resume has not been live-verified.

## Build and test

From this directory:

```sh
cargo build --locked
cargo test --all-targets --locked
```

The library does not read environment variables, `.env`, or repository files. Provide configuration explicitly through `Config`; the CLI reads Apify configuration only from its process environment and never loads `.env`.

## CLI

The `single` command requires a bare HTTPS Instagram `/reel/`, `/reels/`, or `/p/` URL and a positive per-Run charge cap:

```sh
export APIFY_TOKEN='your-token'
cargo run --bin instagram-transcripts -- single 'https://www.instagram.com/reel/your_shortcode/' \
  --max-total-charge-usd 0.10 \
  --require-charge-cap \
  --output-dir ./output
```

The CLI pins Actor Build `0.0.50` and verifies both its Build Number and Build ID before reading the Dataset. Each invocation sends at most one Run-creation POST. A timeout or ambiguous create response is reported as `creation_unknown`; do not rerun automatically until the Run is reconciled manually.

Native Bulk accepts one or more URLs and makes one Actor Run for all unique typed identities. `/reel/X` and `/reels/X` deduplicate as one Reel; `/p/X` stays separate even when its shortcode is the same. Invalid input is rejected before credentials or network access. A positive per-Run cap is required:

```sh
export APIFY_TOKEN='your-token'
cargo run --bin instagram-transcripts -- native-bulk \
  'https://www.instagram.com/reel/first_code/' \
  'https://www.instagram.com/reels/first_code/' \
  'https://www.instagram.com/p/first_code/' \
  --results-limit 12 \
  --max-total-charge-usd 0.10 \
  --require-charge-cap \
  --output-dir ./output
```

Use `bulk --input-file ./urls.txt` to read one URL per line; `native-bulk` is a compatibility alias for the same implementation. The first two URLs above form one Reel task with both source indexes/URLs; the Post remains a separate task. A returned, validated `/reel/X` or `/reels/X` URL is attributed to the same typed Reel identity in either direction. An exact normalized source URL is reported as `exact_url`; a validated path alias is `typed_fallback`. `--results-limit` defaults to 12, and the boolean Actor options default to false. Bulk output contains one task row per unique identity, physical extras once each, and a `plannedTaskCount` that is a number after valid preflight or `null` if no complete plan was possible. The CLI never retries Run creation.

The `bulkUrls` input field is used by the existing cross-language implementations, but this Rust implementation has not yet established the real Actor's per-URL processing coverage. If the Actor returns only a subset of requested items, the current response may not distinguish an unprocessed URL from a confirmed no-transcript/empty outcome. Treat external Actor Bulk compatibility as **unverified** until a separately approved, controlled live acceptance. Do not make a paid request without explicit authorization.

Output files use unique names, are sanitized recursively, and are written with private permissions on Unix. The `--journal` option accepts `memory` or a JSONL path. File journals append durably, use owner-only permissions on Unix, reject malformed history and unsafe symlink paths, and fail closed if another writer holds the journal lock. Persisted records contain the non-sensitive mode input required for recovery, never the token, Cookie, or Session ID.

## Profile metadata

Profile requests validate usernames and supported date filters before credentials are read. The reusable API is `Client::get_profile_posts`; it returns each post's metadata and preserved sanitized Actor item. It does not produce transcript text. Multi-account items require a matching `ownerUsername`; Dataset order is never used to infer ownership. A non-empty Actor `errMsg` is classified as `actor_error` before URL/metadata attribution checks. Otherwise, a post must have a valid post URL, meaningful non-empty metadata, and an allowed owner attribution; a missing owner is accepted only for a single-account request. Null, blank, boolean, array, or object values do not count as meaningful metadata.

```sh
cargo run --bin instagram-transcripts -- profile alice --results-limit 12 --max-total-charge-usd 0.10 \
  --journal ./output/profile.jsonl --output-dir ./output
```

## CSV plan and execution

CSV accepts a `url` or `videoUrl` header and preserves duplicate rows as separate independent tasks. Planning is pure, creates no Client, reads no token, and sends no network requests. `--execute` is required to create Runs, requires a positive per-Run cap, and requires a persistent `--journal` path. Rows execute sequentially even when a requested `--concurrency` value from 1 to 32 is supplied; output records actual concurrency as 1. A creation outcome that is unknown or a journal failure stops the batch and lists unattempted rows.

```sh
cargo run --bin instagram-transcripts -- csv ./input.csv --dry-run
cargo run --bin instagram-transcripts -- csv ./input.csv --execute --max-total-charge-usd 0.10 \
  --journal ./output/csv.jsonl --output-dir ./output
```

`cargo run --bin batch_csv -- ...` is a compatibility shim to the same `instagram-transcripts csv` implementation; it does not contain a separate billing path.

## GET-only Resume

Single and Native Bulk resume require a persistent `--journal` and an existing Run ID. They poll the recorded Run and read its Dataset using GET requests only; they never create another Run. The supplied Bulk URL set must match the journaled normalized plan. Resume does not recover CSV batches or Profile Runs.

## Safety boundaries

- A positive `maxTotalChargeUsd` is required for all Actor Run creation. It is a per-Run request control, not a guarantee of the final bill.
- The HTTP client disables redirects and does not retry POST requests.
- Polling and Dataset reads use GET only.
- Dataset responses must be bare JSON arrays. Reading the configured page limit marks the Dataset incomplete.
- Single results require unique exact URL attribution. Bulk uses exact normalized source URL evidence first; typed fallback requires a reliable item media type and shortcode. It never assigns by Dataset order or guesses from shortcode alone.
- Dataset items are retained once across task rawItems and extraItems; conflicting or duplicate evidence cannot produce transcript success.
- Credential-shaped keys are removed and credential patterns in strings are redacted at output boundaries. This cannot identify every possible secret format.
- File Journal and GET-only Single/Bulk Resume are available. CSV and Profile do not have resume APIs.

No real Actor request is required to build or test the crate. Tests use synthetic credentials, fake transports, and temporary directories.
