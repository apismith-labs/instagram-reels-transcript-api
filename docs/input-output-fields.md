# Input and output fields

This document describes the input and output fields of the Apify Actor
`apple_yang/instagram-transcripts-scraper`.

Actor page: <https://apify.com/apple_yang/instagram-transcripts-scraper>

**Evidence basis.** Field and type information comes from the pinned Actor build `0.0.50`
(build ID `aJLRmMdQapLQRT4sJ`) as recorded in
[actor_audit_20261020.md](audit/actor_audit_20261020.md) and normalised into
[contracts/instagram-transcripts-scraper-0.0.50.json](audit/contracts/instagram-transcripts-scraper-0.0.50.json).
That contract is **derived from an audit**, not a verbatim copy of the upstream schema, and no
field list here has been confirmed by a real Actor run. Anything marked *unverified* below must
be checked with your own controlled run before you depend on it. If the Actor's build changes,
re-compare; do not assume compatibility.

## Three input modes

The Actor has three entry points. Choose **one** per Run and leave the other entry fields out.

| Mode | Entry field | Purpose | Produces transcripts? |
| --- | --- | --- | --- |
| Single transcript | `videoUrl` | Transcribe one public video/post URL | Yes |
| Native bulk transcript | `bulkUrls` | Transcribe several URLs inside one Run | Yes (mode exists), but one result per URL is **not guaranteed** — mapping unverified |
| Profile posts | `usernames` | Collect metadata for posts of one or more public accounts | **No** |

Mode boundaries:

- Do not mix entry fields. Sending `videoUrl` together with `usernames` is undefined behaviour;
  the Actor's schema does not declare which one wins.
- `videoUrl` is required **only in single mode**. It is not a global required field.
- The pinned schema declares `required: []`. Nothing server-side enforces "at least one entry
  field", "exactly one entry field", or "do not mix" — the schema has no `oneOf`/`anyOf`, so a
  request carrying several entry fields is not rejected on schema grounds. What the Actor does
  with such a request is **unverified**.
- **This repository does not implement the three-way choice.** Every example here sends only
  `videoUrl`. None of them validates, rejects, or selects between the three modes; there is no
  client-side mode switch to inherit. "Pick one mode" is guidance for hand-written requests, not
  a behaviour you get from the current code. Native bulk (`bulkUrls`) and Profile (`usernames`)
  examples are not developed yet — they are V2.1 `B01` and `P01`.
- Profile mode collects post metadata. Producing transcripts for those posts requires a separate
  Run using `videoUrl` or `bulkUrls` — the Actor does not chain the two for you.

### What this repository currently implements

| Mode | Example code available here |
| --- | --- |
| Single transcript | Yes — cURL, Python, Node.js, Java, Go, Rust |
| Native bulk transcript | Yes — Python, Node.js, Go, Java |
| Profile posts | Yes — Python, Node.js, Go, Java |

The table above summarizes the currently implemented examples. Java completed controlled Live checks for Single URL, three-URL Native Bulk, one-row CSV, and GET-only Single Resume; its three-account Profile check was PARTIAL (19 success, one owner attribution unknown, one Actor error). See
[batch-processing-guide.md](batch-processing-guide.md) for how the existing CSV examples differ
from native bulk.

## Input fields

### Single mode

```json
{
  "videoUrl": "https://www.instagram.com/reel/your_reel_id/"
}
```

| Field | Type | Required by client | Notes |
| --- | --- | --- | --- |
| `videoUrl` | string | Yes (single mode only) | Public Reel/video/post page URL. The schema sets a prefill example, not a default; omitting the field entirely is unverified. |

### Native bulk mode

```json
{
  "bulkUrls": [
    "https://www.instagram.com/reel/example_one/",
    "https://www.instagram.com/reel/example_two/"
  ]
}
```

| Field | Type | Required by client | Notes |
| --- | --- | --- | --- |
| `bulkUrls` | array of strings | Yes (bulk mode only) | The schema prefill is an empty array. Element validation and `maxItems` are not declared in the pinned schema; the free-plan URL cap is an Actor/plan limit that can change. Result ordering, partial-failure shape, and the input-to-output mapping are **unverified**. |

### Profile mode

```json
{
  "usernames": ["example_account"],
  "resultsLimit": 12,
  "onlyPostsNewerThan": "2 weeks",
  "skipPinnedPosts": false,
  "includeSharesCount": false
}
```

| Field | Type | Notes |
| --- | --- | --- |
| `usernames` | array of strings | Public account names. The schema prefill contains an example account; that is a form prefill, **not** a default — do not treat it as "collects this account if omitted". |
| `resultsLimit` | integer | Prefill `12`; the schema declares no minimum or maximum. Whether it limits per account or per Run across several accounts is **unverified**. Set it explicitly. |
| `onlyPostsNewerThan` | string | Documented as UTC with day/week/month/year relative forms. Documentation also mentions full ISO timestamps, but the pinned schema's pattern rejects full ISO (`2026-07-01T10:30:00Z` → no match). Use a date (`YYYY-MM-DD`) or a relative value (`2 weeks`); full-ISO runtime behaviour is **unverified**. |
| `skipPinnedPosts` | boolean | Prefill `false`. Use it to exclude pinned posts from a recent-posts window. |
| `includeSharesCount` | boolean | Prefill `false`; documented as available on paid plans. The **output key name for share counts is unknown**, so do not parse it as `sharesCount`. |

### Common / uncertain fields

| Field | Type | Notes |
| --- | --- | --- |
| `sessionid` | string per the Actor README | **Absent from the pinned input schema.** Its runtime effect is unknown: do not describe it as deprecated, and do not assume it is ignored. The examples here send an empty string. Never commit or log a real value. |

Additional notes:

- The pinned schema defines **no** `oneOf`/`anyOf` and **no** `required` entries, so neither "at
  least one entry field" nor "no mixing" is enforced server-side.
- `prefill` is form pre-filling, not a runtime default. Behaviour when a field is omitted is
  **unverified** for every optional field.

## Java request and result mapping

The Java client pins Build Number `0.0.50` and verifies Build ID `aJLRmMdQapLQRT4sJ`. It sends `build`, `restartOnError=false`, and the optional `maxTotalChargeUsd` in Run query parameters, not in Actor input. Single input uses `videoUrl` and adds `sessionid` only when explicitly configured. Native Bulk uses `bulkUrls`; Profile uses `usernames` with only the supplied optional filters. Java CSV accepts a `url` or `videoUrl` column and creates one separate Run per row only after `--execute`.

Java retains each Dataset item as a Jackson `JsonNode`; the application result adds normalized status, transcript `text` and `segments` where applicable, while preserving the original `rawItems` and their JSON scalar types. Profile uses `ownerUsername` for attribution and does not require transcript fields. Java reads one Dataset page and reports it incomplete when the configured page limit is reached.

## Output

Output is a Dataset. The Actor's declared output is a single `results` string that links to the
Dataset items URL — it is **not** an inline array of records. The record fields below come from
the pinned build's Dataset field definitions.

Field presence varies by mode. Several fields are marked `required` in the Dataset definition
even though Profile results do not always carry them; do not validate incoming items against that
requirement list.

### Transcript modes (`videoUrl`, `bulkUrls`)

| Field | Type | Notes |
| --- | --- | --- |
| `url` | string | Canonical post URL, which may differ from the URL you submitted. |
| `code` | string | Shortcode, when available. |
| `pk` | string | Keep as a string; it is a large integer and loses precision as a number. |
| `id` | string | Media identifier. |
| `title` | string | Title/caption-derived text. Do not treat it as the transcript. |
| `img` | string | Thumbnail URL, when available; may be temporary. |
| `videoUrl` | string | **Media/CDN link.** Not a page URL — do not feed it back as `videoUrl` input. |
| `audioUrl` | string | Media link; documented as optional in the README while the schema marks it required. Handle absence. |
| `duration` | number | Not listed in the README field table; unit believed to be seconds, **unverified**. |
| `createTime` | integer | Unit **unverified** (a 10-digit value suggests seconds). Keep the raw value. |
| `likeCount` | integer | Missing ≠ `0`; do not fill in a real-looking zero. |
| `commentCount` | integer | Note this is not the same key as Profile's `commentsCount`. |
| `userPk` | string | Keep as a string. |
| `userName` | string | Author username. |
| `userFullName` | string | May be absent. |
| `avatarUri` | string | May be absent; temporary link. |
| `text` | string | The transcript. This is the field your application consumes. |
| `segments` | array of objects | Believed to contain `start` (number), `end` (number), `text` (string), in seconds with `start ≤ end`. Element types are **unverified**. |
| `errMsg` | string | Business error for this item. Non-empty `errMsg` means the item failed regardless of HTTP or Run status. |
| `timestamp` | string | Semantics differ between transcript and Profile output; do not parse with a single assumption. |

### Profile mode (`usernames`)

Registered accounts produce records with post metadata. Profile records generally **do not**
contain `text`, and must not be classified as transcript failures because of that.

| Field | Type | Notes |
| --- | --- | --- |
| `caption` | string | Post caption. Distinct from `title`. |
| `ownerUsername` | string | Account owner. Distinct from `userName`; do not silently overwrite one with the other. |
| `type` | string | Post type. The enumeration has not been published or sampled, so unknown values must be preserved, not dropped. |
| `commentsCount` | integer | Distinct key from transcript's `commentCount`. |
| `videoPlayCount` | integer | Interaction metric; not present on every post. |
| `videoDuration` | number | Not guaranteed to equal the transcript `duration`. |
| `hashtags` | array of strings | Missing and empty array are different states. |
| `mentions` | array of strings | Same as above. |
| Share count | — | Enabled by `includeSharesCount`; **output key name unknown**. Do not guess it. |

Profile items may also carry `url`, `id`, `pk`, `img`, `videoUrl`, `likeCount`, `timestamp`, and
other transcript-mode fields. Their presence per post type is **unverified**.

## Parsing rules

Apply these in order — they match the Python and Node.js examples:

1. **Empty Dataset** → `empty`. No items means no transcript.
2. **Non-empty `errMsg` on any item** → `actor_error`. Do not count it as a success even when
   `text` is also present.
3. **At least one non-empty string `text`** → `success`.
4. **No usable text** (`text` null, missing, empty, or a non-string such as `0`) →
   `no_transcript` for null/missing/empty, `unknown` for an unsupported type.

Additional guidance:

- Preserve unknown extra fields rather than failing the whole item; the Actor may add fields.
- Keep the raw item next to any normalised record you build, so later contract changes are
  auditable.
- Never treat "the script exited 0" as proof of a transcript — see
  [error-handling-and-retries.md](error-handling-and-retries.md).

## Still unverified

Confirmed against nothing but documentation and static schema so far:

- Real response envelopes, Dataset visibility timing, and item counts per mode.
- Whether `errMsg` and `text` ever coexist, and which one the Actor intends as authoritative.
- Profile `timestamp` type/unit, `type` enumeration, share-count key, and `resultsLimit` scope for
  multiple accounts.
- Bulk ordering, partial failure, and input-to-output mapping.
- Billing events, per-video event counts, and whether failures are charged.
