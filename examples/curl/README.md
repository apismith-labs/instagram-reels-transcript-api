# Use Instagram Reels Transcript API with cURL

For a first call that prints the transcript, see the canonical [Quick Start](../../docs/quickstart.md); this page covers the synchronous endpoint and its risks.

This is the fastest way to verify that:

- Your Apify token works.
- The Actor input format is correct.
- A public Instagram URL returns transcript data in the Dataset.

The example uses Apify's synchronous dataset-items endpoint
(`POST /v2/acts/{owner~name}/run-sync-get-dataset-items`). It is convenient for a single URL, but
it has no asynchronous Run handle: the response is the Dataset itself, and there is no Run ID to
return to later.

**Timeout safety:** a client timeout does not prove that Apify rejected the request. This
synchronous endpoint does not expose a Run ID for reconciliation. Do not automatically rerun after
a timeout; check Apify usage/run history first to avoid duplicate charges.

## Setup

From the repository root.

1. Create the environment file only if it does not already exist, so you never overwrite your own
   settings:

   ```bash
   test -f .env || cp .env.example .env
   ```

2. Edit `.env` and set configuration values, replacing the placeholder token with your own:

   ```bash
   APIFY_TOKEN='your_apify_token_here'
   APIFY_ACTOR_ID='apple_yang/instagram-transcripts-scraper'
   INSTAGRAM_SESSIONID=''
   MAX_CONCURRENCY=3
   ```

3. Quote values that contain special characters such as `&` or `?`.

   `INSTAGRAM_SESSIONID` is optional; leave it empty unless your integration specifically needs
   it. Do not commit `.env`, and do not put a real token in a command line, a screenshot, or a
   shared log.

4. Run the example with a public Instagram URL as runtime input:

   ```bash
   bash examples/curl/single-url-sync.sh "https://www.instagram.com/reel/your_reel_id/"
   ```

The script auto-loads `.env` from the repository root. Exported environment variables also work;
if both exported variables and `.env` values are present, the exported values win.
`INSTAGRAM_REEL_URL` is still accepted as a fallback, but the recommended path is the CLI
argument.

The token is always sent as an `Authorization: Bearer` header, never as a URL query parameter.

> The script loads `.env` with `source`, which means the file is evaluated by the shell. Only do
> this with a `.env` you created or trust — do not `source` a file someone else sent you.

## Output

The script saves the raw JSON response (a Dataset item array) to:

```text
sample-output/generated/curl-single-url-response.json
```

It does not print the result to the terminal, so open the file:

```bash
python3 -m json.tool sample-output/generated/curl-single-url-response.json | head -40
```

## Judging the result

`curl --fail` only makes the script exit non-zero when the HTTP request itself fails (for
example `401` for a bad token, `4xx` for a rejected input, or a timeout). **An exit code of `0`
only means the HTTP call succeeded — it does not mean a transcript was produced.**

Inspect the saved JSON:

- `[]` — the Dataset is empty; no transcript was produced.
- A record with a non-empty `errMsg` — the Actor reported a business error.
- A record with no `text` or an empty `text` — no transcript text; treat it as `no_transcript`,
  not as success.
- A non-empty `text` and empty `errMsg` — a transcript was produced.

The cURL example performs none of this classification itself and keeps no journal, so it cannot
be resumed. If you need classified status, exit codes, and recovery, use the
[Python](../python/) or [Node.js](../nodejs/) examples, which create an asynchronous Run and
record its ID.

## Limitations

- Synchronous calls are bounded by a server-side response window (about 300 seconds); longer Runs
  will fail here and need the asynchronous flow.
- One URL per invocation. This is not the Actor's native `bulkUrls` mode.
- No retry, no journal, no Run ID, no resume.
- Billing applies to the Run that the Actor creates. See
  [../../docs/error-handling-and-retries.md](../../docs/error-handling-and-retries.md) and the
  [Actor pricing page](https://apify.com/apple_yang/instagram-transcripts-scraper/pricing).
