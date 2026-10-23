# Go Client and Examples

This Go 1.22 module provides a reusable `transcriptapi` Client plus Single URL, Native Bulk,
Profile, and CSV Batch examples for `apple_yang/instagram-transcripts-scraper`. Live-verified
examples use the controlled Build `0.0.50` / `aJLRmMdQapLQRT4sJ`; this is a pinned, tested Build,
not a claim that it is the Actor's latest Build. Go implements the modes documented here but is not
a complete feature-for-feature replacement for the Python or Node.js examples.

## Live verification scope

Controlled Go Live checks on Build `0.0.50` covered Single URL, one three-URL Native Bulk Run and a
Resume of that same Run, one Profile account with `resultsLimit=1`, CSV dry-run, and one CSV row.
Single URL returned a transcript with 15 segments; the Bulk inputs returned 15, 14, and 12
segments, and GET-only Resume returned the same Run and Dataset; Profile returned one post's
metadata; the CSV row returned a transcript with 15 segments. The Single, Bulk, Profile, and CSV
Live requests used a `$0.10` per-Run cap and `restartOnError=false` where recorded. The reported
Single Run usage was `$0.0055`; usage for the new Bulk, Profile, and CSV Runs was not independently
verified in this local evidence. The CSV row result does not expose `datasetComplete`, so CSV
Dataset completeness was not independently established from that JSON. These are narrow,
controlled checks, not a production reliability guarantee, and a Run cap is not an absolute final
bill limit. Single Resume has offline test coverage; dedicated Single Resume Live acceptance was
not performed.

## Safety behavior

- Importing the package has no environment, credential, network, or file side effects. Pass the
  token through `Config`; CLIs read `APIFY_TOKEN` from the process environment only and do not load
  `.env`.
- Input URLs, usernames, and full CSV contents are validated before credentials are read or a Run
  is created. The CSV CLI defaults to a zero-Run plan; `--execute` is required to submit one
  independent Run per non-empty row.
- Native Bulk submits the validated `bulkUrls` array in one Actor Run. URL identity is primary;
  shortcode fallback is used only when an output item has no URL. Conflicts and unmatched items are
  kept as extras or unknown results rather than assigned by position.
- Profile returns post metadata, not transcripts. Multi-account attribution requires each post's
  `ownerUsername` to match a requested account; for one account, a missing owner is accepted under
  the single-account rule and a conflicting owner remains unknown.
- Build Number and Build ID are checked against the returned Run before Dataset items are accepted.
  New Run requests explicitly send `restartOnError=false`. The creation POST cannot follow
  redirects and is never automatically retried; ambiguous creation returns `creation_unknown`.
- Configure `RequireChargeCap: true` with a positive `MaxTotalChargeUSD` or set the matching CLI
  option/environment variables. The cap is a Run query option, not Actor input, and is not a
  guarantee of the final account bill.
- JSONL Journal intent is synced before creation and the Run identity is synced immediately after
  creation. Journal failures stop further paid work. Resume requires a matching journal record and
  the exact original Actor input; it performs GETs only and never creates a Run.
- Dataset reads use one page with `offset=0` and a configured item limit (default 1000). Reaching
  the limit marks the result incomplete; general pagination is not implemented.
- Result files are unique and use mode `0600` on POSIX. Windows does not provide identical POSIX
  permission semantics.

## Quick starts

From `examples/go`, configure `APIFY_TOKEN`. The CLI never loads `.env`.

```sh
export APIFY_TOKEN='your-token'
export APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD=1
export APIFY_MAX_TOTAL_CHARGE_USD=0.30
```

PowerShell:

```powershell
$env:APIFY_TOKEN = 'your-token'
$env:APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD = '1'
$env:APIFY_MAX_TOTAL_CHARGE_USD = '0.30'
```

Single URL:

```sh
go run ./cmd/single-url https://www.instagram.com/reel/your_reel_id/
```

Native Bulk — one Run for all URLs:

```sh
go run ./cmd/native-bulk https://www.instagram.com/reel/first_id/ https://www.instagram.com/reel/second_id/
```

Profile — metadata only:

```sh
go run ./cmd/profile --results-limit 2 public_username
```

CSV Batch validates the complete file first. It plans by default, with zero credentials read and
zero Runs; use `--execute` only when you intend one separate Run per row:

```sh
go run ./cmd/batch-csv --dry-run path/to/urls.csv
go run ./cmd/batch-csv --execute --require-charge-cap --max-total-charge-usd 0.30 path/to/urls.csv
```

CSV input is UTF-8 with a header containing either `url` or `videoUrl`. A BOM and common newline formats are
accepted. Empty files and empty datasets create no Runs. Every non-empty data row is an independent
task and can incur a separate charge; rows execute serially, and an unknown creation or persistence
state stops the batch from launching more Runs.

`--max-total-charge-usd` is a **per-Run** cap, not a total CSV budget. The default dry-run plan
includes `perRunCapUsd` and `estimatedMaximumRunCapsTotalUsd` only when a positive cap is available;
the latter is `maximumRuns × perRunCapUsd`, an arithmetic estimate rather than a final-bill limit.
Dry-run never reads `APIFY_TOKEN` or creates Runs. An empty CSV creates no Run.

Every CLI accepts `--help`, `--output-dir`, and `--journal`; mode-specific options are shown by each
help page. Outputs use unique files under `sample-output/generated/` by default. JSON retains the
full transcript/segments or Profile posts and original Actor items; stdout is a compact JSON result.

## Resume

Single URL recovery:

```sh
go run ./cmd/single-url --resume RUN_ID https://www.instagram.com/reel/your_reel_id/
```

Native Bulk recovery:

```sh
go run ./cmd/native-bulk --resume RUN_ID https://www.instagram.com/reel/first_id/ https://www.instagram.com/reel/second_id/
```

Use the same Journal path and exact original inputs. Resume refuses missing or mismatched Journal
context and performs only GET requests. CSV and Profile Resume are not supported. Never rerun a
create command just because its prior creation outcome is unknown.

## Reusable Client

```go
package main

import (
	"context"
	"fmt"
	"os"
	"time"

	"github.com/apismith-labs/instagram-reels-transcript-api/examples/go/transcriptapi"
)

func main() {
	journal, err := transcriptapi.OpenJSONLJournal("sample-output/generated/go-run-journal.jsonl")
	if err != nil { panic(err) }
	defer journal.Close()
	client, err := transcriptapi.NewClient(transcriptapi.Config{
		Token: os.Getenv("APIFY_TOKEN"), RequireChargeCap: true, MaxTotalChargeUSD: 0.30, Journal: journal,
	})
	if err != nil { panic(err) }
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	result := client.GetTranscript(ctx, "https://www.instagram.com/reel/your_reel_id/")
	fmt.Println(result.Status, result.RunID, result.DatasetID, result.Text)
}
```

The Client exposes `GetTranscript`, `GetTranscripts`, `GetProfilePosts`, and
`GetTranscriptsFromCSV`. It accepts dependencies explicitly and does not read process environment
or `.env`. Inject an `*http.Client` with a fake `RoundTripper`, a Journal, clock, and context-aware
sleep function for offline tests. `Result` retains the v0.8.0 Single URL JSON contract. Bulk results
include per-input status, attribution, counts, extras, complete raw items and Dataset completeness;
Profile results retain metadata and raw items without requiring transcript fields.

The nested module path is
`github.com/apismith-labs/instagram-reels-transcript-api/examples/go`; import the package at
`github.com/apismith-labs/instagram-reels-transcript-api/examples/go/transcriptapi`. The published
v0.8.0 module can be installed with:

```sh
go get github.com/apismith-labs/instagram-reels-transcript-api/examples/go@v0.8.0
```

That external installation and compilation were verified for v0.8.0 with Go 1.27.3. The v0.9.0
release candidate adds the features and Live evidence described above; its versioned install
command becomes available only after the root and nested-module v0.9.0 tags are published and
verified. The v0.8.0 root repository release tag is `v0.8.0`, while its nested Go Module tag is
`examples/go/v0.8.0`; the command above resolves the Module tag, not the root tag. For the planned
v0.9.0 release, the post-publication install command will be:

```sh
go get github.com/apismith-labs/instagram-reels-transcript-api/examples/go@v0.9.0
```

The nested Go Module tag follows `examples/go/vX.Y.Z` and must point to the same commit as the
corresponding root release tag. Do not use a local `replace` when validating a published version.

## Result states and exit codes

Single URL retains the existing exit code contract: `success` 0, input/configuration error 2,
`actor_error` 4, `empty` 5, `no_transcript` 6, `unknown` 7, `transport_error` 8, `run_failed` 9,
and `creation_unknown` 10. This `ExitCode` table applies to Single URL execution states. Native Bulk
uses `BulkExitCode`: `all_success` 0, `partial_success` 11, `all_failed` 12, `unknown` 13; execution
failures retain their Single URL code (for example, `creation_unknown` 10). Profile returns 0 for
`success`/`empty`, 4 for `actor_error`, 7 for `unknown`, and uses execution failure codes such as 8/9/10.
CSV returns 2 for invalid input, 8/9/10 for transport/run/creation-unknown failures, 11 for other
row failures, and 0 when all rows succeed or there is no work. Non-zero exits can still leave a
unique result file containing completed rows; inspect it to recover partial results.

Place CLI options before positional usernames or URLs. Explicitly passing an empty Profile date
filter is rejected. CSV skips physically empty rows; a non-empty row with a blank URL is rejected
before execution. A stopped CSV result includes `plannedRows` and `unattemptedRows`.

Dataset reads are single-page only. The CSV aggregate exposes row outcomes but does not expose
`datasetComplete`; consult the available per-Run journal and result evidence without treating the
CSV summary as proof of complete pagination. Go does not yet implement every Python or Node.js
API, parallel CSV execution, generalized pagination, Profile/CSV Resume, or Actor-side capabilities
not exposed by the current examples. The controlled Live checks do not cover arbitrary Bulk sizes,
mixed Bulk failures, multiple Profile accounts, multi-row CSV execution, or broad production
reliability.
