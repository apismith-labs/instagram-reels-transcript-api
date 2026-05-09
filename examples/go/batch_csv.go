package main

import (
	"bytes"
	"encoding/csv"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/joho/godotenv"
)

const (
	defaultActorID = "apple_yang/instagram-transcripts-scraper"
	apiBaseURL     = "https://api.apify.com/v2"
	maxRetries     = 2
)

type apiResponse struct {
	Data runInfo `json:"data"`
}

type runInfo struct {
	ID               string `json:"id"`
	Status           string `json:"status"`
	DefaultDatasetID string `json:"defaultDatasetId"`
}

type batchResult struct {
	SourceURL string           `json:"sourceUrl"`
	Status    string           `json:"status"`
	ItemCount int              `json:"itemCount"`
	Text      string           `json:"text"`
	Segments  []any            `json:"segments"`
	ErrMsg    string           `json:"errMsg"`
	RawItems  []map[string]any `json:"rawItems"`
}

type batchError struct {
	SourceURL string
	Error     string
}

func main() {
	if err := runBatch(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func runBatch() error {
	repoRoot, err := findRepoRoot()
	if err != nil {
		return err
	}
	_ = godotenv.Load(filepath.Join(repoRoot, ".env"))

	token, err := requireEnv("APIFY_TOKEN")
	if err != nil {
		return err
	}
	actorID := envOrDefault("APIFY_ACTOR_ID", defaultActorID)
	sessionID := os.Getenv("INSTAGRAM_SESSIONID")
	maxConcurrency, err := parseMaxConcurrency(envOrDefault("MAX_CONCURRENCY", "3"))
	if err != nil {
		return err
	}
	csvPath := filepath.Join(repoRoot, "sample-data", "instagram-reel-urls.csv")
	if len(os.Args) > 1 {
		csvPath = os.Args[1]
		if !filepath.IsAbs(csvPath) {
			abs, err := filepath.Abs(csvPath)
			if err != nil {
				return err
			}
			csvPath = abs
		}
	}

	urls, err := readURLs(csvPath)
	if err != nil {
		return err
	}
	if len(urls) == 0 {
		return errors.New("Error: CSV does not contain any videoUrl values.")
	}

	fmt.Println("Actor ID:", actorID)
	fmt.Println("Total URLs:", len(urls))
	fmt.Println("Max concurrency:", maxConcurrency)
	// Higher concurrency may increase Apify usage cost and rate-limit risk.

	client := &http.Client{Timeout: 10 * time.Minute}
	jobs := make(chan string)
	results := make([]batchResult, 0)
	failures := make([]batchError, 0)
	var mu sync.Mutex
	var processed int64
	var success int64
	var failed int64
	var wg sync.WaitGroup

	for worker := 0; worker < maxConcurrency; worker++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for videoURL := range jobs {
				result, err := processURL(client, token, actorID, videoURL, sessionID)
				mu.Lock()
				if err != nil {
					failures = append(failures, batchError{SourceURL: videoURL, Error: err.Error()})
					atomic.AddInt64(&failed, 1)
				} else {
					results = append(results, result)
					atomic.AddInt64(&success, 1)
				}
				done := atomic.AddInt64(&processed, 1)
				fmt.Printf("Progress: total=%d processed=%d success=%d failed=%d\n", len(urls), done, atomic.LoadInt64(&success), atomic.LoadInt64(&failed))
				mu.Unlock()
			}
		}()
	}

	for _, videoURL := range urls {
		jobs <- videoURL
	}
	close(jobs)
	wg.Wait()

	outputDir := filepath.Join(repoRoot, "sample-output", "generated")
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return err
	}
	resultsPath := filepath.Join(outputDir, "go-batch-results.jsonl")
	errorsPath := filepath.Join(outputDir, "go-batch-errors.csv")
	if err := writeJSONL(resultsPath, results); err != nil {
		return err
	}
	if err := writeErrorsCSV(errorsPath, failures); err != nil {
		return err
	}

	fmt.Println("Results path:", resultsPath)
	fmt.Println("Errors path:", errorsPath)
	return nil
}

func processURL(client *http.Client, token, actorID, videoURL, sessionID string) (batchResult, error) {
	var lastErr error
	for attempt := 0; attempt <= maxRetries; attempt++ {
		items, _, err := callActorOnce(client, token, actorID, videoURL, sessionID)
		if err == nil {
			return buildResult(videoURL, items), nil
		}
		lastErr = err
		if attempt < maxRetries {
			time.Sleep(time.Duration(1<<attempt) * time.Second)
		}
	}
	return batchResult{}, lastErr
}

func callActorOnce(client *http.Client, token, actorID, videoURL, sessionID string) ([]map[string]any, []byte, error) {
	run, err := startActorRun(client, token, actorID, videoURL, sessionID)
	if err != nil {
		return nil, nil, err
	}
	if run.ID == "" {
		return nil, nil, errors.New("Actor run response did not include an id.")
	}
	finishedRun, err := waitForRun(client, token, run.ID)
	if err != nil {
		return nil, nil, err
	}
	if finishedRun.Status != "SUCCEEDED" {
		return nil, nil, fmt.Errorf("Actor run finished with status %s.", finishedRun.Status)
	}
	if finishedRun.DefaultDatasetID == "" {
		return nil, nil, errors.New("Actor run completed without a defaultDatasetId.")
	}
	return fetchDatasetItems(client, token, finishedRun.DefaultDatasetID)
}

func buildResult(sourceURL string, items []map[string]any) batchResult {
	text := firstString(items, "text")
	segments := firstSlice(items, "segments")
	errMsg := firstString(items, "errMsg")
	status := "success"
	if errMsg != "" {
		status = "actor_error"
	} else if len(items) == 0 {
		status = "empty"
	}
	return batchResult{
		SourceURL: sourceURL,
		Status:    status,
		ItemCount: len(items),
		Text:      text,
		Segments:  segments,
		ErrMsg:    errMsg,
		RawItems:  items,
	}
}

func startActorRun(client *http.Client, token, actorID, reelURL, sessionID string) (runInfo, error) {
	body, err := json.Marshal(map[string]string{
		"videoUrl":  reelURL,
		"sessionid": sessionID,
	})
	if err != nil {
		return runInfo{}, err
	}
	actorIDForURL := strings.ReplaceAll(actorID, "/", "~")
	url := fmt.Sprintf("%s/acts/%s/runs", apiBaseURL, actorIDForURL)

	var response apiResponse
	if err := doJSON(client, token, http.MethodPost, url, body, &response); err != nil {
		return runInfo{}, err
	}
	return response.Data, nil
}

func waitForRun(client *http.Client, token, runID string) (runInfo, error) {
	for attempt := 0; attempt < 150; attempt++ {
		url := fmt.Sprintf("%s/actor-runs/%s", apiBaseURL, runID)
		var response apiResponse
		if err := doJSON(client, token, http.MethodGet, url, nil, &response); err != nil {
			return runInfo{}, err
		}
		switch response.Data.Status {
		case "SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED":
			return response.Data, nil
		}
		time.Sleep(2 * time.Second)
	}
	return runInfo{}, errors.New("Timed out waiting for Actor run to finish.")
}

func fetchDatasetItems(client *http.Client, token, datasetID string) ([]map[string]any, []byte, error) {
	url := fmt.Sprintf("%s/datasets/%s/items", apiBaseURL, datasetID)
	raw, err := doRaw(client, token, http.MethodGet, url, nil)
	if err != nil {
		return nil, nil, err
	}
	var items []map[string]any
	if len(bytes.TrimSpace(raw)) > 0 {
		if err := json.Unmarshal(raw, &items); err != nil {
			return nil, nil, err
		}
	}
	if items == nil {
		items = []map[string]any{}
	}
	pretty, err := json.MarshalIndent(items, "", "  ")
	if err != nil {
		return nil, nil, err
	}
	return items, pretty, nil
}

func doJSON(client *http.Client, token, method, url string, body []byte, target any) error {
	raw, err := doRaw(client, token, method, url, body)
	if err != nil {
		return err
	}
	if len(bytes.TrimSpace(raw)) == 0 {
		return nil
	}
	return json.Unmarshal(raw, target)
}

func doRaw(client *http.Client, token, method, url string, body []byte) ([]byte, error) {
	var reader io.Reader
	if body != nil {
		reader = bytes.NewReader(body)
	}
	request, err := http.NewRequest(method, url, reader)
	if err != nil {
		return nil, err
	}
	request.Header.Set("Authorization", "Bearer "+token)
	request.Header.Set("Content-Type", "application/json")

	response, err := client.Do(request)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()

	raw, err := io.ReadAll(response.Body)
	if err != nil {
		return nil, err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return nil, fmt.Errorf("HTTP %d from Apify API: %s", response.StatusCode, string(raw))
	}
	return raw, nil
}

func readURLs(csvPath string) ([]string, error) {
	file, err := os.Open(csvPath)
	if err != nil {
		return nil, fmt.Errorf("Error: CSV file not found: %s", csvPath)
	}
	defer file.Close()

	reader := csv.NewReader(file)
	records, err := reader.ReadAll()
	if err != nil {
		return nil, err
	}
	if len(records) == 0 {
		return nil, errors.New("Error: CSV is empty.")
	}
	videoURLIndex := -1
	for index, header := range records[0] {
		if strings.TrimSpace(header) == "videoUrl" {
			videoURLIndex = index
			break
		}
	}
	if videoURLIndex == -1 {
		return nil, errors.New("Error: CSV must include a videoUrl column.")
	}

	urls := make([]string, 0, len(records)-1)
	for _, record := range records[1:] {
		if videoURLIndex < len(record) {
			value := strings.TrimSpace(record[videoURLIndex])
			if value != "" {
				urls = append(urls, value)
			}
		}
	}
	return urls, nil
}

func writeJSONL(path string, results []batchResult) error {
	var builder strings.Builder
	for _, result := range results {
		line, err := json.Marshal(result)
		if err != nil {
			return err
		}
		builder.Write(line)
		builder.WriteByte('\n')
	}
	return os.WriteFile(path, []byte(builder.String()), 0o644)
}

func writeErrorsCSV(path string, failures []batchError) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()

	if err := writer.Write([]string{"sourceUrl", "error"}); err != nil {
		return err
	}
	for _, failure := range failures {
		if err := writer.Write([]string{failure.SourceURL, failure.Error}); err != nil {
			return err
		}
	}
	return writer.Error()
}

func firstString(items []map[string]any, field string) string {
	for _, item := range items {
		if value, ok := item[field].(string); ok && value != "" {
			return value
		}
	}
	return ""
}

func firstSlice(items []map[string]any, field string) []any {
	for _, item := range items {
		if value, ok := item[field].([]any); ok {
			return value
		}
	}
	return []any{}
}

func requireEnv(name string) (string, error) {
	value := strings.TrimSpace(os.Getenv(name))
	if value == "" {
		return "", fmt.Errorf("Error: %s is required. Set it in .env or your environment.", name)
	}
	return value, nil
}

func envOrDefault(name, defaultValue string) string {
	value := strings.TrimSpace(os.Getenv(name))
	if value == "" {
		return defaultValue
	}
	return value
}

func parseMaxConcurrency(rawValue string) (int, error) {
	value, err := strconv.Atoi(rawValue)
	if err != nil {
		return 0, errors.New("Error: MAX_CONCURRENCY must be an integer.")
	}
	if value < 1 {
		return 0, errors.New("Error: MAX_CONCURRENCY must be at least 1.")
	}
	return value, nil
}

func findRepoRoot() (string, error) {
	current, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		if fileExists(filepath.Join(current, ".env.example")) && fileExists(filepath.Join(current, "sample-data")) {
			return current, nil
		}
		parent := filepath.Dir(current)
		if parent == current {
			break
		}
		current = parent
	}
	return "", errors.New("Error: Could not locate repository root.")
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
