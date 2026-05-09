# Use Instagram Reels Transcript API with Apify MCP

Apify MCP lets compatible AI applications and agents interact with the Apify platform through the Model Context Protocol. The Instagram transcript Actor can be used as a tool to convert an Instagram Reel URL into transcript text, timestamped segments, and metadata.

Primary Actor: [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)

Apify MCP documentation: [Apify MCP server](https://docs.apify.com/platform/integrations/mcp)

## Conceptual workflow

```text
User provides Instagram Reel URL
-> AI client / agent
-> Apify MCP
-> apple_yang/instagram-transcripts-scraper
-> transcript JSON
-> LLM analysis
-> structured insights
```

The LLM can then summarize, analyze, classify, translate, or repurpose the transcript.

## When MCP is useful

- You want an AI assistant to call the Actor as part of a broader workflow.
- You want tool calls and transcript analysis in one AI client.
- You are building research, content intelligence, or agent workflows around Reel URLs.
- You want the AI system to inspect Actor output and generate structured summaries, tags, or next actions.

## When direct API examples are better

- You need a production backend or scheduled batch job.
- You want strict control over retries, storage, logging, and costs.
- You are integrating the Actor into an application pipeline.
- You need deterministic input/output handling outside an interactive AI client.

Use the language examples in this repository for direct API integration:

- [cURL](../examples/curl/)
- [Python](../examples/python/)
- [Node.js](../examples/nodejs/)
- [Java](../examples/java/)
- [Go](../examples/go/)
- [Rust](../examples/rust/)

## Security notes

- Never expose Apify API tokens in public prompts, screenshots, or client-side code.
- Use secure connector configuration, environment variables, OAuth if available, or server-side configuration.
- Do not commit local MCP configuration files if they contain secrets.
- Do not use the Actor for private or unauthorized content.

## Related docs

- [Use with ChatGPT via Apify MCP](use-with-chatgpt-mcp.md)
- [Use with Claude via Apify MCP](use-with-claude-mcp.md)
- [Use with Gemini CLI via Apify MCP](use-with-gemini-cli-mcp.md)
- [Use with Cursor and VS Code via Apify MCP](use-with-cursor-vscode-mcp.md)
- [Prompt recipes for Reels analysis](prompt-recipes-for-reels-analysis.md)
- [AI agent use cases](ai-agent-use-cases.md)
