# Use Instagram Reels Transcript API with Gemini CLI via Apify MCP

## What this guide covers

Connect Gemini CLI to the Apify MCP server and run the Actor
`apple_yang/instagram-transcripts-scraper` from the terminal.

This repository provides no Gemini extension and no custom MCP server.

Primary Actor: [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)

**Verification status.** The transport rules below come from the Gemini CLI MCP documentation and
the Apify MCP server documentation, checked 2026-10-21. **No Gemini CLI session was connected to
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

OAuth-free Bearer token via environment variable (Streamable HTTP):

```json
{
  "mcpServers": {
    "apify-instagram-transcript": {
      "httpUrl": "https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper",
      "headers": {
        "Authorization": "Bearer ${APIFY_TOKEN}"
      },
      "timeout": 60000
    }
  }
}
```

If your Gemini CLI build does not interpolate `${...}` in `headers`, keep the token in the
environment and let the client's own auth flow handle it rather than pasting a literal value into
the file.

Local stdio alternative:

```json
{
  "mcpServers": {
    "apify": {
      "command": "npx",
      "args": ["-y", "@apify/actors-mcp-server@latest"],
      "env": {
        "APIFY_TOKEN": "YOUR_APIFY_TOKEN"
      },
      "timeout": 30000
    }
  }
}
```

Notes:

- `includeTools` and `excludeTools` narrow what the server exposes; `excludeTools` wins when a
  name appears in both.
- `trust: true` skips tool-call confirmation. Do not enable it for a server that can start
  billable Runs unless you have a spend cap in place.
- Avoid underscores in server names; the docs warn that name parsing is affected.
- Add the server with the CLI (`gemini mcp add`) if you prefer not to hand-edit JSON; check
  `gemini mcp add --help` for the transport flag names in your installed version.

## Which tools to use

| Step | Tool |
| --- | --- |
| Find the Actor | `search-actors` |
| Read the input schema | `fetch-actor-details` |
| Start the Run | `call-actor` — returns Run and storage IDs, not items |
| Check the Run | `get-actor-run` |
| Read the transcript | `get-dataset-items` with the Dataset ID, paging with `limit`/`offset` |
| Look at logs | `get-actor-run-log` |

`add-actor` and `get-actor-output` are not part of the current tool set. If Gemini CLI suggests
them, it is recalling older documentation — re-map to `get-dataset-items`.

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

## Cost

- Each Run is billable Apify usage; the Actor has multiple billing events.
- Request `maxItems` / `maxTotalChargeUsd` in `callOptions` where supported before any loop over
  URLs. Their enforcement as a hard billing ceiling for this Actor has not been verified.
- Incomplete output is a reason to re-read the dataset, never to re-run.

Pricing: <https://apify.com/apple_yang/instagram-transcripts-scraper/pricing>

## Still unverified

- Whether your Gemini CLI version interpolates environment variables inside `headers`.
- Whether an Actor-scoped URL loads the Actor as a directly callable tool or only through
  `call-actor`.
- Whether pagination of `get-dataset-items` is exposed to the model in this client.

## Related docs

- [Use Instagram Reels Transcript API with Apify MCP](use-with-apify-mcp.md)
- [Use with ChatGPT](use-with-chatgpt-mcp.md)
- [Use with Claude](use-with-claude-mcp.md)
- [Use with Cursor and VS Code](use-with-cursor-vscode-mcp.md)
- [Prompt recipes for Reels analysis](prompt-recipes-for-reels-analysis.md)
- [AI agent use cases](ai-agent-use-cases.md)
- Official: [Apify MCP server documentation](https://docs.apify.com/mcp)
