# Error handling and retries

This document compares the Python, Node.js, Go, and Java examples where their implementations differ. It documents implemented behaviour only; anything not implemented is listed explicitly under [Not implemented](#not-implemented).

Two distinctions drive everything below:

1. **An HTTP 200 is not a business success.** The Actor can accept a request, finish the Run, and
   still return an item whose `errMsg` says the video could not be transcribed.
2. **Creating a Run and reading its result are separate stages.** A failure while reading must
   never cause another Run to be created, because Runs are billable.

## Result statuses

Every row or call resolves to exactly one status.

| Status | Meaning | Single-URL exit code |
| --- | --- | --- |
| `success` | At least one item has non-empty string `text` and no item carries a non-empty `errMsg`. | `0` |
| `actor_error` | At least one item carries a non-empty `errMsg`. Checked **before** `text`, so an item with both is still a failure. | `4` |
| `empty` | The Dataset returned no items at all. | `5` |
| `no_transcript` | Items exist, but no transcript text: `text` is null, missing, or an empty string. | `6` |
| `unknown` | The response did not look like the expected item list, or `text` had an unsupported type (for example the number `0`). | `7` |
| `transport_error` | A recognisable API/network error while reading, or the overall deadline was exceeded. | `8` |
| `run_failed` | The Run ended `FAILED`, `TIMED-OUT`, or `ABORTED`. | `9` |
| `creation_unknown` | The Run-creation POST outcome is unknown — the Run may or may not exist. | `10` |

Additional exit codes: `2` for configuration or argument errors (missing token, missing URL,
unknown Run ID in the journal). Only `0` means a transcript was produced.

Configuration errors exit `2` for both languages. A missing or non-numeric `MAX_CONCURRENCY`
exits `2` in Node.js; Python raises on a non-integer value rather than reporting a clean code.

### Batch exit codes

The CSV batch scripts use a different contract:

| Code | Meaning |
| --- | --- |
| `0` | Every row succeeded |
| `1` | At least one row ended in any non-`success` status |
| `2` | Configuration error |

Per-row detail comes from the printed summary (`processed`, `failed`, and a count per status) and
from the errors CSV, not from the process exit code alone.

### Notes on specific statuses

- **`no_transcript` does not trigger another billable Run by default.** The scripts report the
  state and stop; they do not re-run the Actor hoping for text.

  That is a **default policy, not a proof that a retry is futile.** The state only says that no
  `text` came back this time. A genuinely silent video will probably stay silent, but content can
  also be temporarily unavailable — removed and re-posted, made private, geo- or login-gated, or
  hit by a transient extraction failure — and for those cases a later attempt *may* succeed. If
  you decide to retry, do it deliberately: bound the attempt count, run it yourself, and accept
  that each attempt is a fresh Run. Do not wire it into an unbounded loop.
- **Profile results without `text` are not transcription failures.** Profile-mode items carry
  post metadata only. If you process Profile output, classify it against the Profile contract
  from [input-output-fields.md](input-output-fields.md), not against these transcript statuses.
- **`unknown` should alert you.** It usually means the response shape changed, which is a signal
  to re-check the Actor contract rather than to retry.

## Retry rules by stage

| Stage | Retried? | Behaviour |
| --- | --- | --- |
| Create Run (`POST /acts/{id}/runs`) | No automatic retry | One attempt. Any HTTP 429 is `creation_unknown` because acceptance semantics are unverified; reconcile before considering a new Run. |
| Create Run, outcome unknown | No | Transport failure, timeout, unparsable body, or 5xx is treated as ambiguous → `creation_unknown`, with no automatic re-POST. |
| Permanent client errors | No | `400`, `401`, `403` and other non-429 4xx stop immediately with `transport_error`. Repeating them cannot help. |
| Poll Run (`GET /actor-runs/{id}`) | Yes | Up to 4 attempts on `429`, `5xx`, or a transport failure, with exponential backoff (capped at 8s) or the server's `Retry-After` (seconds or HTTP-date). |
| Read Dataset (`GET /datasets/{id}/items`) | Yes | Same rule. Re-reads the same Dataset; never re-creates the Run. |
| Overall deadline | — | 15 minutes per call by default. Once exceeded, the call stops and returns a recoverable status together with the `runId`. |

Polling interval between status reads is about 2 seconds. An exceeded deadline returns
`transport_error` with whatever Run/Dataset IDs are already known; it does **not** claim the Actor
Run was cancelled — nothing in these examples cancels a Run.

### HTTP 429 on Run creation

The scripts do not automatically retry a Run-creation POST after HTTP 429. The Actor/platform's
acceptance semantics have not been verified, and repeating the request could create duplicate
billable work. The response is recorded as `creation_unknown`; reconcile the Run history before
deciding whether to submit a new request.

Keep these claims separate:

| Claim | Status |
| --- | --- |
| The scripts automatically retry a Run-creation POST after `429` | No. |
| A `429` means the server definitely created no Run | **Unverified.** |
| Therefore a `429` means the request is definitely safe to repeat | **Not established.** |

Intermediaries can make a response hard to interpret: a proxy or gateway may return a status
after forwarding a request. Treat the outcome as potentially ambiguous and check the Actor's
run history before starting another Run.

The ambiguous case is handled conservatively for the same reason: a POST whose response never
arrived is reported as `creation_unknown` and is not retried automatically, because a second Run
may already exist.

## Journal and recovery

Each language writes an append-only JSONL journal:

```text
sample-output/generated/python-run-journal.jsonl
sample-output/generated/nodejs-run-journal.jsonl
```

| Property | Detail |
| --- | --- |
| Record contents | `rowId`, `sourceUrl`, `actorId`, `runId`, `datasetId`, `stage`, `status`, `updatedAt`, and a filtered `error` message |
| Write timing | One line per stage transition, flushed and `fsync`ed before the next stage |
| Permissions | Set to mode `0600` on append (owner read/write only) |
| Sensitive data | Error text is truncated and credential-like patterns (Bearer tokens, `token=`, `sessionid:`, `authorization`, `cookie`, `password`, `api_key`) are redacted before writing |

JSONL results, error CSVs, and single-result JSON files are also written with mode `0600`; existing
files have their permissions tightened before replacement.

If a Dataset returns an empty array after the Run succeeds, the runners wait and re-read that
same Dataset up to twice before classifying it as `empty`.

### Resuming

```bash
python examples/python/single_url.py --resume RUN_ID
node examples/nodejs/single-url.mjs --resume RUN_ID
```

Conditions and limits:

- The Run ID, Actor ID, source URL, and row ID must match a journal record; missing or mismatched
  records and malformed JSONL fail closed with exit `2`.
- Resume re-uses the journal's `sourceUrl` and `datasetId`, polls the **existing** Run, and sends
  no Run-creation request.
- Python and Node.js expose Single URL Resume. Go and Java also support GET-only Native Bulk Resume when the exact Journal identity and inputs are supplied. CSV and Profile Resume are not implemented.
- Resume is per-machine and per-file. There is no distributed lock, no cross-process de-duplication,
  and no guarantee that two resumptions of the same Run will not both run.

### Recovering after an unknown POST

There is no automatic path. The journal keeps the row identity (`rowId`, `sourceUrl`) but no Run
ID, because none was received. To reconcile:

1. Look up recent Runs for the Actor in the Apify Console or via the API.
2. Match by input URL and start time.
3. If a Run exists, read its Dataset (or resume it explicitly with that Run ID).
4. Only if no Run exists should you re-submit — and treat that as a deliberate, billable action.

## Output sanitisation

Before persisting results, credential-like keys are removed recursively (`token`, `sessionid`,
`cookie`, `authorization`, `password`, `secret`, `accessToken`, `refreshToken`, `apiKey`, in
snake, kebab, and camel forms), and string values are scrubbed for common credential assignments.
This reduces accidental leakage; it is not a substitute for treating raw Actor output as
sensitive, and it does not inspect every possible encoding.

## Java, Go, and Rust notes

Go and Java now provide reusable clients and safer staged execution. Their creation POST is attempted at most once, and their built-in HTTP clients do not replay redirected POST requests. Java uses JDK `HttpClient.Redirect.NEVER`; it classifies a timeout or ambiguous POST response as `creation_unknown`, writes Journal `intent` before POST, and requires explicit `--execute` for CSV Runs (CSV defaults to a zero-Run plan). Java GET reads retry transient transport failures, HTTP 429, and 5xx responses up to four attempts within the overall deadline, respecting `Retry-After` when supplied. Java Resume is GET-only and supports Single URL and Native Bulk; Profile and CSV Resume are not implemented.

Java uses the eight statuses listed above and Single exit codes 0, 2, 4, 5, 6, 7, 8, 9, and 10. Bulk adds 11/12/13 for partial, all-known-failed, and unknown aggregates. It reads one Dataset page (`limit=100`, `offset=0`); reaching the limit marks results incomplete and does not imply pagination support. `maxTotalChargeUsd` is a per-Run request option, not a final invoice guarantee. See the [Java guide](../examples/java/README.md) for mode-specific exit codes and configuration.

Rust remains an experimental call reference and does not yet provide the same retry-safe staged client contract.

## Not implemented

Across the repository examples, do not assume general Dataset pagination or Run cancellation when a client-side deadline expires. Java reads one Dataset page and marks a full page incomplete. Java does not implement Profile Resume, CSV Resume, or checkpoint replay. No example automatically starts downstream LLM or other processing after an error.

## Still unverified

- Real REST response envelopes, error bodies, and whether the Actor returns `errMsg` alongside a
  partial `text`.
- Dataset visibility timing right after `SUCCEEDED` (a first read could legitimately be empty).
- Server-side `Retry-After` behaviour and rate-limit semantics of this specific Actor.
- Whether any of the above prevents duplicate billing under real network failure.
- Actual charged events per Run and whether failed items are billed.
