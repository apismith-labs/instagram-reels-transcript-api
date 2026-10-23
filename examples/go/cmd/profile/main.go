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
	flags := flag.NewFlagSet("profile", flag.ContinueOnError)
	flags.SetOutput(stderr)
	limit := flags.Int("results-limit", 0, "optional Profile resultsLimit")
	newer := flags.String("only-posts-newer-than", "", "optional YYYY-MM-DD or relative period")
	skipPinned := flags.Bool("skip-pinned-posts", false, "skip pinned posts")
	includeShares := flags.Bool("include-shares-count", false, "include shares count")
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
	request := transcriptapi.ProfileRequest{Usernames: flags.Args(), OnlyPostsNewerThan: *newer}
	visited := map[string]bool{}
	flags.Visit(func(item *flag.Flag) { visited[item.Name] = true })
	if visited["only-posts-newer-than"] && strings.TrimSpace(*newer) == "" {
		fmt.Fprintln(stderr, "--only-posts-newer-than requires a non-empty date or relative period")
		return 2
	}
	if visited["results-limit"] {
		request.ResultsLimit = limit
	}
	if visited["skip-pinned-posts"] {
		request.SkipPinnedPosts = skipPinned
	}
	if visited["include-shares-count"] {
		request.IncludeSharesCount = includeShares
	}
	if _, err := transcriptapi.ValidateProfileRequest(request); err != nil {
		fmt.Fprintln(stderr, err)
		return 2
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
	var err error
	if chargeRaw != "" {
		charge, err = strconv.ParseFloat(chargeRaw, 64)
		if err != nil || charge <= 0 || math.IsInf(charge, 0) || math.IsNaN(charge) {
			fmt.Fprintln(stderr, "charge cap must be a finite positive number")
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
		file, openErr := transcriptapi.OpenJSONLJournal(*journalPath)
		if openErr != nil {
			fmt.Fprintln(stderr, "cannot open Journal:", openErr)
			return 8
		}
		defer file.Close()
		journal = file
	}
	client, err := transcriptapi.NewClient(transcriptapi.Config{Token: token, ActorID: getenv("APIFY_ACTOR_ID"), BuildNumber: getenv("APIFY_BUILD"), BuildID: getenv("APIFY_BUILD_ID"), MaxTotalChargeUSD: charge, RequireChargeCap: require, HTTPClient: transport, Journal: journal})
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 2
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	result := client.GetProfilePosts(ctx, request)
	path, err := transcriptapi.WriteJSONUnique(*outputDir, "go-profile", result, time.Now())
	if err != nil {
		fmt.Fprintln(stderr, "cannot persist Profile result:", err)
		return 8
	}
	encoded, _ := json.Marshal(struct {
		transcriptapi.ProfileResult
		OutputFile string `json:"outputFile"`
	}{result, path})
	fmt.Fprintln(stdout, string(encoded))
	return transcriptapi.ProfileExitCode(result)
}
