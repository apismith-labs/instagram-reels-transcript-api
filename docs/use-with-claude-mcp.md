# Use Instagram Reels Transcript API with Claude via Apify MCP

## What this guide covers

This guide shows how to use the Actor
`apple_yang/instagram-transcripts-scraper` in Claude-compatible MCP workflows
through Apify MCP.

This repository does not include a separate Claude-specific SDK wrapper,
Claude Skill, custom MCP server, or hosted proxy yet.

Primary Actor: [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)

## Prerequisites

- Claude-compatible MCP client
- Apify account
- Apify OAuth connection or `APIFY_TOKEN`
- Public Instagram Reel URL
- Actor ID: `apple_yang/instagram-transcripts-scraper`

## Hosted Apify MCP configuration

OAuth-style remote configuration:

```json
{
  "mcpServers": {
    "apify": {
      "url": "https://mcp.apify.com"
    }
  }
}
```

Actor-focused configuration:

```json
{
  "mcpServers": {
    "apify-instagram-transcript": {
      "url": "https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper"
    }
  }
}
```

## Bearer token configuration

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

Only use Bearer token config in secure local or server-side settings. Do not commit token config files.

## Local stdio setup

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

Use this when the client does not support remote MCP URLs. It requires Node.js 18 or newer.

## Example Claude prompt

```text
Use Apify MCP to call the Actor apple_yang/instagram-transcripts-scraper.

Input:
{
  "videoUrl": "https://www.instagram.com/reel/your_reel_id/",
  "sessionid": ""
}

After the Actor finishes, retrieve the full output if needed and produce:
1. A short summary
2. The main hook
3. Key talking points
4. CTA
5. Product or brand mentions
6. Suggestions for a similar Reel script
```

## Direct Actor tool vs generic Apify tools

- If the Actor appears as a direct tool, call it directly.
- If not, use `search-actors`, `fetch-actor-details`, `call-actor`, and `get-actor-output`.

## Claude Skill note

This repository does not include a Claude Skill yet.

A Claude Skill may be added later as a separate reusable workflow package.

## Security notes

- Keep Apify tokens out of public prompts and screenshots.
- Use secure local or server-side connector configuration.
- Do not use the Actor for private or unauthorized content.

## Related docs

- [Use Instagram Reels Transcript API with Apify MCP](use-with-apify-mcp.md)
- [Prompt recipes for Reels analysis](prompt-recipes-for-reels-analysis.md)
- [AI agent use cases](ai-agent-use-cases.md)
