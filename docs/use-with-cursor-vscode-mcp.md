# Use Instagram Reels Transcript API with Cursor and VS Code via Apify MCP

## What this guide covers

Both editors can reach Apify MCP, but **they do not share a config format**. Copying one JSON
block between them is a common failure: Cursor expects a top-level `mcpServers` object, while VS
Code's own format expects a top-level `servers` object with an explicit transport `type`.

This repository ships no IDE extension.

Primary Actor: [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)

**Verification status.** Formats below were taken from the Cursor MCP documentation, the VS Code
MCP configuration reference, and the Apify Cursor integration page on 2026-10-21. **No editor was
connected to this Actor while writing this.** Field names and file locations change between
releases; if a key is rejected, check your editor's current reference before improvising.

## Prerequisites

- Cursor, or VS Code with MCP-capable agent tooling
- An Apify account
- A public Instagram Reel/video/post URL
- The Actor ID: `apple_yang/instagram-transcripts-scraper`

---

## Cursor

### Option 1 — Apify plugin (official recommendation)

Apify publishes a Cursor plugin that bundles the MCP server, a routing agent, and skills:

1. In Cursor chat, run `/add-plugin apify`, or install from **Settings → Plugins → search
   "Apify" → Get**.
2. Choose the scope: this project only, or all projects.
3. Open **Settings → Tools & MCPs**, find **Apify MCP**, and click **Connect**.
4. Approve the OAuth prompt in the browser.

Read-only tools (`search-actors`, `fetch-actor-details`) work before signing in; running Actors
and reading datasets require the OAuth connection. The connection persists across sessions.

If Cursor runs in a remote session, devcontainer, or over SSH with no browser, set `APIFY_TOKEN`
in the environment before starting Cursor instead of using OAuth.

### Option 2 — manual `mcp.json`

Project-scoped: `.cursor/mcp.json`. Global: `~/.cursor/mcp.json`. The top-level key is
`mcpServers`.

Remote server with OAuth (no token in the file):

```json
{
  "mcpServers": {
    "apify-instagram-transcript": {
      "url": "https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper"
    }
  }
}
```

With a Bearer token, referenced from the environment rather than written literally:

```json
{
  "mcpServers": {
    "apify-instagram-transcript": {
      "url": "https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper",
      "headers": {
        "Authorization": "Bearer ${env:APIFY_TOKEN}"
      }
    }
  }
}
```

Cursor's remote entries use `url`, and the editor works out from the endpoint whether it is an
SSE or a Streamable HTTP server. Local stdio servers instead use `command`, `args`, and `env`.
If your Cursor version rejects a `url`-only remote entry, check its current reference for the
transport field it expects rather than copying a VS Code config.

---

## VS Code

VS Code's own format is **not** `mcpServers`. Two different things are easy to mix up:

| Format | Top-level key | Where it lives |
| --- | --- | --- |
| VS Code format | `servers` | Workspace `.vscode/mcp.json`, or the user-profile `mcp.json` |
| Portable / Copilot config | `mcpServers` | Workspace-root `.mcp.json`, or `~/.copilot/mcp-config.json` (`$COPILOT_HOME/mcp-config.json`) |

The VS Code format carries an explicit transport `type`. Remote HTTP:

```json
{
  "servers": {
    "apify-instagram-transcript": {
      "type": "http",
      "url": "https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper"
    }
  }
}
```

Local stdio, same `servers` wrapper:

```json
{
  "servers": {
    "apify": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@apify/actors-mcp-server@latest"],
      "env": {
        "APIFY_TOKEN": "YOUR_APIFY_TOKEN"
      }
    }
  }
}
```

Portable variant, for a client that expects the shared format at the workspace root:

```json
{
  "mcpServers": {
    "apify-instagram-transcript": {
      "url": "https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper"
    }
  }
}
```

Notes:

- Prefer OAuth or an input variable over a literal token, and never commit a token-bearing
  workspace config.
- Portable configurations do not support VS Code input variables or env files, which is one more
  reason not to translate a config mechanically between the two formats.
- `MCP: Add Server` in the Command Palette writes a correct config for you and is less
  error-prone than hand-editing.

---

## What to ask the assistant to do

The workflow is the same in both editors:

| Step | Tool |
| --- | --- |
| Find the Actor | `search-actors` |
| Read the input schema | `fetch-actor-details` |
| Start the Run | `call-actor` — returns run and storage IDs |
| Check the Run | `get-actor-run` |
| Read items | `get-dataset-items` with the Dataset ID, paging with `limit`/`offset` |

`add-actor` and `get-actor-output` do not exist in the current server. If the assistant offers
them, it is working from stale documentation.

## Example prompts

Generate a typed interface from real data, not from a guess:

```text
Use the Apify MCP Actor apple_yang/instagram-transcripts-scraper on this public Reel URL:
https://www.instagram.com/reel/your_reel_id/

Read the actual dataset items first, then generate a TypeScript interface from the fields that
are present. Mark optional fields as optional and keep unknown extra fields rather than dropping
them. Do not invent fields that are absent from the items.
```

Generate error handling that matches this repository's semantics:

```text
Using the Apify MCP tools, run apple_yang/instagram-transcripts-scraper once and show me:
- the Run status
- the number of dataset items
- whether any item has a non-empty errMsg

Then write error handling for three distinct cases: Run failed, dataset empty, and item with
errMsg. Do not treat an HTTP or tool-call success as a transcript.
```

Plan a batch job without overspending:

```text
I have 20 public Reel URLs. Plan a batch job that runs the Actor once per URL through the
Python example in this repository. For each URL, explain how I detect success, where the Run ID
is recorded, and how I avoid re-running a URL whose Run already exists. Do not write code that
retries by creating a new Run.
```

## Cost

- Each Run bills against your Apify plan; the Actor has multiple billing events.
- Cursor's own usage is charged separately — a Run costs on both sides.
- Request `maxItems` / `maxTotalChargeUsd` in `callOptions` where supported, and re-read datasets
  instead of re-running when output looks incomplete. Enforcement as a hard billing ceiling for
  this Actor has not been verified.
- Skills that edit project files make real changes; review diffs before committing.

Pricing: <https://apify.com/apple_yang/instagram-transcripts-scraper/pricing>

## Credentials

- OAuth is preferred in both editors; it keeps tokens out of project files entirely.
- `.cursor/mcp.json` and `.vscode/mcp.json` are frequently committed by accident. If a config
  contains a token, either interpolate it from the environment or add the file to `.gitignore`.
- Do not paste tokens into a chat prompt or a screenshot.
- Review tool calls before approving them, especially anything that writes to your project.

## Still unverified

- Whether Cursor's plugin path or the manual `mcp.json` path is appropriate for your version and
  team policy.
- Whether VS Code tools load from `.vscode/mcp.json` or the portable `.mcp.json` in your harness.
- Whether either client surfaces pagination for `get-dataset-items` or silently truncates.

## Related docs

- [Use Instagram Reels Transcript API with Apify MCP](use-with-apify-mcp.md)
- [Use with ChatGPT](use-with-chatgpt-mcp.md)
- [Use with Claude](use-with-claude-mcp.md)
- [Use with Gemini CLI](use-with-gemini-cli-mcp.md)
- [Prompt recipes for Reels analysis](prompt-recipes-for-reels-analysis.md)
- [AI agent use cases](ai-agent-use-cases.md)
- Official: [Apify Cursor integration](https://docs.apify.com/integrations/cursor),
  [VS Code MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)
