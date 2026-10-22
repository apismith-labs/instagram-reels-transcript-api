package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/apismith-labs/instagram-reels-transcript-api/examples/go/transcriptapi"
)

type dependencies struct {
	getenv      func(string) string
	stdout      io.Writer
	stderr      io.Writer
	transport   transcriptapi.HTTPDoer
	journal     transcriptapi.Journal
	writeResult func(string, transcriptapi.Result, time.Time) (string, error)
	now         func() time.Time
}

type cliOutput struct {
	transcriptapi.Result
	OutputFile string `json:"outputFile,omitempty"`
}

func main() {
	os.Exit(run(os.Args[1:], dependencies{getenv: os.Getenv, stdout: os.Stdout, stderr: os.Stderr, now: time.Now}))
}

func run(args []string, deps dependencies) int {
	if deps.getenv == nil {
		deps.getenv = os.Getenv
	}
	if deps.stdout == nil {
		deps.stdout = io.Discard
	}
	if deps.stderr == nil {
		deps.stderr = io.Discard
	}
	if deps.now == nil {
		deps.now = time.Now
	}
	if deps.writeResult == nil {
		deps.writeResult = transcriptapi.WriteResultUnique
	}
	flags := flag.NewFlagSet("single-url", flag.ContinueOnError)
	flags.SetOutput(deps.stderr)
	outputDir := flags.String("output-dir", "sample-output/generated", "directory for unique private JSON output")
	journalPath := flags.String("journal", "", "append-only JSONL Journal path (defaults inside output-dir)")
	maxCharge := flags.String("max-total-charge-usd", "", "per-Run charge cap; may also be set with APIFY_MAX_TOTAL_CHARGE_USD")
	requireCapFlag := flags.Bool("require-charge-cap", false, "require a positive per-Run charge cap")
	flags.Usage = func() {
		fmt.Fprintln(deps.stderr, "Usage: single-url [options] https://www.instagram.com/reel/SHORTCODE/")
		flags.PrintDefaults()
	}
	if err := flags.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return 0
		}
		return cliError(deps.stderr, "invalid arguments", 2)
	}
	if len(flags.Args()) != 1 {
		flags.Usage()
		return cliError(deps.stderr, "exactly one explicit Instagram URL is required", 2)
	}
	validURL, err := transcriptapi.ValidateVideoURL(flags.Args()[0])
	if err != nil {
		return cliError(deps.stderr, err.Error(), 2)
	}

	// Credentials and environment configuration are read only after the explicit URL passes validation.
	token := strings.TrimSpace(deps.getenv("APIFY_TOKEN"))
	if token == "" {
		return cliError(deps.stderr, "APIFY_TOKEN is required in the process environment", 2)
	}
	actorID := strings.TrimSpace(deps.getenv("APIFY_ACTOR_ID"))
	if actorID == "" {
		actorID = transcriptapi.DefaultActorID
	}
	buildNumber := strings.TrimSpace(deps.getenv("APIFY_BUILD"))
	if buildNumber == "" {
		buildNumber = transcriptapi.ControlledBuildNumber
	}
	buildID := strings.TrimSpace(deps.getenv("APIFY_BUILD_ID"))
	if buildID == "" {
		buildID = transcriptapi.ControlledBuildID
	}
	requireCap := *requireCapFlag || deps.getenv("APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD") == "1"
	chargeRaw := strings.TrimSpace(*maxCharge)
	if chargeRaw == "" {
		chargeRaw = strings.TrimSpace(deps.getenv("APIFY_MAX_TOTAL_CHARGE_USD"))
	}
	var charge float64
	if chargeRaw != "" {
		charge, err = strconv.ParseFloat(chargeRaw, 64)
		if err != nil || charge <= 0 || math.IsNaN(charge) || math.IsInf(charge, 0) {
			return cliError(deps.stderr, "APIFY_MAX_TOTAL_CHARGE_USD must be a finite positive number", 2)
		}
	}
	if requireCap && chargeRaw == "" {
		return cliError(deps.stderr, "a charge cap is required before creating a Run", 2)
	}

	journal := deps.journal
	var fileJournal *transcriptapi.JSONLJournal
	if journal == nil {
		path := *journalPath
		if path == "" {
			path = strings.TrimRight(*outputDir, "/\\") + string(os.PathSeparator) + "go-run-journal.jsonl"
		}
		fileJournal, err = transcriptapi.OpenJSONLJournal(path)
		if err != nil {
			return cliError(deps.stderr, "cannot open private Run Journal: "+err.Error(), 8)
		}
		defer fileJournal.Close()
		journal = fileJournal
	}
	config := transcriptapi.Config{Token: token, ActorID: actorID, BuildNumber: buildNumber, BuildID: buildID,
		MaxTotalChargeUSD: charge, RequireChargeCap: requireCap, HTTPClient: deps.transport, Journal: journal}
	client, err := transcriptapi.NewClient(config)
	if err != nil {
		return cliError(deps.stderr, err.Error(), 2)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	result := client.GetTranscript(ctx, validURL)
	writePath, writeErr := deps.writeResult(*outputDir, result, deps.now())
	if writeErr != nil {
		result.Status = transcriptapi.StatusTransportError
		result.Stage = "output_write"
		result.Error = "Run result is available in memory but output persistence failed"
		writePath = ""
	}
	encoded, _ := json.Marshal(cliOutput{Result: result, OutputFile: writePath})
	fmt.Fprintln(deps.stdout, string(encoded))
	if writeErr != nil {
		fmt.Fprintln(deps.stderr, "cannot persist result file:", writeErr)
		return 8
	}
	return transcriptapi.ExitCode(result.Status)
}

func cliError(writer io.Writer, message string, code int) int {
	fmt.Fprintln(writer, message)
	return code
}
