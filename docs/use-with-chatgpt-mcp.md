# Use Instagram Reels Transcript API with ChatGPT via Apify MCP

## What this guide covers

This guide wires ChatGPT to the Apify MCP server so it can run the Actor
`apple_yang/instagram-transcripts-scraper` and read the transcript out of the resulting dataset.

This repository does not provide a Custom GPT Action, OpenAPI proxy, hosted backend, or custom
MCP server.

Primary Actor: [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)

**Verification status.** The setup below follows the official Apify ChatGPT integration page
(<https://docs.apify.com/integrations/chatgpt>) and the Apify MCP server documentation
(<https://docs.apify.com/mcp>), checked 2026-10-24. **No ChatGPT connection to this Actor was
made while writing this.** ChatGPT's connector UI, plan gating, and rollout differ between
accounts, so treat the menu names as "look for something like this", not as a fixed script.

## Prerequisites

- An OpenAI account with ChatGPT access
- **Developer mode enabled** in ChatGPT — custom connectors are not exposed without it
- An Apify account, authorised through OAuth during connector creation
- A public Instagram Reel/video/post URL
- The Actor ID: `apple_yang/instagram-transcripts-scraper`

## What ChatGPT can and cannot be assumed to have

Not every ChatGPT user sees the same feature set. Custom connectors depend on developer mode,
your plan, and a staged rollout. If the menu described below is absent, that is a product
availability issue — not something this Actor or this repository can fix. In that case use the
API examples ([Python](../examples/python/README.md), [Node.js](../examples/nodejs/README.md),
[cURL](../examples/curl/README.md)) or the MCP setup in
[use-with-apify-mcp.md](use-with-apify-mcp.md).

ChatGPT's remote connector authenticates with **OAuth only**; there is no "paste a Bearer token"
field in the connector dialog. Do not try to smuggle a token into the URL — see
[Credentials](#credentials).

## Create the connector

1. Enable developer mode in ChatGPT. When it is active, the message input is visually marked.
2. Open **Settings → Apps & Connectors → Create**. If there is no **Create** option, developer
   mode is off or the feature is unavailable for your account; reload and re-check.
3. Fill in:
   - **Name** — for example `Apify Instagram Transcript MCP`
   - **Description** — for example `Run the Instagram Reels transcript Actor through Apify MCP`
   - **MCP Server URL** — `https://mcp.apify.com` for the default tool set, or the
     Actor-scoped URL below
   - **Authentication** — OAuth
4. Select **Create**. ChatGPT redirects to Apify; sign in and approve access.
5. You should return to a success message listing the tools the server exposes.

Actor-scoped URL:

```text
https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper
```

**ChatGPT cannot edit the tool list of an existing connector.** To change which tools or Actors
are loaded, create a new connector with the URL you want. This is also why the Actor-scoped URL
is worth getting right the first time.

One side effect worth knowing: OpenAI may show a safety warning when the connector includes
social-media scraping tools, because those tools can fetch data about people. That warning comes
from OpenAI, not from this Actor, and it does not indicate the setup is wrong.

## Use it in a chat

1. Open a new chat.
2. Use the **+** button near the composer, then **More**, and pick your Apify connector. The
   connector is per-conversation; enabling it in settings is not enough.
3. Grant tool permissions when prompted — ChatGPT asks the first time each tool is used.
4. Ask for the run, in plain language, with the URL included.

```text
Use the Apify Instagram Transcript MCP connector to run
apple_yang/instagram-transcripts-scraper with this public Reel URL:
https://www.instagram.com/reel/your_reel_id/

Send it as videoUrl. Keep the Run ID and Dataset ID.

When the Run finishes, read the dataset items — not just the preview — and then report:
- errMsg, quoted verbatim, if any item has one
- the transcript text
- how many segments it has
- the creator username
- a short summary: hook, key points, CTA

If the dataset looks cut off, page through it with offset. Do not start a second Run to
retrieve the rest.
```

## Tool availability depends on the endpoint

This guide's recommended URL above is Actor-scoped. Its exact Actor-specific tool name and the
tools ChatGPT actually exposes are **UNVERIFIED** here. Inspect the connector's tool list after
creation and use only the names and argument schema shown there; do not assume it exposes generic
`search-actors`, `fetch-actor-details`, or `call-actor` tools.

The default endpoint `https://mcp.apify.com` provides the general Actor discovery/invocation and
documentation tools. The main [Apify MCP guide](use-with-apify-mcp.md) documents that flow and the
default `call-actor` schema. For either endpoint, request a Dataset `limit` explicitly and use
`offset` for later pages. Never infer that a tool call succeeded merely because the assistant
claims it did; inspect Run status and returned Dataset items.

Older names such as `add-actor` and `get-actor-output` are not part of the current documented tool
set. Ask ChatGPT to list the tools it actually has rather than guessing a replacement.

For a known Run, the Dataset ID was observed at
`structuredContent.storages.datasets.default.id` in `get-actor-run`; Dataset records were
observed at `structuredContent.items` in `get-dataset-items` (**Observed on 2026-10-25, Apify MCP
via Codex Apify plugin**). This is evidence from one client/server version, not a protocol
guarantee; the ChatGPT connector was not tested. `content` text blocks and `structuredContent` are
distinct representations. Do not treat `{type, text}` blocks as Dataset rows. Handle `isError`
when absent, `false`, or `true`; only `true` explicitly indicates a tool error. The original
`call-actor` result shape is unverified. Recover existing data with `get-actor-run` followed by
`get-dataset-items`; do not invoke `call-actor` to recover a Run.

## If ChatGPT cannot find or call the Actor

```text
Search Apify Store for "instagram transcripts scraper".

Then fetch the Actor details for apple_yang/instagram-transcripts-scraper and show me its
input schema. Do not run it yet.

If you cannot load it through the connector, tell me which tools you actually have available
instead of guessing a tool name.
```

Common causes: the connector was created with a URL that does not include the Actor; the
connector is enabled in settings but not attached to this conversation; tool permissions are
blocked; OAuth authorisation never completed.

## Cost

- Each Actor Run is billable Apify usage, and the Actor has multiple billing events.
- An incomplete-looking answer is not a reason to re-run. Ask for `get-dataset-items` with a
  higher `limit` or a later `offset`.
- `maxItems` is an item-count option for pay-per-result Actors; it is not a spending cap and is
  not presented here as a cost control for this pay-per-event Actor. Where the live tool schema
  supports it, `maxTotalChargeUsd` is the relevant requested per-Run protective option. It is not
  an absolute final-invoice guarantee, and server-side enforcement for this Actor has not been
  Live-verified here.

Pricing: <https://apify.com/apple_yang/instagram-transcripts-scraper/pricing>

## Credentials

- Use OAuth. It is the only method the ChatGPT connector dialog offers, and it keeps tokens out
  of configuration entirely.
- Do not paste an Apify token into the chat, even "just to test". Chat content persists and may
  be reviewed, logged, or surfaced in shared links.
- Do not put a token in the MCP server URL as a query parameter — it ends up in URLs, logs, and
  screenshots.
- Treat transcript text as potentially personal or business-sensitive and follow the privacy and
  customer-data policies that apply to your use case.
- Revoke the connection from Apify Console → Settings → Integrations when you are done.

## Limitations

- MCP support in ChatGPT is officially described as beta; tool selection can be slow and
  occasionally wrong.
- Connectors cannot be edited after creation; expect to recreate them.
- Long Runs can exceed the time a single tool call waits for. `call-actor` waits at most 45
  seconds with a default of 30 — a long transcript job will return before it finishes, and the
  Run ID is what you follow up with.
- Whether the agent reads the entire dataset or just the preview is a client behaviour you cannot
  fully control. Always ask for item counts when completeness matters.
- Profile mode (`usernames`) returns metadata only. If the answer contains a "transcript" after a
  Profile run, it is invented.

## Still unverified

- The exact ChatGPT UI path and feature availability for your account and region.
- Whether ChatGPT surfaces pagination controls for `get-dataset-items`, or silently truncates.
- Which tools the connector actually loads with the Actor-scoped URL in current builds.

## Related docs

- [Use Instagram Reels Transcript API with Apify MCP](use-with-apify-mcp.md)
- [Use with Claude](use-with-claude-mcp.md)
- [Use with Gemini CLI](use-with-gemini-cli-mcp.md)
- [Use with Cursor and VS Code](use-with-cursor-vscode-mcp.md)
- [Prompt recipes for Reels analysis](prompt-recipes-for-reels-analysis.md)
- [AI agent use cases](ai-agent-use-cases.md)
- Official: [Apify ChatGPT integration](https://docs.apify.com/integrations/chatgpt)
