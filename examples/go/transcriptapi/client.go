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
	config       Config
	client       *http.Client
	createClient *http.Client
	base         string
	sleep        func(context.Context, time.Duration) error
	now          func() time.Time
}

type apiEnvelope struct {
	Data runMetadata `json:"data"`
}

type runMetadata struct {
	ID               string `json:"id"`
	ActorID          string `json:"actId,omitempty"`
	Status           string `json:"status"`
	DefaultDatasetID string `json:"defaultDatasetId"`
	BuildNumber      string `json:"buildNumber"`
	BuildID          string `json:"buildId"`
}

type runExecution struct {
	RunID             string
	RunActorID        string
	DatasetID         string
	RunStatus         string
	BuildNumber       string
	BuildID           string
	BuildVerification string
	Items             []any
	Complete          bool
	ExecutionStatus   Status
	Stage             string
	Error             string
	Cause             error
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
	// The injected client's transport, timeout, and cookie jar remain in use, but
	// creation requests must not let net/http replay POSTs after a redirect.
	createClient := *config.HTTPClient
	createClient.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
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
	return &Client{config: config, client: config.HTTPClient, createClient: &createClient, base: base, sleep: sleep, now: now}, nil
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
func (c *Client) GetTranscript(ctx context.Context, reelURL string) (result Result) {
	return c.getTranscript(ctx, reelURL, nil)
}

func (c *Client) getTranscript(ctx context.Context, reelURL string, inputContext *JournalInputContext) (result Result) {
	// Public results must always expose a terminal attribution state, including
	// early exits after a Run has been created but before Dataset classification.
	defer func() {
		result.AttributionVerification = terminalAttributionVerification(result.AttributionVerification)
	}()
	validURL, err := ValidateVideoURL(reelURL)
	if err != nil {
		return c.failure(StatusTransportError, "input_validation", reelURL, "", "", "", c.config.BuildNumber, c.config.BuildID, "unverified", err)
	}
	if inputContext == nil {
		inputContext = &JournalInputContext{Mode: "single", Input: map[string]any{"videoUrl": validURL}}
	}
	exec := c.executeRun(ctx, validURL, map[string]any{"videoUrl": validURL}, inputContext)
	result = resultFromExecution(c.config.ActorID, validURL, exec)
	if exec.ExecutionStatus != StatusSuccess {
		return result
	}
	items, complete := exec.Items, exec.Complete
	result.RawItems, result.DatasetComplete = items, complete
	result.Status, result.Text, result.Segments, result.Error, result.AttributionVerification = classifyItems(items, complete, validURL)
	terminal := c.journalEntry(string(result.Status), validURL, result.RunID, result.DatasetID,
		result.RunStatus, result.BuildNumber, result.BuildID, result.BuildVerification, capValue(c.config.MaxTotalChargeUSD))
	terminal.InputContext = inputContext
	if err := c.appendJournal(ctx, terminal); err != nil {
		result.Status, result.Stage, result.Error = StatusTransportError, "journal_terminal", "Run completed but terminal Journal write failed"
		return result
	}
	return result
}

// executeRun is the single Actor Run creation path shared by every mode. It never
// retries the creation POST; callers only classify the returned Dataset items.
func (c *Client) executeRun(ctx context.Context, label string, runInput any, inputContext *JournalInputContext) runExecution {
	result := runExecution{ExecutionStatus: StatusTransportError, BuildNumber: c.config.BuildNumber, BuildID: c.config.BuildID,
		BuildVerification: "pending", Items: []any{}}
	appendFailure := func(status Status, stage string, cause error, verification string) runExecution {
		result.ExecutionStatus, result.Stage, result.Cause = status, stage, cause
		result.Error = cause.Error()
		entry := c.journalEntry(stage, label, result.RunID, result.DatasetID, result.RunStatus, result.BuildNumber,
			result.BuildID, verification, capValue(c.config.MaxTotalChargeUSD))
		entry.InputContext = inputContext
		if err := c.appendJournal(ctx, entry); err != nil {
			result.ExecutionStatus, result.Stage, result.Error = StatusTransportError, "journal_terminal", "Run state is known but terminal Journal write failed"
			result.Cause = &Error{Kind: ErrorJournal, Stage: "journal_terminal", Err: err}
		}
		return result
	}
	intent := c.journalEntry("intent", label, "", "", "", c.config.BuildNumber, c.config.BuildID, "pending", capValue(c.config.MaxTotalChargeUSD))
	intent.InputContext = inputContext
	if err := c.appendJournal(ctx, intent); err != nil {
		result.Stage, result.Error = "journal_intent", err.Error()
		result.Cause = &Error{Kind: ErrorJournal, Stage: "journal_intent", Err: err}
		return result
	}
	body, err := json.Marshal(runInput)
	if err != nil {
		return appendFailure(StatusTransportError, "run_create_prepare", &Error{Kind: ErrorProtocol, Stage: "run_create_prepare", Err: errors.New("Actor input could not be encoded")}, "unknown")
	}
	postURL, err := c.runCreateURL()
	if err != nil {
		return appendFailure(StatusTransportError, "run_create_prepare", err, "unknown")
	}
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
		result.ExecutionStatus, result.Stage, result.Error = status, stage, postErr.Error()
		kind := ErrorCreation
		if status == StatusTransportError {
			kind = ErrorTransport
		}
		result.Cause = &Error{Kind: kind, Stage: stage, Err: postErr}
		failureEntry := c.journalEntry(stage, label, "", "", "", c.config.BuildNumber, c.config.BuildID, "unknown", capValue(c.config.MaxTotalChargeUSD))
		failureEntry.InputContext = inputContext
		if journalErr := c.appendJournal(ctx, failureEntry); journalErr != nil {
			result.ExecutionStatus, result.Stage, result.Error = StatusCreationUnknown, "journal_creation_unknown", "Run creation outcome is unknown and the Journal update failed"
			result.Cause = &Error{Kind: ErrorJournal, Stage: "journal_creation_unknown", Err: journalErr}
		}
		return result
	}
	var created apiEnvelope
	if err := json.Unmarshal(createdRaw, &created); err != nil || created.Data.ID == "" {
		cause := errors.New("Run creation response did not provide a verifiable Run ID")
		result.ExecutionStatus, result.Stage, result.Error = StatusCreationUnknown, "run_create_unknown", cause.Error()
		result.Cause = &Error{Kind: ErrorCreation, Stage: result.Stage, Err: cause}
		entry := c.journalEntry(result.Stage, label, "", "", "", "", "", "unknown", capValue(c.config.MaxTotalChargeUSD))
		entry.InputContext = inputContext
		if journalErr := c.appendJournal(ctx, entry); journalErr != nil {
			result.Error = "Run creation outcome is unknown and the Journal update failed"
			result.Cause = &Error{Kind: ErrorJournal, Stage: "journal_creation_unknown", Err: journalErr}
		}
		return result
	}
	result.RunID, result.DatasetID, result.RunStatus = created.Data.ID, created.Data.DefaultDatasetID, created.Data.Status
	result.RunActorID = created.Data.ActorID
	result.BuildNumber, result.BuildID = created.Data.BuildNumber, created.Data.BuildID
	createdEntry := c.journalEntry("run_created", label, result.RunID, result.DatasetID, result.RunStatus,
		result.BuildNumber, result.BuildID, "pending", capValue(c.config.MaxTotalChargeUSD))
	createdEntry.RunActorID = result.RunActorID
	createdEntry.InputContext = inputContext
	if err := c.appendJournal(ctx, createdEntry); err != nil {
		result.ExecutionStatus, result.Stage, result.Error = StatusTransportError, "journal_run_created", "Run was created but its identity could not be persisted"
		result.Cause = &Error{Kind: ErrorJournal, Stage: result.Stage, Err: err}
		return result
	}
	finished, err := c.waitForRun(ctx, result.RunID, created.Data)
	if err != nil {
		result.RunStatus = finished.Status
		return appendFailure(StatusTransportError, "run_poll", err, "unverified")
	}
	result.RunStatus, result.BuildNumber, result.BuildID = finished.Status, finished.BuildNumber, finished.BuildID
	if finished.Status != "SUCCEEDED" {
		return appendFailure(StatusRunFailed, "run_terminal", fmt.Errorf("Actor Run finished with status %s", finished.Status), "unverified")
	}
	if finished.BuildNumber != c.config.BuildNumber || finished.BuildID != c.config.BuildID {
		result.BuildVerification = "mismatch"
		return appendFailure(StatusTransportError, "build_mismatch", &Error{Kind: ErrorProtocol, Stage: "build_mismatch",
			Err: fmt.Errorf("expected Build %s / %s; received %q / %q", c.config.BuildNumber, c.config.BuildID, finished.BuildNumber, finished.BuildID)}, "mismatch")
	}
	result.BuildVerification = "verified"
	if finished.DefaultDatasetID == "" {
		return appendFailure(StatusTransportError, "dataset_identity", &Error{Kind: ErrorProtocol, Stage: "dataset_identity",
			Err: errors.New("successful Run did not provide defaultDatasetId")}, "verified")
	}
	result.DatasetID = finished.DefaultDatasetID
	items, complete, err := c.readDataset(ctx, result.DatasetID)
	if err != nil {
		return appendFailure(StatusTransportError, "dataset_read", err, "verified")
	}
	result.Items, result.Complete, result.ExecutionStatus = items, complete, StatusSuccess
	result.BuildVerification = "verified"
	return result
}

func (c *Client) appendJournal(ctx context.Context, entry JournalEntry) error {
	return c.config.Journal.Append(ctx, entry)
}

func resultFromExecution(actorID, sourceURL string, exec runExecution) Result {
	buildVerification := exec.BuildVerification
	if buildVerification == "" || buildVerification == "pending" {
		buildVerification = "unverified"
	}
	result := Result{Status: exec.ExecutionStatus, RunStatus: exec.RunStatus, RunID: exec.RunID, DatasetID: exec.DatasetID,
		SourceURL: sourceURL, ActorID: actorID, BuildNumber: exec.BuildNumber, BuildID: exec.BuildID,
		BuildVerification: buildVerification, DatasetComplete: exec.Complete, Segments: []Segment{}, RawItems: exec.Items,
		AttributionVerification: "unverified", Stage: exec.Stage, Error: exec.Error, Cause: exec.Cause}
	if result.RawItems == nil {
		result.RawItems = []any{}
	}
	if exec.ExecutionStatus == StatusSuccess {
		result.Stage, result.Error, result.Cause = "", "", nil
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
	requestClient := c.client
	if method == http.MethodPost {
		requestClient = c.createClient
	}
	resp, err := requestClient.Do(req)
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

func (c *Client) readDataset(ctx context.Context, datasetID string) ([]any, bool, error) {
	endpoint := c.base + "/datasets/" + url.PathEscape(datasetID) + "/items?limit=" + strconv.Itoa(c.config.DatasetLimit) + "&offset=0"
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
	items := []any{}
	trimmed := bytes.TrimSpace(raw)
	if len(trimmed) == 0 || trimmed[0] != '[' {
		return nil, false, &Error{Kind: ErrorProtocol, Stage: "dataset_decode", Err: errors.New("Dataset response is not a JSON array")}
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if err := decoder.Decode(&items); err != nil {
		return nil, false, &Error{Kind: ErrorProtocol, Stage: "dataset_decode", Err: errors.New("Dataset response contains invalid JSON")}
	}
	if err := decoder.Decode(&struct{}{}); err != io.EOF {
		return nil, false, &Error{Kind: ErrorProtocol, Stage: "dataset_decode", Err: errors.New("Dataset response contains trailing data")}
	}
	if items == nil {
		items = []any{}
	}
	return items, len(items) < c.config.DatasetLimit, nil
}

func classifyItems(items []any, complete bool, sourceURL string) (Status, string, []Segment, string, string) {
	segments := []Segment{}
	if len(items) == 0 {
		if !complete {
			return StatusUnknown, "", segments, "Dataset completeness could not be established", "unverified"
		}
		return StatusEmpty, "", segments, "", "unverified"
	}
	requestedIdentity, identityErr := canonicalVideoIdentity(sourceURL)
	if identityErr != nil {
		return StatusUnknown, "", segments, "Requested URL could not be normalized for attribution", "unknown"
	}
	verification := "verified"
	objects := make([]map[string]any, 0, len(items))
	for _, rawItem := range items {
		item, ok := rawItem.(map[string]any)
		if !ok {
			return StatusUnknown, "", segments, "Dataset contained a non-object item", "unknown"
		}
		objects = append(objects, item)
		itemURL, exists := item["url"]
		if !exists {
			verification = "unverified"
			continue
		}
		urlText, ok := itemURL.(string)
		if !ok {
			return StatusUnknown, "", segments, "Dataset item URL has an unexpected type", "unknown"
		}
		itemIdentity, err := canonicalVideoIdentity(urlText)
		if err != nil {
			return StatusUnknown, "", segments, "Dataset item URL is invalid", "unknown"
		}
		if itemIdentity != requestedIdentity {
			return StatusUnknown, "", segments, "Dataset item URL does not match the requested Reel", "mismatch"
		}
	}
	var transcript string
	for _, item := range objects {
		if errMsg, ok := item["errMsg"].(string); ok && strings.TrimSpace(errMsg) != "" {
			return StatusActorError, "", segments, errMsg, verification
		}
		if rawErr, exists := item["errMsg"]; exists && rawErr != nil {
			if _, ok := rawErr.(string); !ok {
				return StatusUnknown, "", segments, "Actor error field has an unexpected type", verification
			}
		}
		if transcript == "" {
			if rawText, exists := item["text"]; exists && rawText != nil {
				text, ok := rawText.(string)
				if !ok {
					return StatusUnknown, "", segments, "Transcript text has an unexpected type", verification
				}
				if strings.TrimSpace(text) == "" {
					continue
				}
				transcript = text
				if rawSegments, exists := item["segments"]; exists && rawSegments != nil {
					list, ok := rawSegments.([]any)
					if !ok {
						return StatusUnknown, transcript, segments, "Transcript segments have an unexpected type", verification
					}
					for _, raw := range list {
						segment, ok := raw.(map[string]any)
						if !ok {
							return StatusUnknown, transcript, segments, "Transcript segment has an unexpected type", verification
						}
						segments = append(segments, Segment(segment))
					}
				}
			}
		}
	}
	if !complete {
		return StatusUnknown, transcript, segments, "Dataset reached the configured single-page item limit", verification
	}
	if transcript != "" {
		return StatusSuccess, transcript, segments, "", verification
	}
	return StatusNoTranscript, "", segments, "Dataset items did not contain non-empty transcript text", verification
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
		Segments: []Segment{}, RawItems: []any{}, AttributionVerification: "unverified", Error: err.Error(),
		Cause: &Error{Kind: kind, Stage: stage, Err: err}}
}

func (c *Client) finishFailure(ctx context.Context, result Result, sourceURL string, status Status, stage string, err error) Result {
	return c.finishFailureResult(ctx, result, sourceURL, status, stage, err)
}

func (c *Client) finishFailureResult(ctx context.Context, result Result, sourceURL string, status Status, stage string, err error) Result {
	result.AttributionVerification = terminalAttributionVerification(result.AttributionVerification)
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

func terminalAttributionVerification(value string) string {
	switch value {
	case "verified", "unverified", "mismatch", "unknown":
		return value
	case "pending":
		return "unverified"
	default:
		return "unknown"
	}
}
