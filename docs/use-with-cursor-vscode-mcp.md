# Use Instagram Reels Transcript API with Cursor and VS Code via Apify MCP

## What this guide covers

This guide shows how developers can use Apify MCP from AI coding assistants to
inspect Actor output and generate integration code.

The Actor can help coding assistants inspect transcript output and generate
integration code, database schemas, ETL steps, or data pipeline plans.

This repository does not include a custom IDE extension.

Primary Actor: [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)

## Prerequisites

- Cursor or VS Code with MCP-compatible tooling
- Apify account
- OAuth or `APIFY_TOKEN`
- Public Instagram Reel URL
- Actor ID: `apple_yang/instagram-transcripts-scraper`

## Cursor configuration example

Create or update `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "apify-instagram-transcript": {
      "url": "https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper"
    }
  }
}
```

Bearer token version:

```json
{
  "mcpServers": {
    "apify-instagram-transcript": {
      "url": "https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper",
      "headers": {
        "Authorization": "Bearer YOUR_APIFY_TOKEN"
      }
    }
  }
}
```

## VS Code MCP configuration example

Generic VS Code user-level MCP configuration:

```json
{
  "mcpServers": {
    "apify-instagram-transcript": {
      "url": "https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper"
    }
  }
}
```

Exact file location may vary by extension or client.

Prefer user-level config or secure workspace config. Do not commit token-bearing
workspace files.

## Local stdio alternative

```json
{
  "mcpServers": {
    "apify": {
      "command": "npx",
      "args": ["-y", "@apify/actors-mcp-server@latest"],
      "env": {
        "APIFY_TOKEN": "YOUR_APIFY_TOKEN"
      }
    }
  }
}
```

## Example coding assistant prompts

```text
Use the Apify MCP Actor apple_yang/instagram-transcripts-scraper to inspect this
public Instagram Reel URL.

Then generate a TypeScript interface for the output fields.
```

```text
Run the Instagram transcript Actor with this Reel URL.

Inspect the returned JSON and create a PostgreSQL schema for storing transcript
records.
```

```text
Use this Actor output to write a batch-processing pipeline that stores:
- transcript text
- segments
- creator username
- like count
- comment count
- errMsg
```

```text
Generate error handling logic for failed Actor runs, empty transcripts, and incomplete MCP output previews.
```

## Useful developer tasks

- Generate TypeScript interfaces
- Generate database schemas
- Generate batch processing code
- Generate error handling strategy
- Compare output fields across runs
- Write tests based on sample output

## Security notes

- Do not commit `.cursor/mcp.json` if it contains tokens.
- Do not commit workspace MCP configs with secrets.
- Prefer OAuth where available.
- Review tool calls before running write operations.
- Keep `APIFY_TOKEN` out of public prompts and screenshots.

## Related docs

- [Use Instagram Reels Transcript API with Apify MCP](use-with-apify-mcp.md)
- [Prompt recipes for Reels analysis](prompt-recipes-for-reels-analysis.md)
- [AI agent use cases](ai-agent-use-cases.md)
