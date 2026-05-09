# Use Instagram Reels Transcript API with Cursor and VS Code via Apify MCP

Developer tools such as Cursor and VS Code can use MCP-compatible tool configuration to access external tools such as Apify MCP. This repository does not include a custom IDE extension.

Primary Actor: [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)

## How this helps coding assistants

The Actor can help coding assistants inspect transcript output and generate integration code, database schemas, ETL steps, or data pipeline plans.

Typical flow:

```text
Cursor or VS Code
-> MCP-compatible tool configuration
-> Apify MCP
-> Instagram transcript Actor
-> transcript JSON
-> coding assistant generates implementation guidance
```

## Example prompts

```text
Use the Instagram transcript Actor output to generate a TypeScript interface.
```

```text
Create a database schema for storing Reel transcript records, timestamped segments, creator metadata, and processing errors.
```

```text
Write a batch-processing pipeline based on this Actor output.
```

```text
Generate error handling logic for failed Actor runs and records with errMsg.
```

```text
Review this sample Actor output and suggest indexes for search, creator filtering, and transcript lookup.
```

## Security notes

- Do not commit local MCP config containing tokens.
- Use OAuth or environment variables where possible.
- Review tool calls before running write operations.
- Keep Actor output containing sensitive research data out of public issue trackers and screenshots.

## Related docs

- [Use Instagram Reels Transcript API with Apify MCP](use-with-apify-mcp.md)
- [Prompt recipes for Reels analysis](prompt-recipes-for-reels-analysis.md)
- [AI agent use cases](ai-agent-use-cases.md)
