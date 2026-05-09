# Use Instagram Reels Transcript API with ChatGPT via Apify MCP

ChatGPT developer workflows can use MCP-compatible tools in supported environments. This repository does not provide a Custom GPT Action, custom proxy, hosted backend proxy, or full ChatGPT-specific integration yet.

Primary Actor: [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)

## Intended architecture

```text
ChatGPT developer workflow
-> Apify MCP
-> Instagram transcript Actor
-> transcript JSON
-> ChatGPT analysis
```

In this workflow, the Actor handles transcript extraction. ChatGPT then works with the returned JSON fields such as `text`, `segments`, `userName`, `title`, `likeCount`, `commentCount`, `errMsg`, and `url`.

## Example prompts

```text
Analyze this Instagram Reel URL and extract the hook, key points, and CTA.
```

```text
Summarize the transcript and turn it into a blog outline.
```

```text
Compare this Reel transcript against our product positioning.
```

```text
Use the transcript JSON to return a structured table with hook, pain point, offer, proof, CTA, and reusable content ideas.
```

## Security notes

- Do not paste Apify API tokens directly into normal chat messages.
- Use secure MCP app configuration.
- Keep tokens out of committed files and screenshots.
- Review tool calls before using Actor output in downstream automation.

## Related docs

- [Use Instagram Reels Transcript API with Apify MCP](use-with-apify-mcp.md)
- [Prompt recipes for Reels analysis](prompt-recipes-for-reels-analysis.md)
- [AI agent use cases](ai-agent-use-cases.md)
