[![Instagram Transcript Scraper on Apify](https://apify.com/actor-badge?actor=apple_yang/instagram-transcripts-scraper)](https://apify.com/apple_yang/instagram-transcripts-scraper)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub Actions CI](https://github.com/apismith-labs/instagram-reels-transcript-api/actions/workflows/python-offline.yml/badge.svg)](https://github.com/apismith-labs/instagram-reels-transcript-api/actions/workflows/python-offline.yml)

# Instagram Reels Transcript API

Use the Apify Actor as an Instagram transcript API: submit public Instagram Reel and video URLs to get transcript text and timestamped segments when available, plus structured post metadata. The Actor performs collection and transcription; this repository provides SDKs, runnable examples, and integration guides.

**[Try on Apify](https://apify.com/apple_yang/instagram-transcripts-scraper)** · **[View Pricing](https://apify.com/apple_yang/instagram-transcripts-scraper/pricing)** · **[Developer Quick Start](docs/quickstart.md)**

## Try it without code

You can try the Actor in Apify Console without setting up a local project:

1. Open the [Actor on Apify](https://apify.com/apple_yang/instagram-transcripts-scraper) and select **Try for free**.
2. In the **Input** form, enter one public Instagram Reel URL in **Video URL**.
3. Select **Start**, then open the Dataset in the **Storage** tab to inspect or export the result.

Usage may incur charges. See [current pricing on Apify](https://apify.com/apple_yang/instagram-transcripts-scraper/pricing).

## What you can build

| Use case | What the Actor provides | Next step |
| --- | --- | --- |
| Competitor content analysis | Transcript text, timestamped segments, and post metadata when returned | Use a downstream LLM to study hooks, messaging, and CTAs; see [AI agent use cases](docs/ai-agent-use-cases.md). |
| Bulk transcription | Submit multiple supported URLs in one Native Bulk Run | Use the returned structured items in your research workflow; see [batch processing](docs/batch-processing-guide.md). |
| AI agent and MCP workflows | Structured Actor results through an Apify MCP integration path | Connect a supported MCP client and pass results to your AI workflow; see [MCP guides](docs/use-with-apify-mcp.md). |
| Content repurposing | Transcript text and segments when available | Give the result to a separate AI or content tool to draft summaries, articles, or scripts; see [prompt recipes](docs/prompt-recipes-for-reels-analysis.md). |
| Creator and profile research | Public post metadata from Profile mode | Use profile metadata for creator and competitor research; see [Profile mode fields](docs/input-output-fields.md#profile-mode). |

## Example output

Illustrative field shape only; this is not a recorded Actor response. Fields vary by mode and result.

```json
{
  "url": "https://www.instagram.com/reel/<shortcode>/",
  "code": "<shortcode>",
  "text": "<transcript text, when available>",
  "segments": [
    { "start": 0.0, "end": 2.4, "text": "<spoken segment>" }
  ],
  "errMsg": ""
}
```

Transcript `text` and `segments` depend on the returned item; inspect `errMsg` and the actual fields instead of inferring success from the Run status. The [field reference](docs/input-output-fields.md) describes known and uncertain fields.

## Supported input modes

Choose one Actor input mode per Run:

| Mode | Input | Purpose |
| --- | --- | --- |
| Single Transcript | `videoUrl` | One supported public video URL |
| Native Bulk | `bulkUrls` | Multiple supported URLs in one Actor Run |
| Profile Metadata | `usernames` | Public post metadata only; no transcripts |

CSV Batch is a repository client workflow, not a fourth Actor input mode; supported clients create separate Runs for rows when execution is enabled. See [input and output fields](docs/input-output-fields.md) and [Native Bulk vs CSV](docs/batch-processing-guide.md).

## Use it from code

This repository includes examples for Python, Node.js, Go, Java, Rust, and cURL:

| Language | Guide |
| --- | --- |
| Python | [Python examples and client](examples/python/README.md) |
| Node.js | [Node.js examples and client](examples/nodejs/README.md) |
| Go | [Go examples and client](examples/go/README.md) |
| Java | [Java examples and client](examples/java/README.md) |
| Rust | [Rust examples and client](examples/rust/README.md) |
| cURL | [cURL examples](examples/curl/README.md) |

Before running, set `APIFY_TOKEN` securely in your process environment or secret manager. `0.10` below is an example Run option, not an Actor price or a promise about the final charge; adjust it to suit your needs. The run may incur actual charges.

```bash
export APIFY_MAX_TOTAL_CHARGE_USD=0.10
export APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD=1
python3 examples/python/quickstart_single.py 'https://www.instagram.com/reel/REPLACE_WITH_A_REAL_SHORTCODE/'
```

This command creates one potentially billable Run. The [Developer Quick Start](docs/quickstart.md) has the full setup and equivalent cURL and Node.js examples. Do not retry an uncertain create request; reconcile the existing Run first.

## Use with AI agents and MCP

The Actor can be connected to supported AI clients through Apify MCP. This repository provides setup guides; it is not a hosted MCP server. Tool availability and live behavior depend on the client and mode, so consult the [compatibility matrix](docs/compatibility.md) and do not assume every integration has been end-to-end verified.

- [Apify MCP](docs/use-with-apify-mcp.md)
- [ChatGPT](docs/use-with-chatgpt-mcp.md)
- [Claude](docs/use-with-claude-mcp.md)
- [Gemini CLI](docs/use-with-gemini-cli-mcp.md)
- [Cursor and VS Code](docs/use-with-cursor-vscode-mcp.md)

## Why use this Actor

- Use one Apify Actor for supported public Instagram collection and video transcription, reducing the need to assemble and maintain separate retrieval and transcription tools.
- Submit multiple video URLs in one Native Bulk Run, then inspect the returned items for partial results.
- Send structured transcript text, timestamped segments, and post metadata when available to your own content research, downstream LLM, or automation workflow; the Actor does not perform that downstream analysis for you.
- Integrate through the repository's SDKs and examples for Python, Node.js, Go, Java, and Rust, through cURL, or through the documented Apify MCP path in a compatible client.

## FAQ

### How do I get my first transcript?

Open the Actor in Apify Console, choose **Try for free**, enter a public URL, select **Start**, and inspect the Dataset. See [Try it without code](#try-it-without-code).

### Do I need to write code?

No. You can try the Actor in Apify Console. Use the [Quick Start](docs/quickstart.md) when you want to integrate it into an application.

### What if a Reel has no speech?

A Reel without transcribable speech may have no transcript text. Check the returned `text`, `segments`, and `errMsg` fields.

For more first-call answers, see the full [FAQ](docs/faq.md).

## Important limitations

- Use public content you are allowed to process; private or login-gated content may not be accessible.
- Transcript fields can be missing, and a completed Run does not guarantee a usable transcript.
- Profile mode returns public post metadata only; submit a post URL in a separate Single or Native Bulk request when you need a transcript.
- Native Bulk may return partial results; a successful result for every URL is not guaranteed, so check the returned items and available identity evidence.
- The Actor transcribes audio, not text embedded in video frames.
- A timed-out or ambiguous create request is not a reason to create a replacement Run. See [error handling and retries](docs/error-handling-and-retries.md).

See the [compatibility matrix](docs/compatibility.md) for mode-specific implementation and verification status.

## Documentation

| Topic | Guide |
| --- | --- |
| First transcript and code setup | [Quick Start](docs/quickstart.md) |
| First-call questions | [FAQ](docs/faq.md) |
| Inputs, outputs, and field caveats | [Input and output fields](docs/input-output-fields.md) |
| Language and mode verification | [Compatibility](docs/compatibility.md) |
| Errors and retry behavior | [Error handling](docs/error-handling-and-retries.md) |
| Native Bulk and CSV | [Batch processing](docs/batch-processing-guide.md) |
| Production integration | [Production checklist](docs/production-integration-checklist.md) |
| AI use cases and prompts | [AI agent use cases](docs/ai-agent-use-cases.md) · [Prompt recipes](docs/prompt-recipes-for-reels-analysis.md) |
| MCP setup | [Apify MCP](docs/use-with-apify-mcp.md) · [ChatGPT](docs/use-with-chatgpt-mcp.md) · [Claude](docs/use-with-claude-mcp.md) · [Gemini CLI](docs/use-with-gemini-cli-mcp.md) · [Cursor / VS Code](docs/use-with-cursor-vscode-mcp.md) |

## Try the Actor

**[Open the Instagram Transcript Scraper on Apify](https://apify.com/apple_yang/instagram-transcripts-scraper)** · [Read the Developer Quick Start](docs/quickstart.md)

MIT licensed. See [LICENSE](LICENSE).
