# Use Instagram Reels Transcript API with Gemini CLI via Apify MCP

## What this guide covers

Connect Gemini CLI to the Apify MCP server and run the Actor
`apple_yang/instagram-transcripts-scraper` from the terminal.

This repository provides no Gemini extension and no custom MCP server.

Primary Actor: [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)

**Verification status.** The transport rules below come from the Gemini CLI MCP documentation and
the Apify MCP server documentation, checked 2026-10-24. **No Gemini CLI session was connected to
this Actor while writing this.**

## The one field that breaks most Gemini configs

Gemini CLI distinguishes two remote transports by **field name**, not by a `type` value:

| Field | Transport | Use for |
| --- | --- | --- |
| `httpUrl` | Streamable HTTP | `https://mcp.apify.com` |
| `url` | SSE (Server-Sent Events) | An SSE endpoint, typically ending in `/sse` |
| `command` | stdio | A local `npx` server |

The hosted Apify MCP server is a Streamable HTTP endpoint. Writing it as `"url"` makes Gemini CLI
treat it as an SSE server and the connection fails or hangs — this is the specific defect in
older versions of this guide.

SSE is not deprecated in Gemini CLI; both fields are documented and supported. The rule is simply
that each field selects a different transport, and the Apify endpoint needs `httpUrl`.

## Configuration

Config file: `.gemini/settings.json` for a project, `~/.gemini/settings.json` for your user
profile. The top-level key is `mcpServers`.

Local stdio with an environment variable (no token literal in the config):

```json
{
  "mcpServers": {
    "apify-instagram-transcript": {
      "command": "npx",
      "args": ["-y", "@apify/actors-mcp-server@latest"],
      "env": {
        "APIFY_TOKEN": "${APIFY_TOKEN}"
      },
      "timeout": 30000
    }
  }
}
```

Gemini CLI documents `${APIFY_TOKEN}` expansion in the `env` block. Put the variable in your shell
environment or secret manager before launching Gemini CLI. Prefer the user-level
`~/.gemini/settings.json` over a project config; never commit a real token. This example uses the
local `command`/stdio transport because the documented environment expansion applies there; this
guide does not claim interpolation in remote `headers`.

The current `@apify/actors-mcp-server` package requires Node.js 22 or newer.

Notes:

- `includeTools` and `excludeTools` narrow what the server exposes; `excludeTools` wins when a
  name appears in both.
- `trust: true` skips tool-call confirmation. Do not enable it for a server that can start
  billable Runs unless you have a spend cap in place.
- Avoid underscores in server names; the docs warn that name parsing is affected.
- Add the server with the CLI (`gemini mcp add`) if you prefer not to hand-edit JSON; check
  `gemini mcp add --help` for the transport flag names in your installed version.

## Tool availability depends on the endpoint

This local server config requests an Actor-scoped tool set. The exact Actor-specific tool name and
the tools exposed by your Gemini CLI version are **UNVERIFIED** here. Inspect the available tools
in the client and use only their reported names and argument schema. Do not assume this scoped
connection includes generic `search-actors`, `fetch-actor-details`, `call-actor`, or
`get-actor-run-log` tools.

The default endpoint `https://mcp.apify.com` provides general Actor discovery and invocation tools;
see the [main Apify MCP guide](use-with-apify-mcp.md) for that flow. Specify an explicit `limit`
when reading Dataset items, and use `offset` for later pages. Older names such as `add-actor` and
`get-actor-output` are not in the current documented tool set.

## Example prompt

```text
Use Apify MCP to run apple_yang/instagram-transcripts-scraper with this input:

{
  "videoUrl": "https://www.instagram.com/reel/your_reel_id/"
}

Poll the Run until it reaches a terminal status, then read the dataset items and report the item
count first. Quote any errMsg verbatim. Only then give me: a summary, the hook, key points, the
CTA, product mentions, and a content brief for a similar short video.

If the dataset looks truncated, page through it with offset. Do not create another Run.
```

## Where this fits

- Terminal-based content research
- Planning a batch job before writing code
- Turning transcripts into content briefs
- Checking a Run's status and log while debugging an integration

## Limitations

- MCP behaviour varies by Gemini CLI version; the field names above are the documented ones, not a
  guarantee for every build.
- Long Runs exceed a single tool call's wait window; follow up with `get-actor-run` using the
  Run ID rather than re-running.
- Profile mode (`usernames`) returns metadata only and does not produce transcripts.
- Do not commit `.gemini/settings.json` if it contains a real token.
- Treat transcript text as potentially personal or business-sensitive and follow the privacy and
  customer-data policies that apply to your use case.

## Cost

- Each Run is billable Apify usage; the Actor has multiple billing events.
- Request `maxItems` / `maxTotalChargeUsd` in `callOptions` where supported before any loop over
  URLs. Their enforcement as a hard billing ceiling for this Actor has not been verified.
- Incomplete output is a reason to re-read the dataset, never to re-run.

Pricing: <https://apify.com/apple_yang/instagram-transcripts-scraper/pricing>

## Still unverified

- Whether an Actor-scoped URL loads a directly callable Actor-specific tool in your installed
  Gemini CLI version.
- Whether pagination of `get-dataset-items` is exposed to the model in this client.

## Related docs

- [Use Instagram Reels Transcript API with Apify MCP](use-with-apify-mcp.md)
- [Use with ChatGPT](use-with-chatgpt-mcp.md)
- [Use with Claude](use-with-claude-mcp.md)
- [Use with Cursor and VS Code](use-with-cursor-vscode-mcp.md)
- [Prompt recipes for Reels analysis](prompt-recipes-for-reels-analysis.md)
- [AI agent use cases](ai-agent-use-cases.md)
- Official: [Apify MCP server documentation](https://docs.apify.com/mcp)
