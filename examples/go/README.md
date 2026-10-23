# Go Client and Examples

This Go 1.22 module provides a reusable `transcriptapi` Client plus Single URL, Native Bulk,
Profile, and CSV Batch examples for `apple_yang/instagram-transcripts-scraper`. The public API
uses the pinned Build `0.0.50` / `aJLRmMdQapLQRT4sJ`. Go now covers these modes, while Resume is
available for journaled Single URL and Native Bulk Runs; it does not yet match every Python or
Node.js feature.

## Live verification scope

Go Single URL completed one controlled Live verification with Build `0.0.50`. The Run succeeded,
returned transcript text and 15 timestamped segments, and verified the expected Build and URL
attribution. Apify Run metadata confirmed the requested `$0.10` charge cap and
`restartOnError=false`; reported usage was `$0.0055`. This single test is not a large-scale
production reliability guarantee, does not establish that every video can be transcribed, and the
charge cap is not an absolute final-bill limit. Native Bulk, Profile, and CSV Batch do not have a
new Go Live acceptance in this release.

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

That external installation and compilation were verified for v0.8.0 with Go 1.27.3. The parity
features described above are development-branch work and are not part of the published v0.8.0
module. For a checkout under development, use a local `replace` directive rather than claiming the
unreleased APIs are available from v0.8.0. Future nested-module tags follow
`examples/go/vX.Y.Z` and must point to the same commit as the corresponding root release tag.

## Result states and limits

Single URL retains the existing exit code contract: `success` 0, input/configuration error 2,
`actor_error` 4, `empty` 5, `no_transcript` 6, `unknown` 7, `transport_error` 8, `run_failed` 9,
and `creation_unknown` 10. Bulk returns `all_success`, `partial_success`, `all_failed`, or `unknown`
and preserves per-input statuses. Profile returns `success`, `empty`, `actor_error`, or `unknown`;
it does not classify missing transcript text as failure. CSV records successes and failures per row.

Dataset reads are single-page only. Native Bulk, Profile, and CSV Batch have offline coverage but
no new Go Live acceptance in this release. Go does not yet implement every Python or Node.js API,
parallel CSV execution, generalized pagination, Profile/CSV Resume, or Actor-side capabilities not
exposed by the current examples.
