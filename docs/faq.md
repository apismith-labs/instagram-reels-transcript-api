# First-call FAQ

## 1. Will my first call cost money?

It starts a real Actor Run and may incur event charges. The documented examples request a `$0.10` per-Run cap, but that is not an absolute final-bill guarantee. Check the [current Actor pricing](https://apify.com/apple_yang/instagram-transcripts-scraper/pricing) and [cost examples](cost-estimation.md) before running.

## 2. Where does the API token go?

Set `APIFY_TOKEN` in your process environment or secret manager. The examples send it in an Authorization Bearer header; do not put it in a URL, source file, command-line argument, or Git. See the [Quick Start](quickstart.md).

## 3. Does one URL call create one Run?

The Single workflow creates one Actor Run. Native Bulk puts several URLs in one Run. CSV Batch is different: each non-empty row creates an independent Run when execution is explicitly enabled. See the [batch guide](batch-processing-guide.md).

## 4. Does Profile return transcripts?

No. Profile returns post metadata and owner information. To get a transcript, make a separate Single or Native Bulk request for the post URL.

## 5. Is a successful Run the same as a successful transcript?

No. Check the Dataset item too. A non-empty `errMsg`, an empty Dataset, or missing transcript `text` needs separate handling even if the Run itself completed. See [input/output fields](input-output-fields.md) and [error handling](error-handling-and-retries.md).

## 6. What should I do if the create request times out?

Do not retry the create POST. The Actor may have accepted it before the response was lost. Reconcile the Run in Apify using your account's run history and the Run ID if you received one. The client reports ambiguous creation as `creation_unknown` where applicable.

## 7. Is `sessionid` required?

The Quick Start does not use it. The Actor's current public description calls it optional, but the audited schema for pinned Build `0.0.50` omits it, so its runtime effect for that Build is unknown. Treat a session ID as sensitive authentication data and never commit or log it; any benefit is not guaranteed.

## 8. What does the charge cap do?

It is a per-Run Apify option. It is not a shared budget across a CSV batch and should not be described as an absolute bill limit. Review [cost estimation](cost-estimation.md).

## 9. How do I choose Single, Bulk, Profile, or CSV?

Choose Single for one URL; Native Bulk for several URLs in one Actor Run; Profile for public post metadata by username; CSV when you need row-by-row independent Runs. Use the [batch guide](batch-processing-guide.md) for the cost and execution distinction.

## 10. What is the difference between an SDK and MCP?

An SDK is a library or CLI that your program invokes directly. MCP connects an AI client to Apify tools that can discover and call Actors. MCP is a separate integration path; it does not make an SDK's offline/live verification apply to MCP. See [MCP setup](use-with-apify-mcp.md) and the [compatibility matrix](compatibility.md).

## 11. Is every language equally verified?

No. Implemented features and recorded live tests differ by language. Java Profile's recorded three-account test was partial; several CSV, multi-account, mixed-failure, and scale cases remain unverified. Check the [compatibility matrix](compatibility.md) and the relevant language guide.

## 12. Does GitHub Release v0.11.0 publish the Rust crate?

No. A GitHub Release versions the repository. The Rust manifest package is `instagram-transcripts-rust` at `0.1.0`; crates.io publication is separate and is not implied by the repository tag. See [compatibility](compatibility.md).
