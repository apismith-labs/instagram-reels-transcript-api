# Use Instagram Reels Transcript API with Gemini CLI via Apify MCP

Gemini CLI can be used in developer terminal workflows with MCP-compatible server configuration. This repository does not provide a custom Gemini extension, custom MCP server, or hosted proxy.

Primary Actor: [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)

Gemini CLI MCP documentation: [MCP servers with the Gemini CLI](https://google-gemini.github.io/gemini-cli/docs/tools/mcp-server.html)

## Intended architecture

```text
Gemini CLI
-> MCP server configuration
-> Apify MCP
-> Instagram transcript Actor
-> transcript JSON
-> Gemini analysis
```

The Actor provides transcript data. Gemini CLI can then help inspect output, plan batch analysis, draft content briefs, or generate structured summaries from Actor results.

## Use cases

- Terminal-based content research.
- Batch URL analysis planning.
- Transforming transcripts into content briefs.
- Generating structured analysis from Actor output.
- Reviewing transcript fields before building a database or pipeline.

## Example prompts

```text
Use the Instagram transcript Actor output to summarize this Reel and extract hook, key points, CTA, and product mentions.
```

```text
Given this batch of transcript records, propose a JSON schema for storing content intelligence results.
```

```text
Turn these transcript records into a content brief grouped by theme, creator, and CTA style.
```

## Security notes

- Do not store tokens in committed files.
- Use environment variables or secure local config.
- Keep local MCP config files out of public repositories if they contain secrets.
- Review terminal commands and tool calls before allowing write operations.

## Related docs

- [Use Instagram Reels Transcript API with Apify MCP](use-with-apify-mcp.md)
- [Prompt recipes for Reels analysis](prompt-recipes-for-reels-analysis.md)
- [AI agent use cases](ai-agent-use-cases.md)
