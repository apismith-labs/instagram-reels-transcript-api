# Use Instagram Reels Transcript API with ChatGPT via Apify MCP

## What this guide covers

This guide shows how to connect a ChatGPT developer workflow to Apify MCP and
use the Actor `apple_yang/instagram-transcripts-scraper`.

This repository does not provide a Custom GPT Action, custom MCP server, hosted backend proxy, or OpenAPI proxy yet.

Primary Actor: [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)

## Prerequisites

- ChatGPT account with Developer Mode or custom connector access
- Apify account
- Apify Actor: `apple_yang/instagram-transcripts-scraper`
- Public Instagram Reel URL

## Create the Apify MCP connector in ChatGPT

1. Enable Developer Mode if needed.
2. Go to Settings > Apps & Connectors > Create.
3. Name: `Apify Instagram Transcript MCP`
4. Description: `Run the Instagram Reels transcript Actor through Apify MCP.`
5. MCP Server URL:
   - General Apify MCP: `https://mcp.apify.com`
   - Actor-focused version: `https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper`
6. Authentication: OAuth where available.
7. Authorize Apify in the browser.

Some ChatGPT connector settings may vary.

If the connector cannot be edited after creation, create a new connector with
the desired tools URL.

## Use it in a chat

Start a new chat, add or select the Apify connector, then ask ChatGPT to run or locate the Actor.

```text
Use the Apify MCP connector to run the Actor
apple_yang/instagram-transcripts-scraper with this public Instagram Reel URL:

https://www.instagram.com/reel/your_reel_id/

Use this input:
{
  "videoUrl": "https://www.instagram.com/reel/your_reel_id/",
  "sessionid": ""
}

Then return:
- transcript text
- segment count
- creator username
- title/caption if available
- errMsg if present
- a summary with hook, key points, and CTA
```

## If ChatGPT cannot find the Actor

Ask ChatGPT to:

- Search Apify Actors for `instagram transcripts scraper`
- Fetch Actor details for `apple_yang/instagram-transcripts-scraper`
- Add or call that Actor
- Retrieve full output if needed

Troubleshooting prompt:

```text
Search Apify Actors for "instagram transcripts scraper".

If you find apple_yang/instagram-transcripts-scraper, fetch its Actor details,
inspect the input schema, then call it with this input:
{
  "videoUrl": "https://www.instagram.com/reel/your_reel_id/",
  "sessionid": ""
}
If the output preview is incomplete, retrieve the full Actor output.
```

## Limitations

- This repo does not provide a Custom GPT Action or backend proxy yet.
- ChatGPT UI may change.
- Actor runs may take time.
- Some outputs may require `get-actor-output` if preview is truncated.

## Security notes

- Do not paste Apify API tokens directly into normal chat messages.
- Use secure MCP app configuration.
- Keep tokens out of committed files and screenshots.
- Use OAuth where available.

## Related docs

- [Use Instagram Reels Transcript API with Apify MCP](use-with-apify-mcp.md)
- [Prompt recipes for Reels analysis](prompt-recipes-for-reels-analysis.md)
- [AI agent use cases](ai-agent-use-cases.md)
