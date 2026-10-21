# Use Instagram Reels Transcript API with Claude via Apify MCP

## What this guide covers

Three different "Claude" surfaces are commonly confused, and they do **not** share one config
format:

| Surface | How Apify MCP is attached |
| --- | --- |
| Claude on the web (claude.ai) and Claude Desktop | A **remote custom connector** — configured in the UI, not in a JSON file |
| Claude Code (CLI) | A CLI command, `claude mcp add` |
| Any client/version that still reads an MCP JSON config | `claude_desktop_config.json` with a `mcpServers` object |

This repository provides no Claude Skill, SDK wrapper, custom MCP server, or hosted proxy.

Primary Actor: [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)

**Verification status.** The three paths below were checked against
<https://docs.apify.com/integrations/claude-desktop> and the Claude Code MCP documentation on
2026-10-21. **No Claude client was connected to this Actor while writing this.** Menu placement
and available scopes vary by client version and, on Team/Enterprise plans, by administrator
policy.

## Prerequisites

- A Claude client (web, Desktop, or Code)
- An Apify account
- A public Instagram Reel/video/post URL
- The Actor ID: `apple_yang/instagram-transcripts-scraper`

## Path A — remote connector (recommended)

This is the officially recommended path. The connector runs on Anthropic's side, so **the same
connector works in Claude Desktop and on claude.ai**, updates automatically, and uses OAuth
instead of a token in a file.

1. Open **Settings → Connectors**.
2. Select **Add**, then **Add custom connector**.
3. Name it, for example `Apify`.
4. Set the remote MCP server URL to `https://mcp.apify.com`.
5. Continue. Claude probes the server and pre-fills the detected authentication settings; keep
   the detected OAuth settings and add the connector.
6. On first connection a browser opens; sign in to Apify and approve access.

To expose only this Actor, generate the URL in the configurator at <https://mcp.apify.com/> and
use that instead of the bare endpoint.

There is also a one-click option: search for "Apify" in the Claude Desktop connector directory,
or open the published `.mcpb` bundle from the Apify MCP server releases page.

**Team and Enterprise plans:** an Owner or Primary Owner may need to add the connector for the
whole organisation before individuals can use it.

## Path B — Claude Code (CLI)

Claude Code does not use the connector dialog; it takes a command:

```bash
claude mcp add --transport http apify https://mcp.apify.com
```

With an explicit scope and an Actor-scoped URL:

```bash
claude mcp add --transport http apify \
  --scope user \
  "https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper"
```

Scope flags decide where the server is stored and who else sees it: `local` (default, current
project only), `project` (shared through the project's `.mcp.json`), `user` (all your projects).
Use `--header "Authorization: Bearer ..."` only if you must use a token instead of OAuth, and
keep that command out of shell history and shared scripts. Verify the exact flags with
`claude mcp add --help` in your installed version.

## Path C — local stdio via JSON

Use this only if your client reads a JSON config file and cannot use a remote connector. The file
is named `claude_desktop_config.json`; its location depends on operating system and client
version, so find it from the client's settings rather than assuming a path.

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

Restart the client after editing the file. Requires Node.js 18 or newer.

This is the **only** one of the three paths that puts a credential in a file. If Node.js is
installed only through a version manager (nvm, fnm, nodenv, Volta), some Claude Desktop surfaces
cannot find the binary; the remote connector avoids that class of problem entirely.

## Which tools the agent should use

| Step | Tool |
| --- | --- |
| Discover the Actor | `search-actors` |
| Read its input schema | `fetch-actor-details` |
| Start the Run | `call-actor` (returns run and storage IDs, not items) |
| Check the Run | `get-actor-run` |
| Read the transcript | `get-dataset-items` with the Dataset ID, paging with `limit`/`offset` |

`add-actor` and `get-actor-output` from older guides no longer exist. If Claude emits one, it is
pattern-matching on outdated documentation — ask it to list `tools/list` and re-map the step.

## Example prompt

```text
Use Apify MCP to run apple_yang/instagram-transcripts-scraper on this public Reel URL:
https://www.instagram.com/reel/your_reel_id/

Send it as videoUrl. Then:
1. Poll the Run until it reaches a terminal status and tell me which status it was.
2. Read the dataset items and report the item count before summarising anything.
3. Quote any errMsg verbatim; an item with errMsg is a failure even if the Run succeeded.
4. Then summarise: hook, key talking points, CTA, product or brand mentions.

If the dataset appears truncated, page through it with offset instead of starting another Run.
```

## Cost

- Each Run is billable; the Actor has more than one billing event, so the Store unit price is not
  the total cost of a video.
- Request `maxItems` and `maxTotalChargeUsd` in `callOptions` where supported. Their enforcement
  as a hard billing ceiling for this Actor has not been verified.
- Do not re-run because output looked incomplete — re-read the dataset.

Pricing: <https://apify.com/apple_yang/instagram-transcripts-scraper/pricing>

## Credentials

- Path A (connector) is the safest: OAuth, no token stored locally.
- Do not paste tokens into a Claude conversation. The transcript of a conversation is not a
  secret store.
- Do not commit `claude_desktop_config.json` or a project `.mcp.json` containing a real token.
- Do not use the Actor for private or unauthorised content.

## Still unverified

- Which of the three paths is available in your specific Claude build and plan.
- Whether the connector exposes pagination for large datasets, or truncates them.
- Whether an Actor-scoped URL survives connector updates without re-adding.

## Related docs

- [Use Instagram Reels Transcript API with Apify MCP](use-with-apify-mcp.md)
- [Use with ChatGPT](use-with-chatgpt-mcp.md)
- [Use with Gemini CLI](use-with-gemini-cli-mcp.md)
- [Use with Cursor and VS Code](use-with-cursor-vscode-mcp.md)
- [Prompt recipes for Reels analysis](prompt-recipes-for-reels-analysis.md)
- [AI agent use cases](ai-agent-use-cases.md)
- Official: [Apify Claude Desktop integration](https://docs.apify.com/integrations/claude-desktop)
