package transcriptapi

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

const defaultAPIBaseURL = "https://api.apify.com/v2"

type Client struct {
	config Config
	client HTTPDoer
	base   string
	sleep  func(context.Context, time.Duration) error
	now    func() time.Time
}

type apiEnvelope struct {
	Data runMetadata `json:"data"`
}

type runMetadata struct {
	ID               string `json:"id"`
	Status           string `json:"status"`
	DefaultDatasetID string `json:"defaultDatasetId"`
	BuildNumber      string `json:"buildNumber"`
	BuildID          string `json:"buildId"`
}

type apiHTTPError struct{ StatusCode int }

func (e *apiHTTPError) Error() string { return fmt.Sprintf("Apify API returned HTTP %d", e.StatusCode) }

// NewClient validates configuration without reading environment variables or performing I/O.
func NewClient(config Config) (*Client, error) {
	if strings.TrimSpace(config.Token) == "" {
		return nil, &Error{Kind: ErrorConfiguration, Stage: "config", Err: errors.New("Token is required")}
	}
	if config.ActorID == "" {
		config.ActorID = DefaultActorID
	}
	if strings.TrimSpace(config.ActorID) != config.ActorID || strings.ContainsAny(config.ActorID, "?#") {
		return nil, &Error{Kind: ErrorConfiguration, Stage: "config", Err: errors.New("Actor ID is invalid")}
	}
	if config.BuildNumber == "" {
		config.BuildNumber = ControlledBuildNumber
	}
	if config.BuildID == "" {
		config.BuildID = ControlledBuildID
	}
	if config.BuildNumber != ControlledBuildNumber || config.BuildID != ControlledBuildID {
		return nil, &Error{Kind: ErrorConfiguration, Stage: "config", Err: errors.New("only the controlled Build 0.0.50 / aJLRmMdQapLQRT4sJ is accepted")}
	}
	if config.RequireChargeCap && (!finitePositive(config.MaxTotalChargeUSD)) {
		return nil, &Error{Kind: ErrorConfiguration, Stage: "config", Err: errors.New("a finite positive MaxTotalChargeUSD is required")}
	}
	if !config.RequireChargeCap && config.MaxTotalChargeUSD != 0 && !finitePositive(config.MaxTotalChargeUSD) {
		return nil, &Error{Kind: ErrorConfiguration, Stage: "config", Err: errors.New("MaxTotalChargeUSD must be finite and positive when supplied")}
	}
	if config.Journal == nil {
		return nil, &Error{Kind: ErrorConfiguration, Stage: "config", Err: ErrNoJournal}
	}
	if config.HTTPClient == nil {
		config.HTTPClient = &http.Client{Timeout: 30 * time.Second}
	}
	if config.PollInterval <= 0 {
		config.PollInterval = 2 * time.Second
	}
	if config.MaxPolls <= 0 {
		config.MaxPolls = 150
	}
	if config.DatasetLimit <= 0 {
		config.DatasetLimit = DefaultDatasetLimit
	}
	base := defaultAPIBaseURL
	sleep := config.Sleep
	if sleep == nil {
		sleep = sleepContext
	}
	now := config.Now
	if now == nil {
		now = time.Now
	}
	return &Client{config: config, client: config.HTTPClient, base: base, sleep: sleep, now: now}, nil
}

func finitePositive(value float64) bool {
	return value > 0 && !math.IsInf(value, 0) && !math.IsNaN(value)
}

func capValue(value float64) *float64 {
	if value <= 0 {
		return nil
	}
	return &value
}

func sleepContext(ctx context.Context, duration time.Duration) error {
	timer := time.NewTimer(duration)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

// GetTranscript creates at most one Run. It never retries the Run-creation POST.
func (c *Client) GetTranscript(ctx context.Context, reelURL string) Result {
	validURL, err := ValidateVideoURL(reelURL)
	if err != nil {
		return c.failure(StatusTransportError, "input_validation", reelURL, "", "", "", c.config.BuildNumber, c.config.BuildID, "unverified", err)
	}
	result := Result{ActorID: c.config.ActorID, BuildNumber: c.config.BuildNumber, BuildID: c.config.BuildID,
		SourceURL: validURL, BuildVerification: "pending", Segments: []Segment{}, RawItems: []map[string]any{}}
	entry := c.journalEntry("intent", validURL, "", "", "", c.config.BuildNumber, c.config.BuildID, "pending", capValue(c.config.MaxTotalChargeUSD))
	if err := c.config.Journal.Append(ctx, entry); err != nil {
		return c.failure(StatusTransportError, "journal_intent", validURL, "", "", "", "", "", "", &Error{Kind: ErrorJournal, Stage: "journal_intent", Err: err})
	}

	postURL, err := c.runCreateURL()
	if err != nil {
		return c.failure(StatusTransportError, "run_create_prepare", validURL, "", "", "", "", "", "", err)
	}
	body, _ := json.Marshal(map[string]string{"videoUrl": validURL})
	query := url.Values{}
	query.Set("build", c.config.BuildNumber)
	query.Set("restartOnError", "false")
	if c.config.MaxTotalChargeUSD > 0 {
		query.Set("maxTotalChargeUsd", strconv.FormatFloat(c.config.MaxTotalChargeUSD, 'f', -1, 64))
	}
	createdRaw, _, postErr := c.request(ctx, http.MethodPost, postURL+"?"+query.Encode(), body)
	if postErr != nil {
		status := StatusCreationUnknown
		var apiErr *apiHTTPError
		if errors.As(postErr, &apiErr) && apiErr.StatusCode >= 400 && apiErr.StatusCode < 500 && apiErr.StatusCode != http.StatusTooManyRequests {
			status = StatusTransportError
		}
		stage := "run_create_unknown"
		if status == StatusTransportError {
			stage = "run_create_rejected"
		}
		journalErr := c.config.Journal.Append(ctx, c.journalEntry(stage, validURL, "", "", "", c.config.BuildNumber, c.config.BuildID, "unknown", capValue(c.config.MaxTotalChargeUSD)))
		result.Status, result.Stage, result.Error = status, stage, postErr.Error()
		kind := ErrorCreation
		if status == StatusTransportError {
			kind = ErrorTransport
		}
		result.Cause = &Error{Kind: kind, Stage: stage, Err: postErr}
		if journalErr != nil {
			result.Status, result.Stage, result.Error = StatusCreationUnknown, "journal_creation_unknown", "Run creation outcome is unknown and the Journal update failed"
			result.Cause = &Error{Kind: ErrorJournal, Stage: "journal_creation_unknown", Err: journalErr}
		}
		return result
	}
	var created apiEnvelope
	if err := json.Unmarshal(createdRaw, &created); err != nil || created.Data.ID == "" {
		message := errors.New("Run creation response did not provide a verifiable Run ID")
		journalErr := c.config.Journal.Append(ctx, c.journalEntry("run_create_unknown", validURL, "", "", "", "", "", "unknown", capValue(c.config.MaxTotalChargeUSD)))
		if journalErr != nil {
			message = errors.New("Run creation outcome is unknown and the Journal update failed")
		}
		return c.failure(StatusCreationUnknown, "run_create_unknown", validURL, "", "", "", "", "", "unknown", message)
	}
	result.RunID = created.Data.ID
	result.DatasetID = created.Data.DefaultDatasetID
	result.RunStatus = created.Data.Status
	result.BuildNumber = created.Data.BuildNumber
	result.BuildID = created.Data.BuildID
	if err := c.config.Journal.Append(ctx, c.journalEntry("run_created", validURL, result.RunID, result.DatasetID,
		result.RunStatus, result.BuildNumber, result.BuildID, "pending", capValue(c.config.MaxTotalChargeUSD))); err != nil {
		return c.failure(StatusTransportError, "journal_run_created", validURL, result.RunID, result.DatasetID, result.RunStatus,
			result.BuildNumber, result.BuildID, "unknown", &Error{Kind: ErrorJournal, Stage: "journal_run_created", Err: err})
	}

	finished, pollErr := c.waitForRun(ctx, result.RunID, created.Data)
	if pollErr != nil {
		return c.finishFailure(ctx, result, validURL, StatusTransportError, "run_poll", pollErr)
	}
	result.RunStatus = finished.Status
	result.BuildNumber = finished.BuildNumber
	result.BuildID = finished.BuildID
	if finished.Status != "SUCCEEDED" {
		result = c.finishFailureResult(ctx, result, validURL, StatusRunFailed, "run_terminal", fmt.Errorf("Actor Run finished with status %s", finished.Status))
		return result
	}
	if finished.BuildNumber != c.config.BuildNumber || finished.BuildID != c.config.BuildID {
		result.BuildVerification = "mismatch"
		return c.finishFailure(ctx, result, validURL, StatusTransportError, "build_mismatch", &Error{Kind: ErrorProtocol,
			Stage: "build_mismatch", Err: fmt.Errorf("expected Build %s / %s; received %q / %q", c.config.BuildNumber, c.config.BuildID, finished.BuildNumber, finished.BuildID)})
	}
	result.BuildVerification = "verified"
	if finished.DefaultDatasetID == "" {
		return c.finishFailure(ctx, result, validURL, StatusTransportError, "dataset_identity", &Error{Kind: ErrorProtocol,
			Stage: "dataset_identity", Err: errors.New("successful Run did not provide defaultDatasetId")})
	}
	result.DatasetID = finished.DefaultDatasetID
	items, complete, err := c.readDataset(ctx, finished.DefaultDatasetID)
	if err != nil {
		return c.finishFailure(ctx, result, validURL, StatusTransportError, "dataset_read", err)
	}
	result.RawItems, result.DatasetComplete = items, complete
	result.Status, result.Text, result.Segments, result.Error = classifyItems(items, complete)
	if err := c.config.Journal.Append(ctx, c.journalEntry(string(result.Status), validURL, result.RunID, result.DatasetID,
		result.RunStatus, result.BuildNumber, result.BuildID, result.BuildVerification, capValue(c.config.MaxTotalChargeUSD))); err != nil {
		result.Status, result.Stage, result.Error = StatusTransportError, "journal_terminal", "Run completed but terminal Journal write failed"
		return result
	}
	return result
}

func (c *Client) runCreateURL() (string, error) {
	actor := strings.ReplaceAll(c.config.ActorID, "/", "~")
	return c.base + "/acts/" + url.PathEscape(actor) + "/runs", nil
}

func (c *Client) request(ctx context.Context, method, endpoint string, body []byte) ([]byte, int, error) {
	var reader io.Reader
	if body != nil {
		reader = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, method, endpoint, reader)
	if err != nil {
		return nil, 0, &Error{Kind: ErrorTransport, Stage: "request_build", Err: err}
	}
	req.Header.Set("Authorization", "Bearer "+c.config.Token)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.client.Do(req)
	if err != nil {
		return nil, 0, &Error{Kind: ErrorTransport, Stage: "http", Err: err}
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 16<<20))
	if err != nil {
		return nil, resp.StatusCode, &Error{Kind: ErrorTransport, Stage: "response_read", Err: err}
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return nil, resp.StatusCode, &apiHTTPError{StatusCode: resp.StatusCode}
	}
	return raw, resp.StatusCode, nil
}

func (c *Client) waitForRun(ctx context.Context, runID string, created runMetadata) (runMetadata, error) {
	latest := created
	var lastErr error
	for attempt := 0; attempt < c.config.MaxPolls; attempt++ {
		if attempt > 0 {
			if err := c.sleep(ctx, c.config.PollInterval); err != nil {
				return latest, &Error{Kind: ErrorTransport, Stage: "run_poll_sleep", Err: err}
			}
		}
		path := c.base + "/actor-runs/" + url.PathEscape(runID)
		var raw []byte
		for getAttempt := 0; getAttempt < 3; getAttempt++ {
			var err error
			raw, _, err = c.request(ctx, http.MethodGet, path, nil)
			if err == nil {
				lastErr = nil
				break
			}
			lastErr = err
			if getAttempt < 2 {
				if sleepErr := c.sleep(ctx, time.Duration(getAttempt+1)*100*time.Millisecond); sleepErr != nil {
					return latest, &Error{Kind: ErrorTransport, Stage: "run_get_retry", Err: sleepErr}
				}
			}
		}
		if lastErr != nil {
			return latest, &Error{Kind: ErrorTransport, Stage: "run_get", Err: lastErr}
		}
		var response apiEnvelope
		if err := json.Unmarshal(raw, &response); err != nil || response.Data.ID != runID {
			return latest, &Error{Kind: ErrorProtocol, Stage: "run_identity", Err: errors.New("Run GET response is invalid or has a mismatched ID")}
		}
		latest = response.Data
		switch latest.Status {
		case "SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED":
			return latest, nil
		}
	}
	return latest, &Error{Kind: ErrorTransport, Stage: "run_poll_timeout", Err: errors.New("timed out waiting for Actor Run terminal status")}
}

func (c *Client) readDataset(ctx context.Context, datasetID string) ([]map[string]any, bool, error) {
	endpoint := c.base + "/datasets/" + url.PathEscape(datasetID) + "/items?limit=" + strconv.Itoa(c.config.DatasetLimit)
	var raw []byte
	var err error
	for attempt := 0; attempt < 3; attempt++ {
		raw, _, err = c.request(ctx, http.MethodGet, endpoint, nil)
		if err == nil {
			break
		}
		if attempt < 2 {
			if sleepErr := c.sleep(ctx, time.Duration(attempt+1)*100*time.Millisecond); sleepErr != nil {
				return nil, false, &Error{Kind: ErrorTransport, Stage: "dataset_get_retry", Err: sleepErr}
			}
		}
	}
	if err != nil {
		return nil, false, &Error{Kind: ErrorTransport, Stage: "dataset_get", Err: err}
	}
	items := []map[string]any{}
	trimmed := bytes.TrimSpace(raw)
	if len(trimmed) == 0 || trimmed[0] != '[' {
		return nil, false, &Error{Kind: ErrorProtocol, Stage: "dataset_decode", Err: errors.New("Dataset response is not a JSON array")}
	}
	if err := json.Unmarshal(raw, &items); err != nil {
		return nil, false, &Error{Kind: ErrorProtocol, Stage: "dataset_decode", Err: errors.New("Dataset response contains an invalid item")}
	}
	if items == nil {
		items = []map[string]any{}
	}
	return items, len(items) < c.config.DatasetLimit, nil
}

func classifyItems(items []map[string]any, complete bool) (Status, string, []Segment, string) {
	segments := []Segment{}
	if len(items) == 0 {
		if !complete {
			return StatusUnknown, "", segments, "Dataset completeness could not be established"
		}
		return StatusEmpty, "", segments, ""
	}
	var transcript string
	for _, item := range items {
		if item == nil {
			return StatusUnknown, "", segments, "Dataset contained a non-object item"
		}
		if errMsg, ok := item["errMsg"].(string); ok && strings.TrimSpace(errMsg) != "" {
			return StatusActorError, "", segments, errMsg
		}
		if rawErr, exists := item["errMsg"]; exists && rawErr != nil {
			if _, ok := rawErr.(string); !ok {
				return StatusUnknown, "", segments, "Actor error field has an unexpected type"
			}
		}
		if transcript == "" {
			if rawText, exists := item["text"]; exists && rawText != nil {
				text, ok := rawText.(string)
				if !ok {
					return StatusUnknown, "", segments, "Transcript text has an unexpected type"
				}
				if strings.TrimSpace(text) == "" {
					continue
				}
				transcript = text
				if rawSegments, exists := item["segments"]; exists && rawSegments != nil {
					list, ok := rawSegments.([]any)
					if !ok {
						return StatusUnknown, transcript, segments, "Transcript segments have an unexpected type"
					}
					for _, raw := range list {
						segment, ok := raw.(map[string]any)
						if !ok {
							return StatusUnknown, transcript, segments, "Transcript segment has an unexpected type"
						}
						segments = append(segments, Segment(segment))
					}
				}
			}
		}
	}
	if !complete {
		return StatusUnknown, transcript, segments, "Dataset reached the configured single-page item limit"
	}
	if transcript != "" {
		return StatusSuccess, transcript, segments, ""
	}
	return StatusNoTranscript, "", segments, "Dataset items did not contain non-empty transcript text"
}

func (c *Client) journalEntry(stage, sourceURL, runID, datasetID, runStatus, buildNumber, buildID, verification string, cap *float64) JournalEntry {
	return JournalEntry{At: c.now().UTC(), Stage: stage, ActorID: c.config.ActorID, SourceURL: sourceURL, RunID: runID,
		DatasetID: datasetID, RunStatus: runStatus, BuildNumber: buildNumber, BuildID: buildID,
		BuildVerification: verification, MaxTotalChargeUSD: cap, RestartOnError: false}
}

func (c *Client) failure(status Status, stage, sourceURL, runID, datasetID, runStatus, buildNumber, buildID, verification string, err error) Result {
	if status == StatusTransportError && stage == "build_mismatch" {
		verification = "mismatch"
	}
	kind := ErrorTransport
	switch status {
	case StatusCreationUnknown:
		kind = ErrorCreation
	case StatusRunFailed, StatusUnknown:
		kind = ErrorProtocol
	case StatusTransportError:
		if stage == "input_validation" {
			kind = ErrorInput
		}
	}
	var typed *Error
	if errors.As(err, &typed) {
		kind = typed.Kind
	}
	return Result{Status: status, Stage: stage, SourceURL: sourceURL, RunID: runID, DatasetID: datasetID, RunStatus: runStatus,
		ActorID: c.config.ActorID, BuildNumber: buildNumber, BuildID: buildID, BuildVerification: verification,
		Segments: []Segment{}, RawItems: []map[string]any{}, Error: err.Error(),
		Cause: &Error{Kind: kind, Stage: stage, Err: err}}
}

func (c *Client) finishFailure(ctx context.Context, result Result, sourceURL string, status Status, stage string, err error) Result {
	return c.finishFailureResult(ctx, result, sourceURL, status, stage, err)
}

func (c *Client) finishFailureResult(ctx context.Context, result Result, sourceURL string, status Status, stage string, err error) Result {
	result.Status, result.Stage, result.Error = status, stage, err.Error()
	kind := ErrorTransport
	if status == StatusCreationUnknown {
		kind = ErrorCreation
	}
	var typed *Error
	if errors.As(err, &typed) {
		kind = typed.Kind
	}
	result.Cause = &Error{Kind: kind, Stage: stage, Err: err}
	entry := c.journalEntry(string(status), sourceURL, result.RunID, result.DatasetID, result.RunStatus,
		result.BuildNumber, result.BuildID, result.BuildVerification, capValue(c.config.MaxTotalChargeUSD))
	if journalErr := c.config.Journal.Append(ctx, entry); journalErr != nil {
		result.Status, result.Stage, result.Error = StatusTransportError, "journal_terminal", "Run state is known but terminal Journal write failed"
		result.Cause = &Error{Kind: ErrorJournal, Stage: "journal_terminal", Err: journalErr}
	}
	return result
}
