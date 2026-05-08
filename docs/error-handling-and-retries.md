# Error handling and retries

Production integrations should handle both Actor-level errors and client-side failures.

## Error sources

Common failure points include:

- Missing or invalid `APIFY_TOKEN`
- Invalid Instagram Reel URL
- Deleted, private, unavailable, or region-limited Reel
- Temporary network failure
- Actor run timeout
- Empty transcript result
- Output record containing `errMsg`

## Retry strategy

Use retries for temporary failures, not permanent input problems.

Recommended first-pass strategy:

- Retry network failures and transient HTTP errors.
- Retry Actor runs that time out or fail due to temporary platform issues.
- Do not retry clearly invalid URLs without changing the input.
- Do not retry rows that return a stable `errMsg` indicating unavailable content.
- Use exponential backoff with a maximum retry count.

## Batch failure records

For batch workflows, preserve failed rows in the output with enough context to investigate later:

- Original `videoUrl`
- Row number
- Error type
- `errMsg` when returned by the Actor
- Attempt count
- Timestamp

## Token safety

Never print `APIFY_TOKEN` in logs or error messages. If your application logs request configuration, redact secrets before writing logs.
