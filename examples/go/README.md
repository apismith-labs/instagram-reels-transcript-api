# Go Single URL Client MVP

This Go example provides an importable `transcriptapi` package and a Single URL CLI for the
Apify Actor `apple_yang/instagram-transcripts-scraper`. It is a Go 1.22 module and is not at
Python or Node.js feature parity. It has not received a real Actor acceptance.

## Safety behavior

- The Client import has no environment, credential, network, or file side effects. Pass the token
  through `Config`; the CLI reads `APIFY_TOKEN` from the process environment only and does not load
  `.env`.
- Reel/post URLs are validated before the CLI reads credentials. Only HTTPS `reel`, `reels`, and
  `p` URL paths on `instagram.com` are accepted; query strings and fragments are rejected.
- Build Number `0.0.50` and Build ID `aJLRmMdQapLQRT4sJ` are fixed and verified against the
  returned Run metadata before Dataset contents are accepted.
- Set `RequireChargeCap: true` and a positive `MaxTotalChargeUSD` (or use the CLI options below).
  The cap is sent as the Run query option, not Actor input. Apify may reject it and it is not a
  guarantee of the final account bill.
- New Run requests explicitly send `restartOnError=false`. The creation POST is attempted once;
  HTTP 429, server errors, timeouts, and ambiguous responses are not retried. A
  `creation_unknown` outcome must be reconciled before any separate retry decision.
- An append-only JSONL Journal records intent before creation and the known Run identity as soon as
  available. Journal failures stop the flow; a Run created before a persistence error is returned
  with its known IDs where available.
- Dataset reads set a single-page limit. `datasetComplete=false` means the response reached that
  configured limit; it does not implement pagination.
- Output and Journal files use unique or append-only names and mode `0600` on POSIX. Windows does
  not provide identical POSIX permission semantics.

## CLI

From this module directory, configure the process environment and run one explicit URL:

```sh
export APIFY_TOKEN='your-token'
export APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD=1
export APIFY_MAX_TOTAL_CHARGE_USD=0.30
go run ./cmd/single-url https://www.instagram.com/reel/your_reel_id/
```

PowerShell:

```powershell
$env:APIFY_TOKEN = 'your-token'
$env:APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD = '1'
$env:APIFY_MAX_TOTAL_CHARGE_USD = '0.30'
go run ./cmd/single-url https://www.instagram.com/reel/your_reel_id/
```

The CLI also accepts `--max-total-charge-usd`, `--require-charge-cap`, `--output-dir`, and
`--journal`. Run `go run ./cmd/single-url --help` for usage. The CLI writes a unique JSON result
under `sample-output/generated/` by default and appends Journal entries to
`sample-output/generated/go-run-journal.jsonl`. It prints a JSON result summary with Run ID,
Dataset ID, Build evidence, status, transcript, segments, and output path. A failed or unknown
result has a non-zero status-specific exit code; in particular, exit code 10 means the creation
outcome is unknown and the POST must not be blindly repeated.

Status exit codes: `success` 0, input/configuration error 2, `actor_error` 4, `empty` 5,
`no_transcript` 6, `unknown` 7, `transport_error` 8, `run_failed` 9, and `creation_unknown` 10.

## Reusable Client

The module path is `github.com/apismith-labs/instagram-reels-transcript-api/examples/go` and the
package import path is the `/transcriptapi` subpackage. The Client accepts dependencies explicitly;
it does not read process environment or `.env` itself.
This nested module does not claim compatibility with the repository's root-level release tags; do
not assume `go get ...@v0.7.0` works. A module-prefixed Go tag is needed before versioned install
instructions can be documented.

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
		Token: os.Getenv("APIFY_TOKEN"),
		RequireChargeCap: true,
		MaxTotalChargeUSD: 0.30,
		Journal: journal,
	})
	if err != nil { panic(err) }

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	result := client.GetTranscript(ctx, "https://www.instagram.com/reel/your_reel_id/")
	fmt.Println(result.Status, result.RunID, result.DatasetID, result.Text)
	if result.Status != transcriptapi.StatusSuccess { os.Exit(transcriptapi.ExitCode(result.Status)) }
}
```

`Result` retains `Status`, actual `RunStatus`, `RunID`, `DatasetID`, `ActorID`, Build Number and ID,
`BuildVerification`, `DatasetComplete`, `Text`, `Segments`, `RawItems`, and error information.
`Cause` provides a typed error for transport, protocol, Journal, or ambiguous-creation failures and
is omitted from JSON. The caller can inject an `HTTPDoer`, `Journal`, clock, and context-aware sleep
function for isolated tests.

The module currently supports Single URL only. Native Bulk, Profile, Resume, and complete CSV Batch
are not implemented.

## Retired CSV Batch entry

The former `batch_csv.go` implementation is retired because it could repeat billable Run-creation
POSTs after an ambiguous failure. Running `go run batch_csv.go` now prints a deprecation message,
returns exit code 2, and does not read credentials or create Runs. The old `single_url.go` entry
was replaced by `cmd/single-url`; migrate to `go run ./cmd/single-url <explicit-URL>` or import the
Client. Do not use the retired CSV entry for batch work. No Go CSV Batch replacement is included in
this MVP.
