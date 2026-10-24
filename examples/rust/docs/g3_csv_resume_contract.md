# Rust G3 CSV and Resume Contract

This document freezes the offline behavior of Rust CSV planning/execution and Single/Native Bulk recovery. It does not claim live compatibility for these newly implemented paths.

## Charge and execution safety

All code paths that create a Run require a syntactically valid positive `maxTotalChargeUsd`. `ConfigBuilder::require_charge_cap` and CLI `--require-charge-cap` remain for compatibility, are redundant, and cannot disable the required cap. The cap is a per-Run request constraint, not a final-bill guarantee.

CSV defaults to pure planning. Planning parses `url` or `videoUrl`, handles UTF-8 BOM and blank rows, preserves physical row IDs and duplicates, validates each URL, estimates maximum Runs and the sum of per-Run caps, and makes no credential lookup or network request. Only explicit `--execute` enters execution. It requires a positive per-Run cap and processes rows sequentially (`concurrency=1`). Invalid input rows are represented in the plan. A row with an ambiguous create outcome (`creation_unknown`) or a critical Journal failure stops later scheduling and reports unattempted row IDs. Other determinate row errors are isolated. A later invocation skips only the matching `rowId` with a journaled `classified_success` result, so duplicate URLs remain distinct tasks. A previously journaled `intent`, `run_created`, `run_terminal`, or `creation_unknown` without a classified terminal result stops the batch for reconciliation instead of creating another Run. This is a safety guard, not a general distributed queue.

The legacy `batch_csv` binary delegates to the single `instagram-transcripts csv` implementation.

## Journal schema and persistence

New records serialize the recovery payload as `inputContext: { mode, input }`. The Rust reader accepts legacy `context` records only when the mode, Run ID, and required inputs are unambiguous. JSONL appends are synchronized, mode 0600 on Unix, and serialized by an in-process mutex plus an exclusive sidecar lock. A stale lock, malformed record, partial final line, symlink/non-regular path, or durability error fails closed. Credentials and Session IDs are never stored in recovery input.

## GET-only recovery

`Client::resume_transcript` and `Client::resume_transcripts` require an existing Run ID and persistent Journal. They recover the exact journaled mode/input, optionally compare caller inputs, poll the recorded Run, validate Build Number and Build ID, read its Dataset, classify with existing attribution rules, and append a terminal Journal record. These methods do not send a Run-creation POST. They do not implement Profile Resume or CSV checkpoint/resume.

## Status and exit codes

Rust Native Bulk retains its frozen G2 `BulkStatus` and exit-code mapping, including its established Rust-specific operation-error codes. This implementation does not silently map those values to another language's conventions. Profile and CSV expose their own typed/aggregate status fields; CLI errors keep existing shared error-kind exit codes.

## Verification boundary

Unit and integration tests use FakeTransport, synthetic credentials, and temporary directories. They verify local logic, serialization, Journal behavior, and zero-POST resume behavior. They do not prove the external Actor's Profile response shape, CSV billing behavior, or real-world Resume compatibility. Those require separate controlled authorization.
