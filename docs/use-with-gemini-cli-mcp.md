# Use Instagram Reels Transcript API with Gemini CLI via Apify MCP

## What this guide covers

This guide shows how Gemini CLI users can connect to Apify MCP and use the Actor `apple_yang/instagram-transcripts-scraper` in terminal-based AI workflows.

This repository does not provide a custom Gemini extension or custom MCP server.

Primary Actor: [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)

## Prerequisites

- Gemini CLI installed
- Apify account
- `APIFY_TOKEN` or OAuth-compatible remote MCP setup
- Public Instagram Reel URL
- Actor ID: `apple_yang/instagram-transcripts-scraper`

## Hosted Apify MCP configuration

```json
{
  "mcpServers": {
    "apify": {
      "url": "https://mcp.apify.com"
    }
  }
}
```

Actor-focused version:

```json
{
  "mcpServers": {
    "apify-instagram-transcript": {
      "url": "https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper"
    }
  }
}
```

## Bearer token example

```json
{
  "mcpServers": {
    "apify-instagram-transcript": {
      "url": "https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper",
      "headers": {
        "Authorization": "Bearer <APIFY_TOKEN>"
      }
    }
  }
}
```

## Local stdio alternative

```json
{
  "mcpServers": {
    "apify": {
      "command": "npx",
      "args": ["-y", "@apify/actors-mcp-server@latest"],
      "env": {
        "APIFY_TOKEN": "<APIFY_TOKEN>"
      }
    }
  }
}
```

## Example Gemini CLI prompt

```text
Use Apify MCP to run apple_yang/instagram-transcripts-scraper with this input:

{
  "videoUrl": "https://www.instagram.com/reel/your_reel_id/",
  "sessionid": ""
}

When the run completes, retrieve the full output if necessary and generate:
- transcript summary
- hook
- key points
- CTA
- product mentions
- content brief for a similar short video
```

## Where this fits

- Terminal-based content research
- Batch URL analysis planning
- Transforming transcripts into content briefs
- Generating structured analysis from Actor output

## Limitations

- This repo does not provide a custom Gemini extension.
- This repo does not provide a custom MCP server.
- MCP client behavior may vary by Gemini CLI version.

## Security notes

- Do not store tokens in committed files.
- Use environment variables or secure local config.
- Keep local MCP config files out of public repositories if they contain secrets.

## Related docs

- [Use Instagram Reels Transcript API with Apify MCP](use-with-apify-mcp.md)
- [Prompt recipes for Reels analysis](prompt-recipes-for-reels-analysis.md)
- [AI agent use cases](ai-agent-use-cases.md)
