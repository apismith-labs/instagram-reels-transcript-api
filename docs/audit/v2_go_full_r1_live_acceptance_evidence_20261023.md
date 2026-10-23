# V2-GO-FULL-R1 — Live Acceptance Evidence

Date: 2026-10-23
Repository: `apismith-labs/instagram-reels-transcript-api`
Evidence scope: local saved outputs, JSONL Journals, prior accepted reports, and the supplied
read-only service evidence. No Actor or Apify API request was made while preparing this report.

## Release baseline

- Branch / HEAD / `origin/main`: `main` / `43e1ff5999503de6e9ec51f68442ad2c717b7842`.
- Root and nested `v0.8.0` tags resolve to `f64e41492c3e3939b4fe566022b02f4bda79a507`.
- `v0.7.0` resolves to `7b933b33cd6b2f6752f3e2e39838391448b5ebdb`.
- Controlled Actor: `S9A11NvceWaGorwwh`; Build `0.0.50`, ID `aJLRmMdQapLQRT4sJ`.
- Existing CI evidence on the baseline: Go 1.22 Run `39894754948` SUCCESS; Python/Node Run
  `39894754697` SUCCESS, 11 jobs.

## Mode evidence

| Mode | Run / Dataset | Saved evidence | Result and evidence limits |
|---|---|---|---|
| Single URL (v0.8.0 evidence) | `KImzl8HbVkTRA0dWG` / `Oi5drQ8byuKikWyJ0` | `sample-output/generated/go-single-url-20261022T140137.659444000Z-0.json`; `sample-output/generated/go-live-20261022T140118Z.jsonl` | `SUCCEEDED`; Build and URL attribution verified; complete Dataset; 15 segments. Previously recorded usage: `$0.0055`. This is historical Single URL evidence, not a new v0.9.0 Run. The old Journal lacks `runActorId` and `inputContext`, so it cannot qualify for current Single Resume. |
| Native Bulk | `WkjbQbLb3Kia5NTl5` / `HAp6Gi4h2Uh2K8Zaj` | `sample-output/generated/go-native-bulk-20261023T034323.531450000Z-0.json`; `sample-output/generated/go-full-l1-native-bulk-journal.jsonl` | `SUCCEEDED`, `all_success`, Build verified, Dataset complete; 3/3 URL attributions verified; segment counts 15/14/12; extras 0. Journal records intent, Run creation, and terminal outcomes. Two terminal records refer to the same Run. No packet-level HTTP capture is available, so the Journal is not proof of an exact POST count. |
| Native Bulk Resume | same Run / Dataset | `sample-output/generated/go-native-bulk-20261023T034630.292030000Z-0.json`; same Bulk Journal | Restored the same Run and Dataset with 3/3 successful attributed items and matching segment counts. The saved evidence contains no additional Run identity; the implementation and offline probes establish GET-only Resume behavior. The terminal evidence does not include a packet-level HTTP trace. |
| Profile | `AwCi7bmqPsA5OK1V5` / `kXhRAg7teW1hihHZZ` | `sample-output/generated/go-profile-20261023T034836.761282000Z-0.json`; `sample-output/generated/go-full-l1-profile-journal.jsonl` | `SUCCEEDED`, Build verified, Dataset complete; one post for `lovepegz`, type Video, `ownerUsername=lovepegz`. Profile metadata was retained; transcript fields were not required. This does not validate multiple accounts or pagination. |
| CSV Dry-run | no Run / no Dataset | `sample-output/live-acceptance-inputs/go-full-l1/one-row.csv`; dry-run result was recorded in the preceding local acceptance session | `dry_run`; one row, maximumRuns 1, per-Run cap `$0.10`, arithmetic cap estimate `$0.10`; zero credential reads, POSTs, Journal writes, or Actor Runs. |
| CSV Live | `bRmoKcKn0LHooIfke` / `rtuVkX5mWCPNgflK6` | `sample-output/generated/go-csv-batch-20261023T035019.696233000Z-0.json`; `sample-output/generated/go-full-l1-csv-journal.jsonl` | One data row (CSV line 2) succeeded; transcript non-empty, 15 segments; planned 1, unattempted 0, failed 0. Journal records intent, Run creation, and success, including Actor/Build/Run identity and cap settings. The CSV JSON does not expose `datasetComplete`; completeness is not independently established by that aggregate. |
| Single Resume | not run | Historical Single Journal above | Offline-tested only. No dedicated Live acceptance was performed because the historical Journal lacks fields required by the current Resume contract. |

The three R1 Live creation Runs evidenced here are Native Bulk, Profile, and one CSV row. The
Bulk Resume reused its existing Run. Per-Run requested cap was `$0.10` where recorded, giving a
`$0.30` arithmetic sum for those three runs; this is not a charge forecast or invoice ceiling.
Actual usage for these three Runs was not independently verified in the saved local evidence.

## Safety and release boundaries

- Saved outputs are referenced by path only; this report excludes full transcript text, complete
  raw Actor items, signed CDN URLs, and authorization headers.
- `.env` contents and credential values were not read. No credential values are stored here.
- Existing generated outputs and Journals were read-only and remain in the ignored generated
  directory.
- A matching Run ID in a Journal is not a packet-level proof of exactly one creation POST. The
  code and offline tests establish that Resume uses GET and does not create a replacement Run.
- One controlled acceptance per new mode does not establish arbitrary input cardinality, mixed
  failure behavior, multi-account Profile attribution, multi-row CSV execution, generalized
  pagination, or long-term production reliability.
- The Go CSV aggregate does not expose `datasetComplete`; do not infer complete pagination from
  `status=all_success` alone.
- The `$0.10` cap is a per-Run platform option and does not guarantee the final account bill.

## Counts and conclusion

- New R1 Actor Runs evidenced: 3 (Native Bulk, Profile, CSV); Bulk Resume: 0 additional Run.
- CSV Dry-run Actor Runs: 0.
- Apify API requests made while compiling this report: 0.
- Source or test changes: 0.
- Evidence supports narrow Live acceptance of Native Bulk, Bulk Resume against the same Run,
  single-account Profile, and one-row CSV. Single Resume remains offline-tested only.

## Offline release-preparation gates

Executed locally without real credentials or network-backed Actor calls:

- Go 1.27.3: `go test ./... -count=1` passed; the repository test gate reported 103 executions,
  103 passed, 0 skipped, 0 failed. Gate self-tests passed.
- `go vet ./...`, `go build ./...`, gofmt check, and Windows/Linux amd64 cross-builds passed.
- Python offline suite: 112 passed, 0 failed; Python source compilation passed.
- Node.js offline CI wrapper: 107 passed, 0 failed, skipped, cancelled, or TODO; its minimum gate
  remains 96.
- Markdown fence/link and `git diff --check` checks passed for the release documents.

Cloud evidence is historical for the fixed baseline and was not rerun: Go 1.22 Run `39894754948`
and Python/Node Run `39894754697` are recorded as successful in the accepted project evidence.
