# Use Instagram Reels Transcript API with Apify MCP

## What this guide covers

This guide shows how to expose the Apify Actor
`apple_yang/instagram-transcripts-scraper` to MCP-compatible clients through
Apify MCP.

Use this when you want an AI client or agent to call the Actor, pass an
Instagram Reel URL, retrieve transcript JSON, and then summarize, classify,
translate, or repurpose the transcript.

Primary Actor: [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)

## Prerequisites

- Apify account
- Apify API token or OAuth connection
- MCP-compatible client
- Public Instagram Reel or video URL
- Actor ID: `apple_yang/instagram-transcripts-scraper`

## Recommended setup: Hosted Apify MCP with OAuth

Use the hosted Apify MCP server when your client supports remote MCP server URLs:

```json
{
  "mcpServers": {
    "apify": {
      "url": "https://mcp.apify.com"
    }
  }
}
```

This uses OAuth where the client supports it.

The user signs in to Apify in the browser, which avoids pasting API tokens into
config files.

## Alternative setup: Hosted Apify MCP with Bearer token

Use this only in secure local or server-side configuration:

```json
{
  "mcpServers": {
    "apify": {
      "url": "https://mcp.apify.com",
      "headers": {
        "Authorization": "Bearer YOUR_APIFY_TOKEN"
      }
    }
  }
}
```

Never commit this config if it contains a real token.

## Limit tools to this Actor

Apify MCP can load specific tools and Actors with the `tools` query parameter.

Actor-focused OAuth configuration:

```json
{
  "mcpServers": {
    "apify-instagram-transcript": {
      "url": "https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper"
    }
  }
}
```

Actor-focused Bearer token configuration:

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

If a client does not expose the Actor directly as a named tool, use the generic
Apify MCP tools such as:

- `search-actors`
- `fetch-actor-details`
- `add-actor`
- `call-actor`
- `get-actor-output`

## Local stdio setup

Use local stdio if your client does not support remote MCP server URLs:

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

This requires Node.js 18 or newer. Keep `APIFY_TOKEN` out of committed files.

## How to call this Actor through MCP

There are two common flows.

### Flow A: Direct Actor tool

If the Actor is loaded as a specific tool, ask the AI client to call
`apple_yang/instagram-transcripts-scraper` directly with the Actor input JSON.

### Flow B: Generic Apify tools

If the Actor does not appear as a direct tool:

1. Use `search-actors` with query `instagram transcripts scraper`.
2. Use `fetch-actor-details` for `apple_yang/instagram-transcripts-scraper`.
3. Use `call-actor` with the Actor ID and run input.
4. Use `get-actor-output` if the output preview is incomplete.

Actor input:

```json
{
  "videoUrl": "https://www.instagram.com/reel/your_reel_id/",
  "sessionid": ""
}
```

- `videoUrl` is required.
- `sessionid` is optional.
- Use only public or authorized content.

## Example MCP prompt

```text
Use Apify MCP to run the Actor apple_yang/instagram-transcripts-scraper.

Input:
{
  "videoUrl": "https://www.instagram.com/reel/your_reel_id/",
  "sessionid": ""
}

After the Actor finishes, retrieve the full output if needed and summarize:
1. Main topic
2. Hook
3. Key points
4. CTA
5. Product mentions
6. Reusable content ideas
```

```text
Find the Apify Actor apple_yang/instagram-transcripts-scraper.

Inspect its input schema, run it with this public Instagram Reel URL, and return:
- transcript text
- segment count
- creator username
- any errMsg
```

## Output fields to expect

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

## Troubleshooting

### Actor tool does not appear

Likely causes:

- The client did not load the Actor-specific `tools=` URL.
- The client only exposes generic Apify tools.

Practical next steps:

- Use `https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper`.
- Reconnect the MCP server.
- Use `search-actors` and `call-actor`.

### Authentication error

Likely causes:

- OAuth connection is incomplete.
- Token is missing or invalid.

Practical next steps:

- Reconnect OAuth.
- Check secure config.
- Replace `YOUR_APIFY_TOKEN` with a valid token in local or server-side config.

### Actor run takes too long

Likely causes:

- Transcript extraction can take time depending on content and platform response.

Practical next steps:

- Wait for completion.
- Ask the client to check run status.
- Use direct API examples for production timeouts and retries.

### Output preview is incomplete

Likely causes:

- Some MCP clients truncate tool output previews.

Practical next steps:

- Ask the client to call `get-actor-output`.
- Fetch the dataset items.

### Empty transcript or `errMsg`

Likely causes:

- Reel is unavailable, private, unsupported, or has no usable transcript.

Practical next steps:

- Check `errMsg`.
- Verify the URL is public or authorized.
- Test another Reel URL.

### 429 / rate limits

Likely causes:

- Too many calls or platform/API limits.

Practical next steps:

- Lower concurrency.
- Retry with backoff.
- Monitor Apify usage.

### Client cannot use remote MCP URL

Likely causes:

- The client may only support stdio MCP servers.

Practical next steps:

- Use the local stdio setup with `npx` and `APIFY_TOKEN`.

## Security notes

- Do not paste API tokens into normal chat messages.
- Do not commit MCP config files containing tokens.
- Use OAuth where available.
- Prefer server-side config for production.
- Do not use for private or unauthorized content.

## Related docs

- [Use with ChatGPT via Apify MCP](use-with-chatgpt-mcp.md)
- [Use with Claude via Apify MCP](use-with-claude-mcp.md)
- [Use with Gemini CLI via Apify MCP](use-with-gemini-cli-mcp.md)
- [Use with Cursor and VS Code via Apify MCP](use-with-cursor-vscode-mcp.md)
- [Prompt recipes for Reels analysis](prompt-recipes-for-reels-analysis.md)
- [AI agent use cases](ai-agent-use-cases.md)
