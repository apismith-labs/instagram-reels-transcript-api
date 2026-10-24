# G2 Instagram URL Identity and Attribution Contract

This document defines the design contract for a future Rust Native Bulk implementation. It does not mean that G2 Bulk behavior is implemented or available in G1.

## Accepted URLs and identity

G2 must validate each URL with the existing G1 URL rules before planning any Run. The parsed HTTPS host must be exactly `instagram.com` or `www.instagram.com`; do not add `m.instagram.com`, other subdomains, or alternate hosts without a separate contract change. The accepted paths are `/reel/{shortcode}`, `/reels/{shortcode}`, and `/p/{shortcode}`. Query strings, fragments, credentials, explicit ports, whitespace, and other path forms remain invalid under the current validator.

Introduce a typed helper with a contract equivalent to:

```rust
pub fn media_identity(url: &str) -> Option<(MediaType, String)>
```

`MediaType` is `Reel` for both `/reel/` and `/reels/`, and `Post` for `/p/`. The identity key is `(MediaType, shortcode)`. Shortcodes are case-sensitive and must never be lowercased or otherwise case-folded. Host spelling and one optional trailing slash do not change identity. `/reel/X` and `/reels/X` are aliases; `/p/X` and `/reel/X` remain different identities even when their shortcode text is equal.

This typed identity is distinct from G1's `canonical_video_identity(url) -> Option<String>`, which returns only the shortcode and is used by the already-accepted G1 Single attribution behavior. G2 must not use that shortcode-only helper for typed deduplication or attribution.

For exact URL evidence, define `normalized_url_identity` as the URL after successful validation, with the host normalized to `instagram.com`, the one optional trailing slash removed, and the accepted path and shortcode preserved exactly. This full normalized URL is more specific than `(MediaType, shortcode)`: `/reel/X` and `/reels/X` share a typed Reel identity but have different normalized URL paths. No query or fragment normalization is needed because those inputs are rejected.

## Input, identity, and task mapping

Build a three-layer plan before any create POST:

```text
Original Input URL (index + exact string) -> typed Media Identity -> Unique Task
```

Use zero-based input indexes. Validate every input before creating the plan; an invalid URL should reject the entire request during preflight, identify the offending index safely, and produce zero create POSTs. Deduplicate automatically by `(MediaType, shortcode)`. A duplicate identity does not reject the whole Bulk request.

The first occurrence of an identity determines the task's output order. Each unique identity creates one task and one primary result row. Preserve every original input occurrence, including repeated identical URL strings, in aligned `sourceIndexes[]` and `sourceUrls[]` arrays. Do not use a Set or any other representation that loses duplicate count or source position. The arrays preserve original input order and have equal lengths.

For example, these inputs create two tasks, not an input error:

```text
0 https://instagram.com/reel/ABC123
1 https://instagram.com/reels/ABC123
2 https://instagram.com/p/ABC123
```

The first two occurrences map to one Reel task, and the third maps to a separate Post task. A repeated exact URL also appears twice in `sourceIndexes[]` and `sourceUrls[]`.

The following is a target G2 output schema only; G1 does not implement it:

```json
{
  "identity": { "mediaType": "reel", "shortcode": "ABC123" },
  "sourceIndexes": [0, 1],
  "sourceUrls": [
    "https://instagram.com/reel/ABC123",
    "https://instagram.com/reels/ABC123"
  ],
  "status": "success"
}
```

## Dataset attribution

Attribute each Dataset item independently, without using its array position or return order:

1. Prefer exact matching of `normalized_url_identity` when a valid item URL is present.
2. Otherwise, use typed `(MediaType, shortcode)` evidence only when it identifies exactly one unique task and no URL evidence conflicts.
3. A shortcode-only fallback is allowed only when the expected type is known and the candidate is unique.
4. If the same shortcode is requested as both a Post and a Reel and an item contains only that shortcode with no valid URL or media type, mark the item explicitly ambiguous/unknown. Do not assign its transcript to either task.

For example:

```text
Inputs:  /p/ABC123, /reel/ABC123
Dataset: shortcode=ABC123, url missing, media type missing
Expected: ambiguous/unknown; no successful attribution; no positional assignment
```

One Dataset item may not satisfy multiple distinct tasks. Conflicting URL and shortcode evidence, malformed identity data, duplicate items, extra items, and items that cannot be attributed must be recorded with explicit conservative statuses and safe diagnostics. Do not ignore unassigned Dataset data because another task matched. Incomplete Dataset reads cannot produce an all-success result.

## G1 Single compatibility

G1 `canonical_video_identity()` returns only the shortcode, so G1 Single can currently treat `/reel/X` and `/p/X` as the same identity while comparing a requested URL with a Dataset URL. This is an accepted existing G1 behavior. This design does not change the G1 validator or Single attribution. G2 must use typed identities consistently for Bulk deduplication and attribution. Any later change to Single needs its own contract review and regression tests.

## Future cross-type identity

Do not merge Post and Reel identities based only on matching shortcodes. A future cross-type alias may be considered only when the Actor provides a trustworthy, stable media ID demonstrably shared by both URL types. Before enabling it, document the ID issuer and scope, prove stability across representations, reject missing, colliding, malformed, or conflicting IDs, and add fixtures for each case. Until then, Post and Reel remain distinct.

## Required offline G2 test plan

- `/reel/X` and `/reels/X` deduplicate to one Reel task.
- `/p/X` remains distinct from `/reel/X`, even with the same shortcode.
- `X` and `x` remain distinct.
- Accepted host spellings and one trailing slash do not change typed identity.
- Query, fragment, userinfo, explicit-port, unsupported-host, and invalid-path inputs fail before any create POST.
- Duplicate aliases and repeated exact URLs are automatically deduplicated while all source indexes and URL occurrences are preserved.
- Unique tasks and results retain first-occurrence order.
- Exact normalized URL attribution takes precedence over fallback evidence.
- Typed identity fallback succeeds only for one compatible task and with no conflicting URL.
- `/p/X` and `/reel/X` plus a Dataset item with only shortcode `X` produce an explicit ambiguous/unknown result, never a positional assignment.
- URL/shortcode conflicts, duplicate Dataset items, extra items, and unassigned items remain explicit and conservative.
- No result is assigned by array position, and incomplete Dataset state is conservative.
