package transcriptapi

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/url"
)

// ResumeTranscript recovers a recorded Single Run using GET requests only.
func (c *Client) ResumeTranscript(ctx context.Context, runID, reelURL string) Result {
	valid, err := ValidateVideoURL(reelURL)
	if err != nil {
		return c.failure(StatusTransportError, "input_validation", reelURL, runID, "", "", c.config.BuildNumber, c.config.BuildID, "unverified", err)
	}
	input := map[string]any{"videoUrl": valid}
	inputContext := &JournalInputContext{Mode: "single", Input: input}
	exec := c.resumeExecution(ctx, runID, "single", valid, input, inputContext)
	result := resultFromExecution(c.config.ActorID, valid, exec)
	if exec.ExecutionStatus == StatusSuccess {
		result.RawItems, result.DatasetComplete = exec.Items, exec.Complete
		result.Status, result.Text, result.Segments, result.Error, result.AttributionVerification = classifyItems(exec.Items, exec.Complete, valid)
		entry := c.journalEntry(string(result.Status), valid, result.RunID, result.DatasetID, result.RunStatus, result.BuildNumber, result.BuildID, result.BuildVerification, capValue(c.config.MaxTotalChargeUSD))
		entry.InputContext = inputContext
		if err := c.appendJournal(ctx, entry); err != nil {
			result.Status, result.Stage, result.Error, result.Cause = StatusTransportError, "journal_terminal", "Resumed result could not be recorded", &Error{Kind: ErrorJournal, Stage: "journal_terminal", Err: err}
		}
	}
	return result
}

// ResumeTranscripts recovers a Native Bulk Run using GET requests only.
func (c *Client) ResumeTranscripts(ctx context.Context, runID string, request BulkRequest) BulkResult {
	clean, err := ValidateBulkRequest(request, c.config.DatasetLimit)
	if err != nil {
		return BulkResult{Status: BulkUnknown, ExecutionStatus: StatusTransportError, URLs: request.URLs, Inputs: []BulkInputResult{}, ExtraResults: []ExtraResult{}, RawItems: []any{}, ActorID: c.config.ActorID, BuildNumber: c.config.BuildNumber, BuildID: c.config.BuildID, BuildVerification: "unverified", Stage: "input_validation", Error: err.Error()}
	}
	input := buildBulkActorInput(clean)
	inputContext := &JournalInputContext{Mode: "native_bulk", Input: input}
	label := "native_bulk"
	exec := c.resumeExecution(ctx, runID, "native_bulk", label, input, inputContext)
	result := BulkResult{Status: BulkUnknown, ExecutionStatus: exec.ExecutionStatus, Inputs: []BulkInputResult{}, ExtraResults: []ExtraResult{}, URLs: clean.URLs,
		Counts: BulkCounts{Unknown: len(clean.URLs)}, RawItems: exec.Items, RunID: exec.RunID, DatasetID: exec.DatasetID, RunStatus: exec.RunStatus,
		ActorID: c.config.ActorID, BuildNumber: exec.BuildNumber, BuildID: exec.BuildID, BuildVerification: terminalAttributionVerification(exec.BuildVerification), DatasetComplete: exec.Complete, Error: exec.Error, Stage: exec.Stage, Cause: exec.Cause}
	if exec.ExecutionStatus != StatusSuccess {
		for _, inputURL := range clean.URLs {
			result.Inputs = append(result.Inputs, BulkInputResult{InputURL: inputURL, Status: BulkItemUnknown, Segments: []Segment{}, Items: []any{}, AttributionVerification: "unverified", Error: exec.Error})
		}
		return result
	}
	result.Inputs, result.ExtraResults, result.Counts, result.Status = attributeBulkItems(clean.URLs, exec.Items, exec.Complete)
	entry := c.journalEntry(string(result.Status), label, result.RunID, result.DatasetID, result.RunStatus, result.BuildNumber, result.BuildID, result.BuildVerification, capValue(c.config.MaxTotalChargeUSD))
	entry.InputContext = inputContext
	if err := c.appendJournal(ctx, entry); err != nil {
		result.Status, result.ExecutionStatus, result.Stage, result.Error, result.Cause = BulkUnknown, StatusTransportError, "journal_terminal", "Resumed result could not be recorded", &Error{Kind: ErrorJournal, Stage: "journal_terminal", Err: err}
	}
	return result
}

func (c *Client) resumeExecution(ctx context.Context, runID, mode, label string, expectedInput any, inputContext *JournalInputContext) runExecution {
	failure := func(stage, message string, err error, verification string) runExecution {
		return runExecution{RunID: runID, BuildNumber: c.config.BuildNumber, BuildID: c.config.BuildID, BuildVerification: verification, ExecutionStatus: StatusUnknown, Stage: stage, Error: message, Cause: &Error{Kind: ErrorProtocol, Stage: stage, Err: err}, Items: []any{}}
	}
	if runID == "" {
		return failure("resume_input", "a Run ID is required", errors.New("Run ID is required"), "unverified")
	}
	reader, ok := c.config.Journal.(JournalReader)
	if !ok {
		return failure("resume_journal", "Journal does not support recovery reads", errors.New("Journal reader is required"), "unverified")
	}
	entries, err := reader.ReadEntries(ctx)
	if err != nil {
		return failure("resume_journal", "could not read the Run Journal", err, "unverified")
	}
	var record *JournalEntry
	for i := range entries {
		entry := &entries[i]
		if entry.RunID == runID && entry.Stage == "run_created" {
			record = entry
		}
	}
	if record == nil || record.ActorID != c.config.ActorID || record.RunActorID == "" || record.BuildNumber != c.config.BuildNumber || record.BuildID != c.config.BuildID || record.DatasetID == "" || record.InputContext == nil || record.InputContext.Mode != mode {
		return failure("resume_journal", "Run is absent from the Journal or lacks verifiable recovery context", errors.New("matching run_created Journal record is required"), "unknown")
	}
	actual, marshalErr := canonicalJSON(record.InputContext.Input)
	if marshalErr != nil {
		return failure("resume_journal", "stored input context is invalid", marshalErr, "unknown")
	}
	expected, marshalErr := canonicalJSON(expectedInput)
	if marshalErr != nil || !bytes.Equal(actual, expected) {
		return failure("resume_input_mismatch", "resume input does not exactly match the recorded Actor input", errors.New("resume input mismatch"), "unknown")
	}
	path := c.base + "/actor-runs/" + url.PathEscape(runID)
	raw, _, err := c.request(ctx, "GET", path, nil)
	if err != nil {
		return failure("resume_run_get", "could not retrieve the recorded Run", err, "unverified")
	}
	var response apiEnvelope
	if err := json.Unmarshal(raw, &response); err != nil || response.Data.ID != runID {
		return failure("resume_run_identity", "Run GET response is invalid or mismatched", errors.New("Run identity mismatch"), "unknown")
	}
	meta := response.Data
	if meta.ActorID == "" || meta.ActorID != record.RunActorID {
		return failure("resume_actor_mismatch", "Run belongs to a different or unverifiable Actor", errors.New("Actor identity mismatch"), "mismatch")
	}
	resumeFailure := func(result runExecution) runExecution {
		entry := c.journalEntry(result.Stage, label, runID, record.DatasetID, result.RunStatus, result.BuildNumber, result.BuildID, result.BuildVerification, capValue(c.config.MaxTotalChargeUSD))
		entry.InputContext = inputContext
		if journalErr := c.appendJournal(ctx, entry); journalErr != nil {
			result.ExecutionStatus, result.Stage, result.Error, result.Cause = StatusTransportError, "journal_terminal", "Resumed Run outcome could not be recorded", &Error{Kind: ErrorJournal, Stage: "journal_terminal", Err: journalErr}
		}
		return result
	}
	finished, err := c.waitForRun(ctx, runID, meta)
	if err != nil {
		return resumeFailure(runExecution{RunID: runID, DatasetID: record.DatasetID, RunStatus: finished.Status, BuildNumber: finished.BuildNumber, BuildID: finished.BuildID, BuildVerification: "unverified", ExecutionStatus: StatusTransportError, Stage: "run_poll", Error: err.Error(), Cause: err, Items: []any{}})
	}
	base := runExecution{RunID: runID, DatasetID: record.DatasetID, RunStatus: finished.Status, BuildNumber: finished.BuildNumber, BuildID: finished.BuildID, Items: []any{}}
	base.RunActorID = finished.ActorID
	if base.RunActorID == "" || base.RunActorID != record.RunActorID {
		base.ExecutionStatus, base.Stage, base.Error = StatusTransportError, "resume_actor_mismatch", "Run Actor identity changed or is unverifiable"
		base.BuildVerification = "mismatch"
		return resumeFailure(base)
	}
	if finished.Status != "SUCCEEDED" {
		base.ExecutionStatus, base.Stage, base.Error = StatusRunFailed, "run_terminal", "Actor Run finished with status "+finished.Status
		return resumeFailure(base)
	}
	if finished.BuildNumber != c.config.BuildNumber || finished.BuildID != c.config.BuildID {
		base.ExecutionStatus, base.BuildVerification, base.Stage, base.Error = StatusTransportError, "mismatch", "build_mismatch", "Run Build identity does not match configured Build"
		return resumeFailure(base)
	}
	base.BuildVerification = "verified"
	if finished.DefaultDatasetID == "" || finished.DefaultDatasetID != record.DatasetID {
		base.ExecutionStatus, base.Stage, base.Error = StatusTransportError, "dataset_identity", "Run Dataset identity does not match Journal"
		return resumeFailure(base)
	}
	items, complete, err := c.readDataset(ctx, record.DatasetID)
	if err != nil {
		base.ExecutionStatus, base.Stage, base.Error, base.Cause = StatusTransportError, "dataset_read", err.Error(), err
		return resumeFailure(base)
	}
	base.Items, base.Complete, base.ExecutionStatus = items, complete, StatusSuccess
	_ = label
	return base
}

func canonicalJSON(value any) ([]byte, error) {
	encoded, err := json.Marshal(value)
	if err != nil {
		return nil, err
	}
	var normalized any
	if err := json.Unmarshal(encoded, &normalized); err != nil {
		return nil, err
	}
	return json.Marshal(normalized)
}
