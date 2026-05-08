# Production integration checklist

Use this checklist before connecting the Actor to a production workflow.

## Credentials

- `APIFY_TOKEN` is read from environment variables or a secret manager.
- `.env` is listed in `.gitignore`.
- No real token appears in source code, examples, logs, or documentation.

## Inputs

- Instagram Reel URLs are validated before submission.
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
