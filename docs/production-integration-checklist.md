# Production integration checklist

Use this checklist before connecting the Actor to a production workflow.

Use it alongside the runnable examples before moving from local validation to production workflows.

## Credentials

- `APIFY_TOKEN` is read from environment variables or a secret manager.
- `APIFY_ACTOR_ID`, optional `INSTAGRAM_SESSIONID`, and `MAX_CONCURRENCY` are treated as configuration.
- `.env` is listed in `.gitignore`.
- No real token appears in source code, examples, logs, or documentation.

## Inputs

- Instagram Reel URLs are treated as runtime input, not stable environment configuration.
- Single URL jobs pass the Reel URL as a CLI argument or request payload.
- Batch CSV files include a `videoUrl` column.
- Optional `sessionid` usage is documented internally if your integration requires it.

## Processing

- Single URL processing is tested before batch processing.
- Batch jobs preserve the source URL for every result.
- Retry behavior is limited and intentional.
- Permanent failures are recorded instead of retried indefinitely.

## Outputs

- Transcript `text` is stored in the downstream format your application needs.
- `segments` are preserved if timestamped transcript display or analysis is required.
- `errMsg` is captured for failed records.
- Raw Actor output is stored during early validation.

## Operations

- Runs are observable through logs or job records.
- Long batch jobs can resume or be safely re-run.
- Output files are written outside version control.
- Error samples are reviewed before expanding volume.

## Java SDK and CLI

- Use Java 17 and build the local source-integrated project with `mvn -B verify`; it is not published to Maven Central.
- Supply `APIFY_TOKEN` through the process environment or explicitly to `ClientConfig`; Java does not load `.env` or Keychain credentials.
- Pin Build `0.0.50` / ID `aJLRmMdQapLQRT4sJ`; require a positive per-Run `maxTotalChargeUsd` where policy requires it, and treat the cap as a request guard rather than an invoice guarantee.
- Review the append-only JSONL Journal and unique result files under `sample-output/generated/`; intent is persisted before a create POST, and POSIX files use owner-only permissions.
- Treat `creation_unknown` as a reconciliation state. Never automatically repeat the create request. Single and Native Bulk Resume use GET only and require matching Journal identity/input.
- CSV is plan-only by default. Confirm the row count, per-Run cap, and maximum possible Runs before explicit `--execute`; a Journal failure or unknown POST stops later rows.
- Java has no Java-specific Live acceptance in this implementation stage. Start with separately authorized, capped, narrow Live checks before production traffic.
