package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/joho/godotenv"
)

const (
	defaultActorID = "apple_yang/instagram-transcripts-scraper"
	apiBaseURL     = "https://api.apify.com/v2"
)

type apiResponse struct {
	Data runInfo `json:"data"`
}

type runInfo struct {
	ID               string `json:"id"`
	Status           string `json:"status"`
	DefaultDatasetID string `json:"defaultDatasetId"`
}

func main() {
	if err := runSingle(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func runSingle() error {
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
	_ = envOrDefault("MAX_CONCURRENCY", "3")
	reelURL := os.Getenv("INSTAGRAM_REEL_URL")
	if len(os.Args) > 1 {
		reelURL = os.Args[1]
	}
	if strings.TrimSpace(reelURL) == "" {
		return errors.New("Error: INSTAGRAM_REEL_URL is required. Set it in .env or pass it as a CLI argument.")
	}

	fmt.Println("Actor ID:", actorID)
	fmt.Println("Running request...")

	client := &http.Client{Timeout: 10 * time.Minute}
	run, err := startActorRun(client, token, actorID, reelURL, sessionID)
	if err != nil {
		return err
	}
	if run.ID == "" {
		return errors.New("Error: Actor run response did not include an id.")
	}

	finishedRun, err := waitForRun(client, token, run.ID)
	if err != nil {
		return err
	}
	if finishedRun.Status != "SUCCEEDED" {
		return fmt.Errorf("Error: Actor run finished with status %s.", finishedRun.Status)
	}
	if finishedRun.DefaultDatasetID == "" {
		return errors.New("Error: Actor run completed without a defaultDatasetId.")
	}

	items, rawItems, err := fetchDatasetItems(client, token, finishedRun.DefaultDatasetID)
	if err != nil {
		return err
	}

	outputDir := filepath.Join(repoRoot, "sample-output", "generated")
	outputFile := filepath.Join(outputDir, "go-single-url-response.json")
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return err
	}
	if err := os.WriteFile(outputFile, append(rawItems, '\n'), 0o644); err != nil {
		return err
	}

	text := firstString(items, "text")
	segments := firstSlice(items, "segments")
	errMsg := firstString(items, "errMsg")

	fmt.Println("Output path:", outputFile)
	fmt.Println("Items:", len(items))
	fmt.Println("Transcript characters:", len(text))
	fmt.Println("Segments:", len(segments))
	if errMsg != "" {
		fmt.Println("errMsg:", errMsg)
	}

	return nil
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
	return runInfo{}, errors.New("Error: Timed out waiting for Actor run to finish.")
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
