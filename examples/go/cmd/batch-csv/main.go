package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/apismith-labs/instagram-reels-transcript-api/examples/go/transcriptapi"
)

func main() { os.Exit(run(os.Args[1:], os.Getenv, os.Stdout, os.Stderr, nil, nil)) }

func run(args []string, getenv func(string) string, stdout, stderr io.Writer, transport *http.Client, journal transcriptapi.Journal) int {
	if getenv == nil {
		getenv = os.Getenv
	}
	if stdout == nil {
		stdout = io.Discard
	}
	if stderr == nil {
		stderr = io.Discard
	}
	flags := flag.NewFlagSet("batch-csv", flag.ContinueOnError)
	flags.SetOutput(stderr)
	dryRun := flags.Bool("dry-run", false, "validate and plan without reading credentials or creating Runs")
	execute := flags.Bool("execute", false, "explicitly allow one independent Run per CSV row")
	outputDir := flags.String("output-dir", "sample-output/generated", "unique JSON output directory")
	journalPath := flags.String("journal", "", "JSONL Journal path")
	maxCharge := flags.String("max-total-charge-usd", "", "per-Run charge cap")
	requireFlag := flags.Bool("require-charge-cap", false, "require a positive per-Run charge cap")
	if err := flags.Parse(args); err != nil {
		if err == flag.ErrHelp {
			return 0
		}
		return 2
	}
	if len(flags.Args()) != 1 || (*dryRun && *execute) {
		fmt.Fprintln(stderr, "usage: batch-csv [--dry-run | --execute] [options] FILE.csv")
		return 2
	}
	file, err := os.Open(flags.Args()[0])
	if err != nil {
		fmt.Fprintln(stderr, "cannot open CSV:", err)
		return 2
	}
	rows, parseErr := transcriptapi.ReadCSVBatch(file)
	closeErr := file.Close()
	if parseErr != nil {
		fmt.Fprintln(stderr, parseErr)
		return 2
	}
	if closeErr != nil {
		fmt.Fprintln(stderr, "cannot close CSV:", closeErr)
		return 2
	}
	if len(rows) == 0 {
		fmt.Fprintln(stdout, `{"status":"empty","rowCount":0,"maximumRuns":0}`)
		return 0
	}
	if *dryRun || !*execute {
		encoded, _ := json.Marshal(map[string]any{"status": "dry_run", "mode": "csv_batch", "runMode": "one_independent_run_per_row", "rowCount": len(rows), "maximumRuns": len(rows), "concurrency": 1, "executeRequired": true, "rows": rows})
		fmt.Fprintln(stdout, string(encoded))
		return 0
	}
	token := strings.TrimSpace(getenv("APIFY_TOKEN"))
	if token == "" {
		fmt.Fprintln(stderr, "APIFY_TOKEN is required")
		return 2
	}
	chargeRaw := strings.TrimSpace(*maxCharge)
	if chargeRaw == "" {
		chargeRaw = strings.TrimSpace(getenv("APIFY_MAX_TOTAL_CHARGE_USD"))
	}
	var charge float64
	if chargeRaw != "" {
		charge, err = strconv.ParseFloat(chargeRaw, 64)
		if err != nil || charge <= 0 || math.IsNaN(charge) || math.IsInf(charge, 0) {
			fmt.Fprintln(stderr, "charge cap must be finite and positive")
			return 2
		}
	}
	require := *requireFlag || getenv("APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD") == "1"
	if require && charge == 0 {
		fmt.Fprintln(stderr, "required charge cap is missing")
		return 2
	}
	if journal == nil {
		if *journalPath == "" {
			*journalPath = strings.TrimRight(*outputDir, "/\\") + string(os.PathSeparator) + "go-run-journal.jsonl"
		}
		diskJournal, openErr := transcriptapi.OpenJSONLJournal(*journalPath)
		if openErr != nil {
			fmt.Fprintln(stderr, "cannot open Journal:", openErr)
			return 8
		}
		defer diskJournal.Close()
		journal = diskJournal
	}
	client, err := transcriptapi.NewClient(transcriptapi.Config{Token: token, ActorID: getenv("APIFY_ACTOR_ID"), BuildNumber: getenv("APIFY_BUILD"), BuildID: getenv("APIFY_BUILD_ID"), MaxTotalChargeUSD: charge, RequireChargeCap: require, HTTPClient: transport, Journal: journal})
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 2
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(len(rows))*10*time.Minute)
	defer cancel()
	result := client.GetTranscriptsFromCSV(ctx, rows)
	path, err := transcriptapi.WriteJSONUnique(*outputDir, "go-csv-batch", result, time.Now())
	if err != nil {
		fmt.Fprintln(stderr, "cannot persist CSV result:", err)
		return 8
	}
	encoded, _ := json.Marshal(struct {
		transcriptapi.CSVBatchResult
		OutputFile string `json:"outputFile"`
	}{result, path})
	fmt.Fprintln(stdout, string(encoded))
	return transcriptapi.CSVBatchExitCode(result)
}
