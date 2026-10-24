# Rust SDK and Single URL CLI

This directory contains the Rust 2021 library crate `instagram_transcripts` and the `instagram-transcripts` command-line program. The SDK is synchronous. It is currently developed and verified with Rust 1.99.1; a minimum supported Rust version has not been promised.

The Rust SDK provides a reusable Single URL client and Actor-native Bulk client/CLI. Bulk validates and deduplicates `(media type, shortcode)` identities before one Run, preserving every source occurrence and conservatively attributing returned items. Profile, CSV execution, persistent JSONL recovery, and Resume remain out of scope. The [G2 identity and attribution contract](docs/g2_identity_contract.md) defines the stable identity, evidence, status, and result rules.

## Build and test

From this directory:

```sh
cargo build --locked
cargo test --all-targets --locked
```

The library does not read environment variables, `.env`, or repository files. Provide configuration explicitly through `Config`; only the CLI reads `APIFY_TOKEN` from its process environment.

## CLI

The `single` command requires a bare HTTPS Instagram `/reel/`, `/reels/`, or `/p/` URL and a positive per-Run charge cap:

```sh
export APIFY_TOKEN='your-token'
cargo run -- single 'https://www.instagram.com/reel/your_shortcode/' \
  --max-total-charge-usd 0.10 \
  --require-charge-cap \
  --output-dir ./output
```

The CLI pins Actor Build `0.0.50` and verifies both its Build Number and Build ID before reading the Dataset. Each invocation sends at most one Run-creation POST. A timeout or ambiguous create response is reported as `creation_unknown`; do not rerun automatically until the Run is reconciled manually.

Native Bulk accepts one or more URLs and makes one Actor Run for all unique typed identities. `/reel/X` and `/reels/X` deduplicate as one Reel; `/p/X` stays separate even when its shortcode is the same. Invalid input is rejected before credentials or network access. A positive per-Run cap is required:

```sh
export APIFY_TOKEN='your-token'
cargo run -- native-bulk \
  'https://www.instagram.com/reel/first_code/' \
  'https://www.instagram.com/reels/first_code/' \
  'https://www.instagram.com/p/first_code/' \
  --results-limit 12 \
  --max-total-charge-usd 0.10 \
  --require-charge-cap \
  --output-dir ./output
```

The first two URLs above form one Reel task with both source indexes/URLs; the Post remains a separate task. A returned, validated `/reel/X` or `/reels/X` URL is attributed to the same typed Reel identity in either direction. An exact normalized source URL is reported as `exact_url`; a validated path alias is `typed_fallback`. `--results-limit` defaults to 12, and the boolean Actor options default to false. Bulk output contains one task row per unique identity, physical extras once each, and a `plannedTaskCount` that is a number after valid preflight or `null` if no complete plan was possible. The CLI never retries Run creation.

The `bulkUrls` input field is used by the existing cross-language implementations, but this Rust implementation has not yet established the real Actor's per-URL processing coverage. If the Actor returns only a subset of requested items, the current response may not distinguish an unprocessed URL from a confirmed no-transcript/empty outcome. Treat external Actor Bulk compatibility as **unverified** until a separately approved, controlled live acceptance. Do not make a paid request without explicit authorization.

Output files use unique names, are sanitized recursively, and are written with private permissions on Unix. The `--journal` option currently accepts only `memory`; it does not provide persistent crash recovery.

## Legacy CSV entrypoint

`cargo run --bin batch_csv` is intentionally disabled with a nonzero exit status. The former implementation retried a workflow containing the billable create POST. CSV plan/execute support will return only through the reviewed G3 implementation.

## Safety boundaries

- A positive `maxTotalChargeUsd` is required for all Actor Run creation. It is a per-Run request control, not a guarantee of the final bill.
- The HTTP client disables redirects and does not retry POST requests.
- Polling and Dataset reads use GET only.
- Dataset responses must be bare JSON arrays. Reading the configured page limit marks the Dataset incomplete.
- Single results require unique exact URL attribution. Bulk uses exact normalized source URL evidence first; typed fallback requires a reliable item media type and shortcode. It never assigns by Dataset order or guesses from shortcode alone.
- Dataset items are retained once across task rawItems and extraItems; conflicting or duplicate evidence cannot produce transcript success.
- Credential-shaped keys are removed and credential patterns in strings are redacted at output boundaries. This cannot identify every possible secret format.
- This G1 implementation provides an in-memory Journal only; persistent recovery and Resume are out of scope.

No real Actor request is required to build or test the crate. Tests use synthetic credentials, fake transports, and temporary directories.
