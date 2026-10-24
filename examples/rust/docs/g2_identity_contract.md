# G2 Native Bulk Identity, Attribution, and Result Contract

This document freezes the design target for future Rust Native Bulk implementation. It does not claim that Native Bulk, Profile, CSV, or Resume is implemented. G1 Single behavior remains unchanged.

## Scope and identity

Validate every input with the existing G1 URL validator before planning a Run. Accepted HTTPS hosts are exactly `instagram.com` and `www.instagram.com`; paths are `/reel/{shortcode}`, `/reels/{shortcode}`, and `/p/{shortcode}`. Query strings, fragments, userinfo, explicit ports, whitespace, unsupported hosts, and other paths are invalid. Any invalid input rejects the complete request before a create POST.

The G2 identity key is `(MediaType, shortcode)`. `/reel/X` and `/reels/X` are aliases for `(reel, X)`; `/p/X` is `(post, X)`. Shortcodes are case-sensitive. A Post and Reel with the same shortcode remain separate identities. Host spelling and one optional trailing slash do not change identity. Query and fragment normalization is unnecessary because those forms are rejected.

The normalized URL identity is the validated URL with host normalized to `instagram.com`, one optional trailing slash removed, and path kind and shortcode preserved exactly. Reel aliases share typed media identity while retaining their respective source URL strings. G1 `canonical_video_identity(url) -> Option<String>` returns only shortcode text and is used by accepted G1 Single attribution. G2 must not use that shortcode-only identity for typed deduplication or attribution. Any G1 Single change requires separate review and regression tests.

## Input planning and source mapping

Before a create POST, preserve each original input occurrence as `source index -> original URL -> typed identity -> unique task`. Validate every input first, then automatically deduplicate by `(MediaType, shortcode)`. A duplicate does not reject the batch. First occurrence determines task order. Every unique identity has exactly one `results[]` row. Each task's `sourceIndexes[]` and `sourceUrls[]` are zero-based, aligned, equal-length arrays in original occurrence order; they retain every input occurrence, including duplicate strings. Attribution compares against every normalized URL in the task's complete `sourceUrls[]`; the first source is not privileged.

## Dataset evidence precedence and affected tasks

Evaluate each physical Dataset item once. Evidence precedence and conflict handling are:

1. Validate an item's URL using the same URL contract. A malformed non-empty URL is `invalid_item` and blocks fallback.
2. Normalize a valid URL and compare it exactly against all source URLs of all tasks. One match is an `exact_url` candidate.
3. Compare the validated URL's own typed identity with every other reliable identity field present on the item, including shortcode and media type, whether or not the URL matched an input task. If URL, shortcode, or type disagree, classify the item as `conflicting_evidence`; URL success does not override the contradiction, and an unmatched URL cannot be used to fall back to a contradictory shortcode.
4. The affected task set for a contradiction is the union of: the URL-matched task, if any; and every task selected by the item's reliable `(mediaType, shortcode)` pair, if present. When a shortcode is present without a reliable media type, all tasks with that shortcode are affected. Never infer a type from the candidate task. Each affected task becomes `unknown`; the one physical item is stored once in `extraItems[]`, with its `affectedTaskIndexes[]`.
5. If there is no valid URL evidence, typed fallback is permitted only when the item itself carries a reliable supported media type and shortcode and that pair selects exactly one task. The expected type cannot be inferred from the tasks or from the fact that only one shortcode candidate exists. If reliable typed identity exists but selects zero tasks, classify the item as `unmatched`, set attribution to `none`, set `affectedTaskIndexes=[]`, leave every task unchanged, and preserve a sanitized diagnostic. Do not discard the media type and retry shortcode-only matching.
6. A valid URL or reliable typed identity that matches no task is `unmatched` and blocks fallback to weaker or contradictory evidence, even if a shortcode alone matches an input. A shortcode-only item without reliable media type is `ambiguous` and cannot succeed even if there is only one input task. Its affected set is all input tasks sharing that shortcode (possibly empty).
7. Invalid or structurally unusable items are `invalid_item` when serializable. They are retained once as extras and never silently discarded.

No item is assigned by Dataset order or array position. One item cannot satisfy multiple tasks. A task may be `success` only when exactly one physical item uniquely attributes to it and its item contract confirms usable transcript data. A single item cannot yield a success if any of its identity evidence conflicts.

### Repeated items for one task

If two or more physical items independently point to the same task, do not select a primary winner. Mark that task `unknown`, put **all** those physical items in `extraItems[]` with reason `duplicate` and the task index in `affectedTaskIndexes[]`, and leave that task's `results[].rawItems[]` empty. If a task becomes `unknown` because of another ambiguous, conflicting, or incomplete item, move every previously attributable item for that task out of its pending `rawItems[]` and into `extraItems[]` with reason `task_unresolved`; keep the causative item under its own reason (such as `ambiguous` or `conflicting_evidence`). This preserves every diagnostic item without copying one item into both arrays or claiming an arbitrary item as success. Other uniquely attributed tasks may retain their own item in `results[].rawItems[]`.

`counts.extraItems` is exactly `extraItems.length`, counting physical Dataset item occurrences, not affected-task references. Each physical Dataset item occurs exactly once across all `results[].rawItems[]` and `extraItems[].rawItem`; an item is never counted in both. Invalid values that cannot be represented as JSON cannot occur in a parsed JSON Dataset; for every parsed item, preserve the sanitized JSON value.

## Formal vocabularies

These vocabularies are scoped to their fields. Identical literals such as `success`, `empty`, `unknown`, and `error` may appear in both Task Status and Batch Status; consumers must interpret them with the field name, not require global string uniqueness.

| Field | Legal serialized values | Meaning |
| --- | --- | --- |
| `results[].status` (Task Status) | `success`, `empty`, `unknown`, `error` | Per unique typed identity. |
| `results[].attribution` | `exact_url`, `typed_fallback`, `none`, `conflicting_evidence` | Evidence used for that task. `none` means no usable evidence; a confirmed empty task uses `none`. Contradictory evidence uses `conflicting_evidence`. |
| `extraItems[].reason` (Extra Reason) | `unmatched`, `ambiguous`, `duplicate`, `invalid_item`, `conflicting_evidence`, `task_unresolved` | Why one physical Dataset item was not uniquely consumed by a task. |
| Batch `status` | `success`, `partial_success`, `empty`, `unknown`, `error`, `input_error`, `creation_unknown`, `output_error` | Overall operation result. |

### Machine-readable error codes and human diagnostics

`errorCode` is a stable machine-readable enum; `error` is a separate, human-readable diagnostic that must pass the established redaction and length-normalization policy. Never put an error code in the `error` text field.

| Scope | `errorCode` values | Rules |
|---|---|---|
| `results[]` task row | `no_transcript`, `actor_error`, `transport_error`, `run_failed`, `unknown`, `build_mismatch`; otherwise `null` | Required non-null for `status=error` or `status=unknown`. `status=success` and `status=empty` use `null` and `error=null`. `unknown` covers unresolved attribution, incomplete evidence, or other non-classifiable task state. `no_transcript` means a unique item exists without usable transcript; `actor_error` preserves a sanitized Actor `errMsg`; `transport_error`, `run_failed`, and `build_mismatch` are task errors only when the implementation emits explicit task rows for the failed Run. |
| Batch operation summary | `input_error`, `create_rejected`, `creation_unknown`, `output_error`, `journal_error`, `transport_error`, `run_failed`, `build_mismatch`, `dataset_error`, `attribution_error`; otherwise `null` | `create_rejected`, `creation_unknown`, `input_error`, `output_error`, and `journal_error` are batch-only and do not become per-task codes when no task outcomes are emitted. `create_rejected` and `creation_unknown` are mutually exclusive. |

`creation_unknown` is batch-only: do not create task rows or assert that a Run exists when the create outcome is uncertain. A `create_rejected` response is also represented as a minimal batch operation error, with `status=error` and `errorCode=create_rejected`; it is distinct from a normal aggregate where all task rows are errors and `errorCode=null`. For task-level `unknown`, set `errorCode=unknown`. For confirmed empty and success rows, omit machine errors (`errorCode=null`, `error=null`).

`typed_fallback` is only valid when the Dataset item has reliable type and shortcode evidence and exactly one task matches. Successful result rows require `exact_url` or `typed_fallback`. `conflicting_evidence` rows are always `unknown`; `none` rows may be `empty`, `unknown`, or `error` depending on the evidence and execution result.

## G1 status to G2 mapping (D5)

The source enum in `src/status.rs` has exactly eight values. G1's process exit codes come from `src/error.rs`; `Status` itself is a result classification, while operational failures can return an `Error` instead of a `TranscriptResult`. The mapping below preserves the distinctions and does not add a G2 Task Status value.

| G1 `Status` | G2 Task Status | G2 `errorCode` scope | Batch handling | Recommended exit | Partial result allowed? |
| --- | --- | --- | --- | ---: | --- |
| `success` | `success` | none | Counts as verified transcript result; batch may be `success` only under the aggregate rules below. | 0 if batch `success`, otherwise 2 | Yes, verified task row only. |
| `empty` | `empty` | none | Confirmed complete Dataset with no item for this task; distinct from missing transcript. | 0 if batch `empty` or `success`, otherwise 2 | Yes. |
| `no_transcript` | `error` | `no_transcript` | A uniquely attributed Actor item exists but has no usable transcript. Never fold into `empty` or all-success. | 1 if all tasks are errors; otherwise 2 for partial/unknown aggregate | Yes, as an explicit error row. |
| `actor_error` | `error` | `actor_error` | Preserve sanitized Actor diagnostic. Never fold into success or empty. | 1 if all tasks are errors; otherwise 2 for partial/unknown aggregate | Yes, as an explicit error row. |
| `unknown` | `unknown` | `unknown` | Preserve diagnostic/evidence. If no task is confirmed success/empty, batch is `unknown`; otherwise `partial_success`. | 2 | Yes. |
| `transport_error` | `error` | `transport_error` | Explicit transport failure; no transcript success is inferred. | 1 if all tasks are errors; otherwise 2 for partial/unknown aggregate | Yes, as an explicit error row. |
| `run_failed` | `error` | `run_failed` | Actor Run failure remains an error, not an empty result. | 1 if all tasks are errors; otherwise 2 for partial/unknown aggregate | Yes, as an explicit error row. |
| `creation_unknown` | none (no task row) | Batch-only `creation_unknown` | Batch-level `creation_unknown`; no task is reported successful from an uncertain create. Never retry the create POST. | 10 (matches G1 `ErrorKind::CreationUnknown`) | Only the minimal batch error summary; no task data. |

The `no_transcript` mapping is deliberately `error/no_transcript`: an item was found, but usable transcript extraction failed. `empty` means a complete Dataset confirms no item for that task. `actor_error` means the Actor returned an explicit item-level error. These are three different outcomes. The recommended G2 exits are normalized by G2 Batch Status (`error` is always 1); G1's existing `ErrorKind` exits remain unchanged in G1 and are not copied as ambiguous per-task exits into the new Batch contract.

G1 operational errors map as follows: invalid input/configuration -> batch `input_error` / exit 2; explicit create rejection -> batch `status=error`, `errorCode=create_rejected`, exit 4; uncertain create -> batch `creation_unknown` / exit 10; Build mismatch -> explicit task errors with `errorCode=build_mismatch` when a task result exists; Run failure -> task `error/run_failed`; transport -> task `error/transport_error` when task rows exist; Dataset or attribution failure -> `unknown` or `error` according to whether evidence is uncertain or a confirmed read/contract failure; Journal/output failure -> minimal batch operation error / exit 2. A normal task aggregate with `status=error` and `errorCode=null` exits 1. The machine code disambiguates the create-rejection exception; no optional exit-code wording is permitted. Do not retry POST for any rejection or unknown create outcome.

## Counts and mutually exclusive Batch Status (D1/D2)

`counts.success`, `counts.empty`, `counts.unknown`, and `counts.error` are derived from final `results[].status`; their sum equals `results.length`, which equals the number of unique input identities. `counts.extraItems` equals `extraItems.length` as defined above. Duplicate input URLs do not increase task counts; duplicate Dataset items do increase `extraItems` once per physical item.

First classify operational outcomes before aggregating task rows. Exactly one applies: invalid preflight -> `input_error`; explicit create rejection -> `error` with batch `errorCode=create_rejected`; uncertain create response -> `creation_unknown`; failure to persist the output -> `output_error`. These outcomes are terminal and do not fall through to normal task aggregation. The `create_rejected` operation summary uses G1 exit 4; normal aggregate `error` uses exit 1. For an `output_error`, emit only the minimal error summary: `results=[]`, `extraItems=[]`, all five counts are zero, and preserve known `runId` and `datasetId`. Do not serialize the otherwise computed in-memory Bulk results or claim a result file exists.

Before normal aggregation, `empty` is allowed only for a complete Dataset. On an incomplete Dataset, every task without a uniquely attributed usable item is `unknown`; uniquely attributed usable items may remain `success`, but the batch can never be all-success. For `N > 0` tasks, use the following mutually exclusive Boolean definitions (not row-order precedence):

1. `success`: Dataset complete, no extras, `unknown=0`, `error=0`, and `success + empty = N` with `success > 0. Exit 0. This permits a confirmed mixture of transcript success and confirmed empty tasks.
2. `empty`: Dataset complete, no extras, `success=0`, `unknown=0`, `error=0`, and `empty=N`. Exit 0.
3. `error`: `success=0`, `empty=0`, `unknown=0`, and `error=N` for a normal task aggregate. Extras remain visible but do not turn a batch of exclusively confirmed task errors into success. Exit 1. A pre-task explicit create rejection is the distinct minimal operation summary `status=error`, `errorCode=create_rejected`, `results=[]`, zero counts, and exit 4; it does not enter this aggregate predicate.
4. `unknown`: `success=0`, `empty=0`, and `unknown>0`, with any remaining errors or extras. Exit 2. Thus all-unknown plus extras has exactly this result.
5. `partial_success`: `success + empty > 0` and any of: `unknown>0`, `error>0`, extras exist, or `datasetComplete=false`. Exit 2. Only uniquely attributed success/empty rows are represented as such; all uncertain rows remain explicit.

The five predicates are disjoint and cover all normal aggregates for `N > 0`. Empty input is `input_error`. An incomplete Dataset cannot produce batch `success` or `empty`; every task without a unique verified item is `unknown`. A normal `BatchResult`'s counts are derived from its emitted rows. Process-level summaries (`input_error`, create-rejected `error`, `creation_unknown`, `output_error`) have `results=[]`, `extraItems=[]`, counts `(0,0,0,0,0)`, and a separate `plannedTaskCount`; they do not claim task outcomes.

| Batch status | Exit code | Output/meaning |
| --- | ---: | --- |
| `success` | 0 | Complete, verified task results; may include confirmed empty rows. |
| `partial_success` | 2 | Some verified success/empty rows plus uncertainty, error, extras, or incomplete Dataset. |
| `empty` | 0 | Every task is confirmed empty on a complete Dataset. |
| `unknown` | 2 | No confirmed success/empty task and at least one unknown task. |
| `error` | 1 for normal task aggregate; 4 when `errorCode=create_rejected` | All task rows are confirmed errors, or an explicit create rejection is represented by the minimal batch error summary. |
| `input_error` | 2 | Invalid preflight; zero create POSTs. |
| `creation_unknown` | 10 | Create outcome uncertain; never retry POST. |
| `output_error` | 2 | Result persistence failed; minimal error summary has empty results/extras, zero counts, and retains known Run/Dataset IDs. |

## Result shape

This is a design target, not a current API. `mediaType` serializes as lowercase `reel` or `post`. The example shows a safe partial outcome:

```json
{
  "status": "partial_success",
  "errorCode": null,
  "error": null,
  "runStatus": "SUCCEEDED",
  "datasetComplete": true,
  "counts": {"success": 1, "empty": 0, "unknown": 1, "error": 0, "extraItems": 1},
  "results": [
    {
      "identity": {"mediaType": "reel", "shortcode": "ABC123"},
      "sourceIndexes": [0, 1],
      "sourceUrls": ["https://instagram.com/reel/ABC123", "https://instagram.com/reels/ABC123"],
      "status": "success",
      "errorCode": null,
      "attribution": "exact_url",
      "rawItems": [{"shortCode": "ABC123", "url": "https://instagram.com/reels/ABC123"}],
      "error": null
    },
    {
      "identity": {"mediaType": "post", "shortcode": "ABC123"},
      "sourceIndexes": [2],
      "sourceUrls": ["https://instagram.com/p/ABC123"],
      "status": "unknown",
      "errorCode": "unknown",
      "attribution": "none",
      "rawItems": [],
      "error": "Dataset identity evidence is ambiguous."
    }
  ],
  "extraItems": [
    {
      "reason": "unmatched",
      "affectedTaskIndexes": [],
      "rawItem": {"shortCode": "ABC123", "url": "https://instagram.com/reel/OTHER9"},
      "diagnostic": "Valid item URL does not match an input task."
    }
  ]
}
```

An `output_error` or `create_rejected` process summary is not a partial Bulk result. Its exact minimal form is:

```json
{
  "status": "output_error",
  "errorCode": "output_error",
  "error": "Could not persist the result file.",
  "runId": "known-run-id-or-null",
  "datasetId": "known-dataset-id-or-null",
  "results": [],
  "extraItems": [],
  "counts": {"success": 0, "empty": 0, "unknown": 0, "error": 0, "extraItems": 0}
}
```

For a rejected create POST, use `status="error"`, `errorCode="create_rejected"`, the sanitized human diagnostic in `error`, no task or extra rows, zero counts, and exit 4. For `creation_unknown`, use `status="creation_unknown"`, `errorCode="creation_unknown"`, no task or extra rows, zero counts, preserve known identifiers if any, and exit 10. Neither operation summary is written as a successful result file.

For conflicts and duplicates, `affectedTaskIndexes[]` contains the zero-based position of each affected unique task in `results[]`; it is separate from original-input `sourceIndexes[]`. A conflicting item sets attribution `conflicting_evidence` on every affected row. An ambiguous shortcode-only item sets attribution `none`; its extra reason is `ambiguous`. Preserve all source mapping for success, empty, unknown, and error rows. Sanitize every saved item and diagnostic.

## Twelve deterministic contract fixtures

Notation: counts are `(success, empty, unknown, error, extraItems)`, and task indexes are positions in `results[]`. Every listed Dataset item occurs once, either in one result's `rawItems[]` or in `extraItems[].rawItem`, never both. `runStatus=SUCCEEDED`, complete Dataset, and no operational failure are assumed unless stated.

| # | Input and Dataset evidence | Unique task result(s): status / `errorCode` / attribution / rawItems | Extras: reason, affected tasks | Counts | Batch / exit |
|---:|---|---|---|---|---|
| 1 | Inputs `/reel/ABC`, `/reels/ABC`; same item URL `/reels/ABC`, shortcode `ABC`, usable transcript. | Reel ABC: `success` / `null` / `exact_url` / 1 item; `sourceIndexes=[0,1]`, both original `sourceUrls` | none | `(1,0,0,0,0)` | `success` / 0 |
| 2 | Inputs `/p/ABC`, `/reel/ABC`; one item only has shortcode `ABC`, no URL/type. | Post ABC: `unknown` / `unknown` / `none` / 0; Reel ABC: `unknown` / `unknown` / `none` / 0 | `ambiguous`, tasks `[0,1]` | `(0,0,2,0,1)` | `unknown` / 2 |
| 3 | One input Reel ABC; two separate usable items both uniquely match ABC. | Reel ABC: `unknown` / `unknown` / `exact_url` / 0 | Two `duplicate` extras, each tasks `[0]` | `(0,0,1,0,2)` | `unknown` / 2 |
| 4 | Inputs Reel A and Reel B; item URL identifies A, while its reliable shortcode/type identify B. | Reel A: `unknown` / `unknown` / `conflicting_evidence` / 0; Reel B: same | `conflicting_evidence`, tasks `[0,1]` | `(0,0,2,0,1)` | `unknown` / 2 |
| 5 | Input Reel ABC; one valid usable ABC item and one unrelated valid OTHER9 item. | Reel ABC: `success` / `null` / `exact_url` / 1 item | `unmatched`, tasks `[]` | `(1,0,0,0,1)` | `partial_success` / 2 |
| 6 | Inputs Reel ABC, Post DEF; ABC has one exact usable item; DEF has shortcode-only evidence without type. | Reel ABC: `success` / `null` / `exact_url` / 1; Post DEF: `unknown` / `unknown` / `none` / 0 | `ambiguous`, tasks `[1]` | `(1,0,1,0,1)` | `partial_success` / 2 |
| 7 | One Reel ABC task; complete Dataset returns no item for ABC. | Reel ABC: `empty` / `null` / `none` / 0 | none | `(0,1,0,0,0)` | `empty` / 0 |
| 8 | One Reel ABC task; one exact item has no usable transcript text. | Reel ABC: `error` / `no_transcript` / `exact_url` / 1 item | none | `(0,0,0,1,0)` | `error` / 1 |
| 9 | Two tasks; both receive explicit `errMsg` items. | Each: `error` / `actor_error` / `exact_url` / 1 item | none | `(0,0,0,2,0)` | `error` / 1 |
| 10 | Inputs Reel ABC and Post DEF; ABC has one exact usable item; complete Dataset has no item for DEF. | Reel ABC: `success` / `null` / `exact_url` / 1; Post DEF: `empty` / `null` / `none` / 0 | none | `(1,1,0,0,0)` | `success` / 0 |
| 11 | Input Reel ABC; item has no URL, reliable type `post`, shortcode `ABC` (zero typed matches). | Reel ABC: `empty` / `null` / `none` / 0 | `unmatched`, tasks `[]`; sanitized diagnostic retained | `(0,1,0,0,1)` | `partial_success` / 2 |
| 12 | One Reel ABC task; one exact usable item plus one shortcode-only ABC item without type. | Reel ABC: `unknown` / `unknown` / `exact_url` / 0; no Success | One `task_unresolved` extra for the exact item and one `ambiguous` extra for the shortcode-only item, both tasks `[0]` | `(0,0,1,0,2)` | `unknown` / 2 |

The duplicate fixture deliberately stores both physical duplicates only as extras, so no primary diagnostic item is silently selected. Fixture 4 treats a valid URL plus contradictory shortcode as conflicting evidence; both affected tasks become unknown. Fixture 11 proves reliable typed identity with zero candidates is unmatched, has no affected task, and cannot fall back to a same-shortcode task of another type. Fixture 12 proves that when a second ambiguous item downgrades a task, the previously exact item is moved to `task_unresolved`; neither physical item is lost or duplicated.

Additional aggregate cases, with exact counts, are:

| Case | Task rows | Attribution | Extras | Counts `(success,empty,unknown,error,extraItems)` | Batch / exit |
|---|---|---|---|---|---|
| All unknown plus one extra | 1 `unknown` task, no confirmed rows | `none` | 1 `ambiguous` extra | `(0,0,1,0,1)` | `unknown` / 2 |
| One success plus one no-transcript task | 1 `success`, 1 `error` (`no_transcript`) | `exact_url`, `exact_url` | none | `(1,0,0,1,0)` | `partial_success` / 2 |
| All tasks are no-transcript errors | 1 `error` (`no_transcript`) | `exact_url` | none | `(0,0,0,1,0)` | `error` / 1 |
| One create outcome is unknown | No task rows; creation status is not evidence of a Run | n/a | none | `(0,0,0,0,0)` | `creation_unknown` / 10 |
| One task's output persistence fails | No task rows are emitted in the returned operational summary; preserve known Run/Dataset IDs | n/a | none | `(0,0,0,0,0)` | `output_error` / 2 |

Operational boundary fixtures (not additional Dataset items):

| Case | Task result(s) | Attribution | Extra reasons / count | Counts `(success,empty,unknown,error,extraItems)` | Batch / exit | Persisted result |
|---|---|---|---|---|---|---|
| Create POST outcome unknown for one planned task | No task rows | n/a | none / 0 | `(0,0,0,0,0)` | `creation_unknown` / 10 | Minimal CLI/operational summary only; preserve known IDs if any; safe Journal diagnostic; no retry. |
| Output write fails after one otherwise successful task result | No task rows in the returned operational summary; preserve known Run/Dataset IDs | n/a | none / 0 | `(0,0,0,0,0)` | `output_error` / 2 | The result file does not exist; report only a sanitized operational error summary. |
| Invalid URL discovered during preflight | no planned task rows | n/a | none / 0 | `(0,0,0,0,0)` | `input_error` / 2 | Safe validation diagnostic; create POST count is zero. |

## Future cross-type identity

Do not merge Post and Reel identities based on shortcode equality. A future cross-type merge may be considered only with a trustworthy stable Actor media ID proven to be shared across URL forms. Document issuer and scope, demonstrate stability, and reject missing, malformed, colliding, or conflicting IDs before enabling the rule. Until then, typed identities remain distinct.

## Required offline G2 test plan

- `/reel/X` and `/reels/X` deduplicate to one Reel task; every source URL participates in exact attribution.
- `/p/X` and `/reel/X` remain separate; shortcode-only evidence without item media type is ambiguous even with one candidate task.
- `X` and `x` remain distinct; host case and optional trailing slash do not alter typed identity.
- Invalid host/path/query/fragment/userinfo/port inputs fail before any create POST.
- Duplicate source occurrences and input indexes survive planning in original order.
- URL is validated and matched across all source URLs before fallback; contradictory shortcode/type prevents success.
- Shortcode-only fallback requires reliable item media type; no positional assignment is allowed.
- Duplicate Dataset items, extras, conflicts, and invalid items are explicit and retained exactly once.
- Incomplete Dataset cannot produce batch `success` or `empty`.
- Counts equal the serialized arrays; status, reason, attribution, and exit code use only their respective vocabularies above.
- Every serialized extra item passes key and text sanitization.
