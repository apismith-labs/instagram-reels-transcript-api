# Use Instagram Reels Transcript API with Apify MCP

## What this guide covers

This guide shows how to expose the Apify Actor
`apple_yang/instagram-transcripts-scraper` to MCP-compatible clients through the Apify MCP
server, call it from an AI client, retrieve the transcript data, and judge whether the result is
actually complete.

Use it when you want an agent to fetch a transcript and then summarize, classify, translate, or
repurpose it — with a clear line between "the agent says it worked" and "the data is really
there".

Primary Actor: [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)

## Verification status

| Part | How it was checked |
| --- | --- |
| Tool names, connection methods, query parameters, run limits | Read from the official Apify MCP documentation (<https://docs.apify.com/mcp>) and the per-client Apify integration pages on 2026-10-24 |
| Actor input/output semantics | Pinned build `0.0.50` contract, same basis as [input-output-fields.md](input-output-fields.md) — schema-level, not observed |
| Actually calling this Actor over MCP from any client | **Not performed.** This repository has no MCP client, no token, and no end-to-end MCP run has been verified |

Everything below is therefore documentation-level guidance. Tool availability, tool naming, and
client UI all depend on the client version, the server configuration, and your account — so treat
tool names as "what to look for", not as strings to hardcode.

## Prerequisites

- An Apify account
- An MCP-compatible client
- Either OAuth (recommended) or an Apify API token, depending on the connection method
- A public Instagram Reel/video/post URL
- Actor ID: `apple_yang/instagram-transcripts-scraper`

Read-only discovery tools (`search-actors`, `fetch-actor-details`, `search-apify-docs`,
`fetch-apify-docs`) work without a token. **Running Actors and reading datasets always require
authentication.**

## Connect to Apify MCP

Two transports are officially supported: the hosted Streamable HTTP server at
`https://mcp.apify.com`, or a local stdio server run with `npx`.

### Hosted server with OAuth (recommended)

```json
{
  "mcpServers": {
    "apify": {
      "url": "https://mcp.apify.com"
    }
  }
}
```

The first connection opens a browser so you can sign in to Apify and approve access. No token is
written into the config file. If your client uses a visual connector dialog instead of a JSON
file, paste `https://mcp.apify.com` as the remote server URL and let it detect OAuth — see the
per-client guides linked at the bottom.

### Hosted server with a Bearer token

```json
{
  "mcpServers": {
    "apify-instagram-transcript": {
      "url": "https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper",
      "headers": {
        "Authorization": "Bearer YOUR_APIFY_TOKEN"
      }
    }
  }
}
```

Use this only for local or server-side configuration, and never commit a file containing a real
token. Prefer an environment-variable reference where your client supports interpolation rather
than a literal value.

### Local stdio server

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

Requires Node.js 22 or newer for the current `@apify/actors-mcp-server` package. Use stdio only
when the client cannot reach a remote MCP server.
Note that the hosted server supports output-schema inference for Actor results while the local
stdio server does not, so the hosted path gives the agent better type information.

There is also an Apify CLI shortcut that writes the client config for you:

```bash
apify mcp install cursor
```

and a visual configurator at <https://mcp.apify.com/> that generates the URL and config for the
tools you pick.

### Default and Actor-scoped tool sets

The endpoint determines which tool families are available. The default endpoint
`https://mcp.apify.com` loads the general `actors` and `docs` categories, along with
`apify/rag-web-browser`, `apify/web-fetch`, and `report-problem`. This is where the generic
`search-actors`, `fetch-actor-details`, and `call-actor` tools are available.

An Actor-scoped URL narrows the configuration to an Actor-specific tool and the documented
automatically included helpers:

```text
https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper
```

- `https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper` requests the Actor-scoped
  tool set. Do not assume it also exposes generic discovery tools such as `search-actors` or
  `call-actor`.
- The exact generated Actor-specific tool name and the tools visible in a particular client are
  **UNVERIFIED** here. Inspect the client's current MCP tool list (`tools/list`, or its tools
  panel) and use only names it actually reports. Do not invent a name from the Actor ID.
- When `call-actor` or an Actor-specific tool is loaded, the server documentation says it also
  exposes `get-actor-run`, `get-dataset-items`, `get-key-value-store-record`, and
  `abort-actor-run`.
- For the general discovery/invocation flow below, connect to the default endpoint. The
  Actor-scoped flow is client-specific; use the tool schema shown by that client.

## Which tool does what

On the **default endpoint**, the general tool set separates *running* an Actor from *reading* its
results.

| What you want | Tool | Notes |
| --- | --- | --- |
| Find the Actor | `search-actors` | Works without authentication |
| Read the input schema, output schema, README, pricing | `fetch-actor-details` | This is how the agent learns which fields to send |
| Start a Run | `call-actor` | Waits up to `waitSecs` (0–45, default 30). Returns **run status and storage IDs, not the results** |
| Get the Run ID | the `call-actor` response | The run object carries its own ID; keep it |
| Check Run status | `get-actor-run`, or `get-actor-run-list` | The list variant is filterable by status, which is how you find a Run whose ID you lost |
| Inspect logs | `get-actor-run-log` | Useful when a Run ends `FAILED` with no useful Dataset |
| Read results | `get-dataset-items` | Takes the `datasetId` from the Run; supports `limit`, `offset`, and field filtering |
| Dataset metadata / inferred schema | `get-dataset`, `get-dataset-schema` | Schema is inferred from the items, so it only helps after data exists |
| Stop a Run | `abort-actor-run` | Available whenever `call-actor` is loaded |

Two names you may see in blog posts, older docs, or an older model's memory are **not** in the
current tool list:

- `add-actor` — no longer needed; naming an Actor in `tools=` or using `call-actor` covers it.
- `get-actor-output` — replaced by `get-dataset-items` with a `datasetId`.

For an Actor-scoped endpoint, do not use this generic table as a promise that all of these tools
are loaded. Ask the client to show its available tools first and use the schema it exposes. Do not
let an agent substitute a tool name it "remembers".

### Run limits belong in `callOptions`

On the default endpoint, `call-actor` accepts `actor`, `input`, `waitSecs`, and `callOptions`.
The current server schema includes `build`, `memory`, `timeout`, `maxItems`, and
`maxTotalChargeUsd` in `callOptions`; these are tool-call options, not Actor input fields. This
repository pins Build `0.0.50`, so the example requests that Build explicitly. If `build` is
omitted, the Actor's configured default may be used. The server schema documents support for this
option, but this repository has not verified end-to-end Build forwarding through a live MCP client
or a live call. A charge-cap request is also not an absolute final-bill guarantee.

```json
{
  "actor": "apple_yang/instagram-transcripts-scraper",
  "input": {
    "videoUrl": "https://www.instagram.com/reel/your_reel_id/"
  },
  "callOptions": {
    "build": "0.0.50",
    "maxItems": 1,
    "timeout": 300,
    "maxTotalChargeUsd": 0.10
  }
}
```

This is the documented **default-endpoint `call-actor`** argument shape. Do not assume the
Actor-scoped direct tool accepts the same options. Confirm the actual schema visible in your client
before any billable call, and get owner approval for the budget.

## Getting complete results

`call-actor` returns identifiers, not data. A transcript is only in hand once dataset items have
been read.

1. Call the Actor and keep the returned **Run ID** and **Dataset ID**.
2. Poll `get-actor-run` until the status is terminal.
3. Read `get-dataset-items` with that `datasetId`.
4. Send an explicit `limit` on each Dataset read, then page with `offset` until you have everything, or until
   the returned count is smaller than the requested limit.
5. Only then claim the result is complete.

Rules that prevent the expensive mistakes:

- **A Dataset preview is not the full output.** Chat clients often truncate tool output for
  display; that is a UI limit, not proof that the Dataset is short.
- **An empty first read is not proof of failure.** Dataset visibility right after `SUCCEEDED` has
  not been verified for this Actor; re-read before concluding `empty`.
- **Never create a second Run because the result looked incomplete.** Re-read the same
  `datasetId`, ask for a specific `offset`, or fetch the dataset through the API. A new Run is new
  billable work and may not even be the same data.
- There is no automatic paging loop in these instructions — paging is something your client has
  to actually perform.

## Actor input: three modes

The Actor has three entry points. Send one per Run.

| Mode | Entry field | Produces | Example in this repository |
| --- | --- | --- | --- |
| Single transcript | `videoUrl` | A transcript for one public video/post URL | Yes — cURL, Python, Node.js, Java, Go, Rust |
| Native bulk transcript | `bulkUrls` | Transcripts for several URLs inside one Run | Yes — Python, Node.js, Go, Java, and Rust SDK examples |
| Profile posts | `usernames` | Post metadata for public accounts | Yes — Python, Node.js, Go, Java, and Rust SDK examples |

These are repository SDK/example capabilities. They do not establish that a particular MCP client
exposes or has live-verified these modes; MCP tool availability and end-to-end behavior remain
client-specific and unverified here.

Boundaries that matter when prompting an agent:

- **Profile mode does not generate transcripts.** It returns post metadata (captions, media URLs,
  engagement fields). A transcript needs a second, separate Run with `videoUrl` or `bulkUrls`.
  An agent that answers "here is the transcript" from `usernames` output is fabricating.
- `videoUrl` is required **only in single mode**. It is not a global required field.
- The pinned Actor schema does not enforce "one mode only". SDK examples validate their own
  mode-specific inputs; direct callers should send one mode at a time.
- `sessionid` appears in the Actor README but is absent from the pinned machine schema. Its
  runtime effect is unknown; leave it out unless you have a specific reason, and never put a real
  value in a chat message or a committed file.
- The `videoUrl` in the **output** is a media/CDN link, not the page URL. Feeding it back as
  input is not a valid re-run.

Single-mode input:

```json
{
  "videoUrl": "https://www.instagram.com/reel/your_reel_id/"
}
```

## Example prompts

These are **agent instructions**, not logs of successful runs. No MCP connection to this Actor
was made while writing them, and an agent may pick different tools or need a second prompt.

Single video:

```text
Use Apify MCP to run the Actor apple_yang/instagram-transcripts-scraper with this public
Instagram Reel URL:
https://www.instagram.com/reel/your_reel_id/

Send it as the videoUrl input. Keep the Run ID and Dataset ID you get back.
When the Run finishes, read the dataset items and report:
- whether any item has a non-empty errMsg (if so, quote it and stop)
- the transcript text
- the number of segments
- the creator username
If the dataset looks truncated, page through it with offset instead of starting another Run.
```

Several URLs in one Run (native bulk — no example code in this repository yet):

```text
Use Apify MCP with the Actor apple_yang/instagram-transcripts-scraper, bulkUrls mode.
Submit these URLs in one Run:
- https://www.instagram.com/reel/example_one/
- https://www.instagram.com/reel/example_two/

Use `maxItems` as a result-count limit. Only provide `maxTotalChargeUsd` if a project owner has
approved a numeric budget and the live tool schema exposes the option; do not treat it as a
verified hard billing ceiling.
After it finishes, read every dataset item and tell me explicitly which submitted URL each
transcript belongs to. If the mapping is unclear, say so — do not guess.
```

Profile posts (metadata only):

```text
Use Apify MCP to run apple_yang/instagram-transcripts-scraper in usernames mode for
example_account, with resultsLimit set explicitly.

Report only post metadata: caption, post type, media URL, engagement counts, timestamp.
Do not describe any of it as a transcript — this mode does not transcribe.
Then tell me which of those post URLs I would need to submit separately as videoUrl to get
transcripts, and that doing so is a separate billable Run.
```

## Output fields to expect

Transcript modes: `text`, `segments`, `title`, `userName`, `likeCount`, `commentCount`,
`videoUrl`, `audioUrl`, `errMsg`, `url`. Profile mode: `caption`, `ownerUsername`, `type`,
`commentsCount`, `videoPlayCount`, `videoDuration`, `hashtags`, `mentions`.

`errMsg` is the business verdict. A tool call that returned successfully, a Run that ended
`SUCCEEDED`, and an item with a populated `errMsg` can all be true at once — the item still
failed. Field-by-field caveats (units, absent fields, key names that must not be guessed) are in
[input-output-fields.md](input-output-fields.md).

## Cost

- Every Actor Run consumes Apify usage; the Actor has more than one billing event, so the unit
  price on the Store page is not the total price of one video.
- An agent retrying "because the output looked empty" can add another billable Run. Re-read the
  existing dataset instead of re-running. `maxItems` and `maxTotalChargeUsd` may be requested in
  `callOptions`, but their enforcement for this Actor has not been verified.
- Bulk and Profile inputs may lead to different or greater usage depending on item counts and
  Actor billing events; comparative cost has not been verified.
- Whether failed or timed-out Runs are billed has not been verified — do not assume a failure is
  free.

Pricing: <https://apify.com/apple_yang/instagram-transcripts-scraper/pricing>

## Credentials

- Use OAuth where the client supports it; it keeps the token out of config files entirely.
- Do not paste an API token into a normal chat prompt. A token in a prompt becomes part of the
  conversation history, may be logged, and may be echoed back.
- Do not commit MCP config files that contain tokens; prefer environment-variable interpolation.
- Treat transcript text as potentially personal or business-sensitive. Process and retain it only
  under the privacy, consent, and customer-data policies that apply to your use case.
- Do not enable MCP task or schedule tools unless you intentionally need recurring operations;
  scheduled Actor calls can create recurring billable work.
- A client that asks you to paste a token because "it cannot connect otherwise" is a version or
  configuration problem, not a reason to hand over a credential.
- Revoke access from Apify Console → Settings → Integrations if a connection is no longer needed.

## Troubleshooting

### The Actor tool does not appear

- Check that the server URL includes the Actor, for example
  `https://mcp.apify.com?tools=apple_yang/instagram-transcripts-scraper`.
- Some clients only expose the generic `actors` tools; then use `search-actors` →
  `fetch-actor-details` → `call-actor`.
- Reconnect the server. In clients that cannot edit a connector after creation (ChatGPT), create
  a new connector with the correct URL.

### A tool name is not recognised

- Ask the client to list its available tools. Map the step to whatever is present.
- If `get-actor-output` or `add-actor` is suggested, that is stale information — use
  `get-dataset-items` with the Dataset ID instead.

### I got a Run but no transcript

- Read `get-actor-run` first: `FAILED`, `TIMED-OUT`, `ABORTED` are Run-level failures.
- Then read `get-dataset-items`: an empty dataset and an item with `errMsg` are different
  outcomes and need different handling.
- Re-read the dataset once before concluding it is empty.

### Output looks cut off

- It usually is a client-side display limit. Ask for `get-dataset-items` with an explicit
  `limit` and `offset`.
- Do not start another Run to "get the rest".

### Authentication error

- OAuth flow not completed, or a token that is missing, expired, or lacks access.
- Re-authorise, or fix the token in secure local/server config. Never paste it into the chat.

### 429 or rate limits

- Reduce concurrency, back off, and check Apify usage.
- The Actor's real rate-limit semantics are unverified; treat retries as potentially billable.

## Still unverified

- Whether any of these tool names behave identically across client versions; only the official
  tool list was checked, not a live connection.
- Whether an agent reliably chooses `get-dataset-items` over a preview when both are available.
- Dataset visibility timing after `SUCCEEDED`, and whether `errMsg` and `text` can coexist.
- One-result-per-URL mapping, ordering, and partial-failure shape in native bulk mode.
- Profile `timestamp` semantics, `type` enumeration, and the share-count output key.
- Whether `maxTotalChargeUsd` is honoured per Run as expected for this Actor.

## Related docs

- [Use with ChatGPT](use-with-chatgpt-mcp.md)
- [Use with Claude](use-with-claude-mcp.md)
- [Use with Gemini CLI](use-with-gemini-cli-mcp.md)
- [Use with Cursor and VS Code](use-with-cursor-vscode-mcp.md)
- [Input and output fields](input-output-fields.md)
- [Error handling and retries](error-handling-and-retries.md)
- [Prompt recipes for Reels analysis](prompt-recipes-for-reels-analysis.md)
- [AI agent use cases](ai-agent-use-cases.md)
- Official: [Apify MCP server documentation](https://docs.apify.com/mcp)
