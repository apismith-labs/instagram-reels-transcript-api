# Instagram Reels Transcript API

**Turn public Instagram Reel/video URLs into transcript text, timestamped segments, and structured post metadata.** The Apify Actor performs the collection and transcription; this repository contains integration examples and SDKs, not a hosted API or transcription service.

- **Try the Actor:** [Open it on Apify](https://apify.com/apple_yang/instagram-transcripts-scraper)
- **First transcript:** [Canonical Quick Start](docs/quickstart.md) · [Current Actor pricing](https://apify.com/apple_yang/instagram-transcripts-scraper/pricing)
- **Check coverage before integrating:** [Compatibility and verification matrix](docs/compatibility.md)

## What you get

A successful transcript item includes text and may include timestamped segments. For example:

```json
{
  "text": "Example transcript text.",
  "segments": [{"start": 0, "end": 1.2, "text": "Example transcript text."}]
}
```

This is illustrative; fields vary by result and mode. Profile returns post metadata rather than transcripts. See the [field reference](docs/input-output-fields.md).

## First call

The shortest repository example uses Python 3.10+ and prints transcript text in the terminal. Set credentials and cap through your shell or secret manager; do not paste a real token into a command stored in history.

```bash
read -r -s -p 'Apify token: ' APIFY_TOKEN; printf '\n'; export APIFY_TOKEN
export APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD=1
read -r -p 'Positive per-Run charge cap (USD): ' APIFY_MAX_TOTAL_CHARGE_USD; export APIFY_MAX_TOTAL_CHARGE_USD
python3 examples/python/quickstart_single.py 'https://www.instagram.com/reel/REPLACE_WITH_A_REAL_SHORTCODE/'
```

Replace the placeholder with a public URL you are allowed to process. This command creates one potentially billable Run. If creation status is uncertain, stop and check Apify before making another create request. See [Quick Start](docs/quickstart.md) for equivalent cURL, Python, and Node.js REST examples that print the Run ID and transcript.

Running this Actor may incur Apify charges. Review [current pricing](https://apify.com/apple_yang/instagram-transcripts-scraper/pricing) before starting a Run. A requested per-Run cap is a protective option, not an absolute final-bill guarantee. A timeout or ambiguous create response is not a reason to retry: reconcile the Run first.

## Choose an integration

| Goal | Use | Notes |
| --- | --- | --- |
| One transcript | [Single URL SDKs and cURL](docs/quickstart.md) | `videoUrl` input; returns transcript `text` and `segments` when available. |
| Several URLs in one Run | [Native Bulk](docs/batch-processing-guide.md) | `bulkUrls`; one Actor Run for the bulk input. |
| Public profile post metadata | [Profile guides](examples/python/README.md#profile-posts-metadata-not-transcripts) | `usernames`; Profile does not create transcripts. |
| CSV with separate work per row | [Batch guide](docs/batch-processing-guide.md) | Each non-empty row is an independent Run when execution is explicitly enabled. |
| AI client / tool connection | [Apify MCP guide](docs/use-with-apify-mcp.md) | MCP is an Actor-tool integration path, not an SDK. |
| Application library | [Python](examples/python/README.md) · [Node.js](examples/nodejs/README.md) · [Go](examples/go/README.md) · [Java](examples/java/README.md) · [Rust](examples/rust/README.md) | Language-specific API, safety, install, and verification details. |

## Capabilities

The Actor has three primary input modes. Choose one mode per Run; do not combine `videoUrl`, `bulkUrls`, and `usernames` in one input.

| Mode | Input | Result |
| --- | --- | --- |
| Single transcript | `videoUrl` | Transcript item for one supported public Reel/video/post URL. |
| Native Bulk transcript | `bulkUrls` | Transcript items for multiple submitted URLs in one Run; exact mapping and completeness depend on returned evidence. |
| Profile posts | `usernames` | Post metadata and owner attribution; no transcript. |

CSV is an SDK workflow, not a fourth Actor input mode. Supported SDK CSV execution starts a separate Run for each non-empty row. A CSV batch cap, where available, is per Run rather than a shared total budget.

The pinned input schema does not enforce an exactly-one-mode rule. SDKs validate their supported mode inputs; direct API callers should still send only one entry field. The Actor's behavior for a mixed-mode input is unverified.

## Integration status

For the current language-by-mode status, live acceptance scope, and package publication boundaries, use the [Compatibility and Verification matrix](docs/compatibility.md). Highlights:

- Rust G5 recorded six narrow checks: Single, same-Run Single Resume, a three-URL Native Bulk run, same-Run Bulk Resume, one Profile result, and one CSV row.
- Go and Java have their own controlled live checks; Java's three-account Profile result was **PARTIAL** (19 successes, one owner attribution unknown, one Actor error).
- Python and Node.js live coverage varies by mode. Do not infer live acceptance from an implementation or offline test.
- These checks are not a production-scale reliability guarantee. Several multi-account, multi-row, partial-result, and ambiguous-create scenarios remain unverified.

## Safety, cost, and Build

- The token belongs in a secret manager or process environment and is sent in an Authorization header. Never put it in a URL, source file, Git, or logs.
- Current repository examples use the controlled Actor Build `0.0.50` where pinned. They verify Build identity according to their language-specific contract. This is not a claim that `0.0.50` is the Actor's latest Build.
- Use a positive `maxTotalChargeUsd` cap for supported Run-creation paths. The cap is a per-Run request option, not an absolute final account-bill limit. Check the [Actor's current pricing](https://apify.com/apple_yang/instagram-transcripts-scraper/pricing).
- A create `POST` is not automatically retried. A timeout can leave creation status unknown; reconcile before any further create request.
- Supported resume operations read an existing Run/Dataset with GET requests only. They do not create a replacement Run.
- Dataset completeness and item attribution matter: Run `SUCCEEDED` alone does not prove every requested item produced a valid transcript.

## Documentation map

| Topic | Guide |
| --- | --- |
| First call and output parsing | [Quick Start](docs/quickstart.md) |
| Pricing and charge-cap notice | [Actor's current pricing](https://apify.com/apple_yang/instagram-transcripts-scraper/pricing) and [Quick Start](docs/quickstart.md) |
| Language and live-verification scope | [Compatibility](docs/compatibility.md) |
| Input and output fields | [Field reference](docs/input-output-fields.md) |
| Errors, states, and retry rules | [Error handling](docs/error-handling-and-retries.md) |
| Native Bulk vs CSV | [Batch processing](docs/batch-processing-guide.md) |
| Production readiness checklist | [Production integration checklist](docs/production-integration-checklist.md) |
| AI use cases and prompt recipes | [AI Agent use cases](docs/ai-agent-use-cases.md) · [Prompt recipes](docs/prompt-recipes-for-reels-analysis.md) |
| MCP setup | [Apify MCP](docs/use-with-apify-mcp.md) · [ChatGPT](docs/use-with-chatgpt-mcp.md) · [Claude](docs/use-with-claude-mcp.md) · [Gemini CLI](docs/use-with-gemini-cli-mcp.md) · [Cursor / VS Code](docs/use-with-cursor-vscode-mcp.md) |

## Verification detail migration map

The former README mixed product navigation with long mode-specific verification notes. Those claims have been moved and checked against the old statements as follows:

| Previous README detail | Canonical location | Retained fact / limitation |
| --- | --- | --- |
| Language-by-mode feature and Live table | [Compatibility](docs/compatibility.md) | Implemented is distinct from Live-verified; Node.js Profile/CSV and Python CSV are not promoted to Live-verified. |
| Rust G5 six checks and unverified cases | [Compatibility](docs/compatibility.md), [Rust guide](examples/rust/README.md) | Single/Bulk/Profile/CSV and same-Run Resume scope retained; actual charge unknown; broader cases remain unverified. |
| Java L1–L5 summary | [Compatibility](docs/compatibility.md), [Java guide](examples/java/README.md) | Profile remains PARTIAL with the recorded 19 / 1 / 1 outcomes; no production-scale claim. |
| Go live checks and result-completeness caveats | [Compatibility](docs/compatibility.md), [Go guide](examples/go/README.md) | Narrow Single/Bulk/Profile/CSV evidence and CSV Dataset-completeness limitation retained. |
| Actor mode and field-shape cautions | [Field reference](docs/input-output-fields.md) | Profile metadata is not transcript output; mode-specific and uncertain fields remain documented. |
| Retry and recovery semantics | [Error handling](docs/error-handling-and-retries.md) | No blind create retry, `creation_unknown`, and supported GET-only recovery boundaries retained. |
| Pricing and Run-cap warnings | [Actor's current pricing](https://apify.com/apple_yang/instagram-transcripts-scraper/pricing), [Quick Start](docs/quickstart.md) | Check current pricing before running; requested caps are not absolute bill guarantees. |

## Repository contents

- `examples/python/`, `examples/nodejs/`, `examples/go/`, `examples/java/`, `examples/rust/`: language clients and CLI examples.
- `examples/curl/`: cURL examples.
- `docs/`: quickstarts, field references, compatibility, safety, batching, and MCP guides.
- `sample-data/`: synthetic/sample CSV input.
- `sample-output/generated/`: local runtime output; generated files are Git-ignored.

MIT licensed. See [LICENSE](LICENSE).
