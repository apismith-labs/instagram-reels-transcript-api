# Rust SDK and Single URL CLI

This directory contains the Rust 2021 library crate `instagram_transcripts` and the `instagram-transcripts` command-line program. The SDK is synchronous. It is currently developed and verified with Rust 1.99.1; a minimum supported Rust version has not been promised.

The first G1 release scope includes a reusable Single URL client and a guarded CLI. Native Bulk, Profile, complete CSV processing, persistent JSONL recovery, and Resume are planned for later stages and are not implemented here.

## Build and test

From this directory:

```sh
cargo build --locked
cargo test --all-targets --locked
```

The library does not read environment variables, `.env`, or repository files. Provide configuration explicitly through `Config`; only the CLI reads `APIFY_TOKEN` from its process environment.

## CLI

The only supported execution command is `single`. It requires a bare HTTPS Instagram `/reel/`, `/reels/`, or `/p/` URL and a positive per-Run charge cap:

```sh
export APIFY_TOKEN='your-token'
cargo run -- single 'https://www.instagram.com/reel/your_shortcode/' \
  --max-total-charge-usd 0.10 \
  --require-charge-cap \
  --output-dir ./output
```

The CLI pins Actor Build `0.0.50` and verifies both its Build Number and Build ID before reading the Dataset. Each invocation sends at most one Run-creation POST. A timeout or ambiguous create response is reported as `creation_unknown`; do not rerun automatically until the Run is reconciled manually.

Output files use unique names, are sanitized recursively, and are written with private permissions on Unix. The `--journal` option currently accepts only `memory`; it does not provide persistent crash recovery.

## Legacy CSV entrypoint

`cargo run --bin batch_csv` is intentionally disabled with a nonzero exit status. The former implementation retried a workflow containing the billable create POST. CSV plan/execute support will return only through the reviewed G3 implementation.

## Safety boundaries

- A positive `maxTotalChargeUsd` is required for all Actor Run creation. It is a per-Run request control, not a guarantee of the final bill.
- The HTTP client disables redirects and does not retry POST requests.
- Polling and Dataset reads use GET only.
- Dataset responses must be bare JSON arrays. Reading the configured page limit marks the Dataset incomplete.
- Results are successful only when the returned Instagram URL uniquely matches the requested shortcode.
- Credential-shaped keys are removed and credential patterns in strings are redacted at output boundaries. This cannot identify every possible secret format.
- This G1 implementation provides an in-memory Journal only; persistent recovery and Resume are out of scope.

No real Actor request is required to build or test the crate. Tests use synthetic credentials, fake transports, and temporary directories.
