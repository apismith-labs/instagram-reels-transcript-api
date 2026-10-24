# Compatibility and Verification

This matrix separates implemented features from recorded live evidence. **Live-verified** means a narrow controlled acceptance was recorded for the stated case; it does not promise general reliability. **Offline-only** means covered by local/CI tests without a real Actor call. **Unverified** means no adequate evidence is recorded. **Not implemented** means the integration does not provide that feature.

## Language and mode status

| Integration | Single transcript | Native Bulk | Profile metadata | CSV Batch | Resume |
| --- | --- | --- | --- | --- | --- |
| Python | Live-verified, narrow single URL | Live-verified, one fixed three-URL run | Live-verified, one account / one post | Offline-only; live CSV rows unverified | Single Resume is implemented; dedicated live acceptance unverified |
| Node.js | Live-verified, narrow single URL | Live-verified, narrow run | Implemented; live acceptance unverified | Implemented; live acceptance unverified | Single and Bulk Resume are implemented; live acceptance unverified |
| cURL | Example available; live status unverified here | Not implemented in the cURL example | Not implemented in the cURL example | Not implemented in the cURL example | Not implemented in the cURL example |
| Go | Live-verified, narrow single URL | Live-verified, one three-URL run | Live-verified, one account / one post | Live-verified, one row; CSV Dataset completeness not independently asserted | Bulk Resume live-verified; Single Resume offline-only |
| Java | Live-verified, narrow single URL | Live-verified, one three-URL run | **PARTIAL**: 19 successes, 1 owner unknown, 1 Actor error | Live-verified, one row | Single Resume live-verified; Bulk Resume is implemented but live-unverified |
| Rust | Live-verified, one URL | Live-verified, one three-URL run | Live-verified, one account / one post | Live-verified, one row | Single and Bulk same-Run Resume live-verified |
| Apify MCP | Actor-call path is available through the documented MCP setup; mode-by-mode live acceptance is unverified | Unverified by MCP client | Unverified by MCP client | Unverified by MCP client | Not a repository SDK Resume API |

All live evidence is scoped to the documented controlled cases and Build `0.0.50` where recorded. Rust G5 covered six checks: Single, same-Run Single Resume, three-URL Native Bulk, same-Run Bulk Resume, one Profile result, and one CSV row. Rust's actual billed amount remains unknown. Java Profile is partial, not a complete pass. No row in this table establishes production-scale reliability.

## Shared capability boundaries

- Profile mode returns post metadata; it does not generate transcript text.
- Native Bulk submits multiple URLs in a single Actor Run. CSV Batch creates an independent Run for each non-empty row in supported SDKs; it is not the same mode.
- Rust CSV defaults to offline planning; execution is explicit and requires a positive per-Run charge cap. Resume is GET-only for supported Single and Bulk records; CSV and Profile Resume are not implemented in Rust.
- A requested per-Run charge cap is an execution option, not an absolute final-bill guarantee.
- The SDKs pin/check Build identity according to their language-specific contracts. The controlled evidence cited here used Build `0.0.50`; do not assume it is the Actor's latest Build.
- Some languages have not live-tested every mode, failure path, pagination boundary, mixed-failure batch, or ambiguous create outcome. Consult each language README before depending on an unverified behavior.

## Repository Release vs language package publication

A GitHub Release/tag versions this repository source snapshot and its release notes. It does **not** automatically publish packages to language registries.

| Language | Repository / package state |
| --- | --- |
| Python | Source examples in this repository; no package publication is implied by a GitHub Release. |
| Node.js | Source examples in this repository; no npm publication is implied by a GitHub Release. |
| Go | Nested Go module has its own module tag/version strategy; a root repository tag is not itself a Go module publication check. |
| Java | Maven example artifact is source-integrated and not published to Maven Central. |
| Rust | Cargo package is `instagram-transcripts-rust`, manifest version `0.1.0`; this repository Release does not publish it to crates.io. |

For package-install availability, check the corresponding registry and language-specific release/tag instructions. Do not infer it from the GitHub Release version.

## More detail

- [Quick Start](quickstart.md)
- [Cost estimation](cost-estimation.md)
- [Python](../examples/python/README.md)
- [Node.js](../examples/nodejs/README.md)
- [Go](../examples/go/README.md)
- [Java](../examples/java/README.md)
- [Rust](../examples/rust/README.md)
- [MCP overview](use-with-apify-mcp.md)
