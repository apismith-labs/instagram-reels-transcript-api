# G2 Instagram URL Identity Contract

This document defines the identity rules to use when a future Rust Native Bulk implementation deduplicates inputs and attributes Dataset items. It is a design contract only; G2 Bulk behavior is not implemented here.

## Canonical identity

For an accepted Instagram video or post URL, use a typed identity:

```text
(media_type, shortcode)
```

The media type is `Reel` for both `/reel/{shortcode}` and `/reels/{shortcode}`, and `Post` for `/p/{shortcode}`. The two Reel path forms are aliases and therefore produce the same identity. A Post and a Reel with the same shortcode remain distinct by default.

Shortcodes are case-sensitive. Do not lowercase or otherwise case-fold them. Normalize only URL components that do not define media identity, such as the accepted Instagram host spelling and a trailing slash. Query strings and fragments are currently rejected by the Rust G1 input validator; this contract does not change that validation behavior. If a future validator accepts tracking parameters, they must be excluded from the identity only after that policy is explicit and tested.

Examples:

| Input | Identity |
| --- | --- |
| `https://www.instagram.com/reel/AbC123/` | `(Reel, AbC123)` |
| `https://instagram.com/reels/AbC123` | `(Reel, AbC123)` |
| `https://instagram.com/p/AbC123/` | `(Post, AbC123)` |
| `https://instagram.com/reel/abc123` | `(Reel, abc123)` |

The first two URLs are aliases. The third is not merged with them, and the fourth is a different case-sensitive shortcode.

## Deduplication and Dataset attribution

Future Bulk input deduplication and Dataset result attribution must use this same typed identity function. Reject duplicate input identities (including `/reel/` versus `/reels/` aliases) before creating a Run. Match results by an exact accepted URL identity first. A shortcode-only fallback is safe only when it yields one unique candidate of the expected media type and there is no conflicting URL evidence. Never use result position to assign an item to an input.

If a Dataset item is malformed, has conflicting URL and shortcode evidence, maps to multiple inputs, or cannot be uniquely attributed, retain it as unknown or extra according to the public result contract. Do not guess an owner. Incomplete Dataset reads must not be reported as complete success.

## Relationship to G1 Single behavior

The current G1 `canonical_video_identity()` returns only the shortcode. Consequently, G1 Single attribution can treat `/reel/X` and `/p/X` as the same identity when comparing a requested URL with a returned Dataset URL. That is an existing, already-accepted Single behavior. This task does not change the G1 validator or Single attribution. G2 must introduce and consistently use the typed identity above for Bulk deduplication and attribution; any later change to Single requires its own contract review and regression tests.

## Future trusted cross-type merging

Cross-type merging may be considered only if the Actor provides a trustworthy, stable media ID that is demonstrably shared by both representations. Before enabling it, document the ID's issuer and scope, prove it is stable across URL types, reject ambiguous or conflicting mappings, and add fixtures for valid matches, collisions, missing IDs, and malicious/malformed IDs. Until those conditions are independently verified, `(Reel, shortcode)` and `(Post, shortcode)` remain separate identities.

## Required offline test plan for G2

- `/reel/X` and `/reels/X` deduplicate to one Reel identity.
- `/p/X` remains distinct from `/reel/X`.
- `X` and `x` remain distinct shortcodes.
- Host spelling and trailing slash do not change an otherwise valid identity.
- Query and fragment behavior follows the validator policy and never silently changes identity.
- Duplicate input aliases are rejected before any create POST.
- Exact URL attribution wins over shortcode-only candidates.
- Shortcode fallback succeeds only for one type-compatible candidate.
- URL/shortcode conflicts and ambiguous candidates stay unknown/extra.
- No result is assigned by array position, and incomplete Dataset state is conservative.
