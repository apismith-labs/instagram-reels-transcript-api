# Use Instagram Reels Transcript API with Claude via Apify MCP

Claude-compatible MCP workflows can use Apify MCP to call the Instagram transcript Actor. This repository does not include a separate Claude-specific SDK wrapper, Claude Skill, custom MCP server, or hosted proxy yet.

Primary Actor: [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)

## Intended architecture

```text
Claude or Claude-compatible MCP client
-> Apify MCP
-> Instagram transcript Actor
-> structured transcript data
-> Claude analysis
```

The Actor returns transcript JSON. Claude can then summarize the Reel, extract messaging patterns, compare creators, or generate structured research notes.

## Example prompts

### Competitor content analysis

```text
Use the Instagram Reel transcript data to analyze this competitor post. Identify the hook, target audience, pain points, product positioning, CTA, and 5 content ideas we could test without copying.
```

### Ad creative analysis

```text
Review this Reel transcript as ad creative research. Extract the opening hook, offer framing, objections handled, proof points, urgency, CTA, and likely reason this creative might perform.
```

### Creator research

```text
Analyze this creator's Reel transcript and metadata. Summarize their content style, recurring topics, audience assumptions, and whether they appear aligned with a B2B or consumer campaign.
```

### Campaign research

```text
Compare these Reel transcript records and produce a campaign research brief with themes, repeated claims, audience language, top hooks, and recommended next tests.
```

## Security notes

- Keep Apify tokens out of public prompts and screenshots.
- Use secure local or server-side connector configuration.
- Avoid committing MCP configuration files that contain secrets.
- Review tool calls before running workflows that write to files, databases, or external systems.

## Related docs

- [Use Instagram Reels Transcript API with Apify MCP](use-with-apify-mcp.md)
- [Prompt recipes for Reels analysis](prompt-recipes-for-reels-analysis.md)
- [AI agent use cases](ai-agent-use-cases.md)
