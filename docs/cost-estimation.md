# Cost Estimation

Pricing is controlled by the Actor's current Apify Store pricing and your Apify plan. This page records the public pricing table checked on **2026-10-24**; re-check the [Actor Pricing page](https://apify.com/apple_yang/instagram-transcripts-scraper/pricing) before budgeting or running. The Actor page currently lists a primary result event and an automatic audio-to-text event, with platform usage included. It does not publish enough detail to promise the exact event count for every input or outcome.

## Published event rates

The public pricing table currently lists these rates per 1,000 events:

| Event shown on Actor Pricing page | Free | Starter | Scale | Business |
| --- | ---: | ---: | ---: | ---: |
| Result Primary | $1.00 | $1.00 | $1.00 | $1.00 |
| Cost-Effective Audio-to-Text (Auto) | $4.50 | $3.50 | $3.00 | $2.00 |
| Platform usage | Included | Included | Included | Included |

Equivalent unit prices are $0.001 per primary result event and, respectively, $0.0045, $0.0035, $0.003, or $0.002 per audio-to-text event. These are event rates, not a guaranteed per-input price. Plan subscription fees, taxes, credits, event eligibility, and any future pricing changes are not included in the arithmetic below.

The Store page says transcript extraction can incur result pricing plus audio-to-text pricing, while Profile metadata uses result pricing only. It describes audio-to-text as charged when speech recognition is performed. The exact event count for every failure, duplicate, no-speech item, or Actor path is **UNKNOWN** unless the current pricing rules or a measured Run establish it.

The Actor page also announces an Enhanced Crawl charge beginning **2026-11-04**, conditional on successful retrieval, but does not give a rate in the public pricing table reviewed here. Its price and precise event count are **UNKNOWN**. The Quick Start is pinned to Build `0.0.50`; verify current Build and pricing before relying on this page after that effective date.

## Illustrative arithmetic (assumptions, not quotes)

For illustration only, assume each transcript input produces exactly one billable primary result and exactly one billable audio-to-text event. Under those assumptions:

| Mode / example | Assumed billable events | Free | Starter | Scale | Business |
| --- | --- | ---: | ---: | ---: | ---: |
| Single transcript, one returned item | 1 primary + 1 audio-to-text | $0.0055 | $0.0045 | $0.0040 | $0.0030 |
| Native Bulk, three returned transcripts | 3 primary + 3 audio-to-text | $0.0165 | $0.0135 | $0.0120 | $0.0090 |
| Profile, twelve returned post rows | 12 primary; no transcript event assumed | $0.0120 | $0.0120 | $0.0120 | $0.0120 |
| CSV, ten rows each returning one transcript | 10 primary + 10 audio-to-text across 10 Runs | $0.0550 | $0.0450 | $0.0400 | $0.0300 |

Formula: `(primary event count × $0.001) + (audio-to-text event count × plan-specific rate)`. CSV is a repository client workflow that starts one independent Actor Run per non-empty row; the example assumes all ten rows reach the stated event pattern. Actual result counts and charges may differ.

## By mode

- **Single:** normally the smallest transcript trial. Its actual result and audio-to-text event counts depend on the Actor's processing and billing rules. The per-item price is not a fixed cost per submitted URL.
- **Native Bulk:** one Actor Run contains multiple `bulkUrls`. Use the number of actual billable events, not just the number of submitted URLs, in an estimate. Missing, duplicate, failed, or partially returned items have outcome-specific billing semantics that are **UNKNOWN** here.
- **Profile:** uses `usernames` and returns post metadata, not transcripts. The Actor's pricing description says this mode uses result pricing only. Estimate from the actual number of chargeable returned rows; the relationship between `resultsLimit` and billable result count must not be assumed beyond the Actor's contract.
- **CSV:** the Rust/SDK CSV workflow creates one separate Run per non-empty row when explicitly executed. Multiply event estimates by rows and budget for multiple Runs. A per-Run cap is not a CSV-wide aggregate limit.

## Caps and safe budgeting

SDKs and the API can send `maxTotalChargeUsd` as a Run option. It is an execution protection option; it is **not an absolute guarantee of the final account bill**. For CSV, each row is a separate Run, so a `$0.10` cap on each of ten rows is ten requested per-Run caps, not a single `$0.10` batch cap. Check the current Actor pricing page, your plan, and your Apify usage before and after a controlled run.

Do not automatically retry a create request after a timeout or ambiguous response: the first Run may already exist and a retry can create another billable Run. Reconcile the Run first. See the [Quick Start](quickstart.md), [error and retry guide](error-handling-and-retries.md), and [batch guide](batch-processing-guide.md).

## Sources

- [Actor Pricing page](https://apify.com/apple_yang/instagram-transcripts-scraper/pricing), checked 2026-10-24.
- [Actor description, modes, and input/output overview](https://apify.com/apple_yang/instagram-transcripts-scraper), checked 2026-10-24.
- [Apify API: Run Actor](https://docs.apify.com/api/v2/actors-runs-post), including `maxTotalChargeUsd`, `restartOnError`, and `build` Run options.
