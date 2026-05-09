# Instagram Reels Transcript API examples using Apify

Production-ready developer examples for extracting Instagram Reels transcripts with
the Apify Actor
[apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper).

This repository helps developers validate the Actor and integrate transcript
extraction into apps, internal tools, databases, batch workflows, and AI/MCP
workflows.

It includes cURL, Python, Node.js, Java, Go, and Rust examples.

## Apify Actor

- Actor page: [Instagram Transcripts Scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)
- Actor ID: `apple_yang/instagram-transcripts-scraper`

## Quick start

1. Create a local environment file:

   ```bash
   cp .env.example .env
   ```

2. Add your Apify token:

   ```bash
   APIFY_TOKEN='your_apify_token_here'
   APIFY_ACTOR_ID='apple_yang/instagram-transcripts-scraper'
   INSTAGRAM_SESSIONID=''
   MAX_CONCURRENCY=3
   ```

3. Run the cURL quick validation example with a Reel URL as runtime input:

   ```bash
   bash examples/curl/single-url-sync.sh "https://www.instagram.com/reel/your_reel_id/"
   ```

4. Choose a language example for production integration:

   - [Python](examples/python/)
   - [Node.js](examples/nodejs/)
   - [Java](examples/java/)
   - [Go](examples/go/)
   - [Rust](examples/rust/)

## Language examples

| Language | Single URL | Batch CSV | Directory |
| -------- | ---------- | --------- | --------- |
| cURL | Yes | No | [examples/curl/](examples/curl/) |
| Python | Yes | Yes | [examples/python/](examples/python/) |
| Node.js | Yes | Yes | [examples/nodejs/](examples/nodejs/) |
| Java | Yes | Yes | [examples/java/](examples/java/) |
| Go | Yes | Yes | [examples/go/](examples/go/) |
| Rust | Yes | Yes | [examples/rust/](examples/rust/) |

## Live demo

If you want to test Instagram transcript extraction without writing code, try the web demo built on top of this API:
[https://www.transcript365.com](https://www.transcript365.com)

## AI and MCP workflows

The API examples in this repository can also be used as building blocks for AI agents and LLM workflows.

For MCP-compatible clients, start with the practical setup hub:

- [Use Instagram Reels Transcript API with Apify MCP](docs/use-with-apify-mcp.md)

Platform-specific guides:

- [ChatGPT via Apify MCP](docs/use-with-chatgpt-mcp.md)
- [Claude via Apify MCP](docs/use-with-claude-mcp.md)
- [Gemini CLI via Apify MCP](docs/use-with-gemini-cli-mcp.md)
- [Cursor and VS Code via Apify MCP](docs/use-with-cursor-vscode-mcp.md)

Analysis and prompt resources:

- [AI Agent Use Cases](docs/ai-agent-use-cases.md)
- [Prompt Recipes for Reels Analysis](docs/prompt-recipes-for-reels-analysis.md)

## When to use this repo

- Build transcript extraction into your own app.
- Process batches of Instagram Reel URLs.
- Feed transcript text into internal tools, databases, or content analysis pipelines.
- Avoid maintaining your own video download and transcription infrastructure.

## Authentication and input

You must provide your own Apify API token.

Do not hard-code tokens in source code, scripts, docs, commits, logs,
screenshots, or shared output files.

Configuration belongs in `.env`:

- `APIFY_TOKEN`
- `APIFY_ACTOR_ID`
- `INSTAGRAM_SESSIONID`
- `MAX_CONCURRENCY`

Instagram Reel URLs are runtime input:

- Single URL examples accept a CLI argument.
- Batch examples read URLs from `sample-data/instagram-reel-urls.csv`.

## Actor input

```json
{
  "videoUrl": "https://www.instagram.com/reel/your_reel_id/",
  "sessionid": ""
}
```

`videoUrl` is the Reel URL for the current request.

`sessionid` is optional configuration and should remain blank unless your
integration requires it.

## Important output fields

- `text`
- `segments`
- `title`
- `userName`
- `likeCount`
- `commentCount`
- `videoUrl`
- `audioUrl`
- `errMsg`
- `url`

See [docs/input-output-fields.md](docs/input-output-fields.md) for the full field reference.

## Repository layout

```text
.
├── docs/
│   ├── ai-agent-use-cases.md
│   ├── batch-processing-guide.md
│   ├── error-handling-and-retries.md
│   ├── input-output-fields.md
│   ├── production-integration-checklist.md
│   ├── prompt-recipes-for-reels-analysis.md
│   ├── use-with-apify-mcp.md
│   ├── use-with-chatgpt-mcp.md
│   ├── use-with-claude-mcp.md
│   ├── use-with-cursor-vscode-mcp.md
│   └── use-with-gemini-cli-mcp.md
├── examples/
│   ├── curl/
│   ├── go/
│   ├── java/
│   ├── nodejs/
│   ├── python/
│   └── rust/
├── sample-data/
│   └── instagram-reel-urls.csv
├── sample-output/
│   └── .gitkeep
├── .env.example
├── .gitignore
├── LICENSE
└── README.md
```

## License

This project is licensed under the MIT License.
