package transcriptapi

import (
	"context"
	"fmt"
	"net/url"
	"strings"
)

type bulkActorInput struct {
	BulkURLs           []string `json:"bulkUrls"`
	ResultsLimit       *int     `json:"resultsLimit,omitempty"`
	SkipPinnedPosts    *bool    `json:"skipPinnedPosts,omitempty"`
	IncludeSharesCount *bool    `json:"includeSharesCount,omitempty"`
}

// ValidateBulkRequest validates and normalizes a Native Bulk request before any I/O.
func ValidateBulkRequest(request BulkRequest, datasetLimit int) (BulkRequest, error) {
	if len(request.URLs) == 0 {
		return BulkRequest{}, fmt.Errorf("at least one explicit URL is required")
	}
	if datasetLimit <= 0 {
		datasetLimit = DefaultDatasetLimit
	}
	if len(request.URLs) > datasetLimit {
		return BulkRequest{}, fmt.Errorf("bulk input exceeds the configured single-page dataset limit; a truncated Dataset would make absent results unknown")
	}
	normalized := BulkRequest{URLs: make([]string, 0, len(request.URLs)), ResultsLimit: request.ResultsLimit,
		SkipPinnedPosts: request.SkipPinnedPosts, IncludeSharesCount: request.IncludeSharesCount}
	identities, shortcodes := map[string]struct{}{}, map[string]struct{}{}
	for index, raw := range request.URLs {
		valid, err := ValidateVideoURL(raw)
		if err != nil {
			return BulkRequest{}, fmt.Errorf("urls[%d]: %w", index, err)
		}
		identity, _ := canonicalVideoIdentity(valid)
		code := videoShortcode(valid)
		if _, exists := identities[identity]; exists {
			return BulkRequest{}, fmt.Errorf("urls[%d] duplicates or ambiguously aliases another Reel input", index)
		}
		if _, exists := shortcodes[code]; exists {
			return BulkRequest{}, fmt.Errorf("urls[%d] duplicates or ambiguously aliases another Reel input", index)
		}
		identities[identity], shortcodes[code] = struct{}{}, struct{}{}
		normalized.URLs = append(normalized.URLs, valid)
	}
	if request.ResultsLimit != nil && *request.ResultsLimit < 1 {
		return BulkRequest{}, fmt.Errorf("resultsLimit must be a positive integer")
	}
	return normalized, nil
}

func videoShortcode(raw string) string {
	u, err := url.Parse(raw)
	if err != nil {
		return ""
	}
	parts := strings.Split(strings.Trim(u.Path, "/"), "/")
	if len(parts) != 2 {
		return ""
	}
	return parts[1]
}

func buildBulkActorInput(request BulkRequest) bulkActorInput {
	return bulkActorInput{BulkURLs: request.URLs, ResultsLimit: request.ResultsLimit,
		SkipPinnedPosts: request.SkipPinnedPosts, IncludeSharesCount: request.IncludeSharesCount}
}

type bulkIndex struct {
	byIdentity map[string][]int
	byCode     map[string][]int
}

func newBulkIndex(urls []string) bulkIndex {
	index := bulkIndex{byIdentity: map[string][]int{}, byCode: map[string][]int{}}
	for i, raw := range urls {
		identity, _ := canonicalVideoIdentity(raw)
		index.byIdentity[identity] = append(index.byIdentity[identity], i)
		index.byCode[videoShortcode(raw)] = append(index.byCode[videoShortcode(raw)], i)
	}
	return index
}

func attributeBulkItems(urls []string, items []any, complete bool) ([]BulkInputResult, []ExtraResult, BulkCounts, BulkStatus) {
	index := newBulkIndex(urls)
	mapped := make([][]any, len(urls))
	extras := make([]ExtraResult, 0)
	for _, raw := range items {
		item, ok := raw.(map[string]any)
		if !ok {
			extras = append(extras, ExtraResult{Reason: "dataset_item_not_object", Item: raw})
			continue
		}
		var target *int
		reason := ""
		itemURL, hasURL := item["url"]
		code, hasCode := item["code"].(string)
		codeMatches := []int(nil)
		if hasCode {
			codeMatches = index.byCode[code]
		}
		if hasURL && itemURL != nil {
			urlText, ok := itemURL.(string)
			if !ok {
				reason = "invalid_output_url"
			} else if valid, err := ValidateVideoURL(urlText); err != nil {
				reason = "invalid_output_url"
			} else {
				identity, _ := canonicalVideoIdentity(valid)
				matches := index.byIdentity[identity]
				if len(matches) != 1 {
					reason = "output_url_not_in_input"
				} else {
					candidate := matches[0]
					if hasCode && code != videoShortcode(valid) {
						reason = "url_code_conflict"
					} else if len(codeMatches) > 0 && (len(codeMatches) != 1 || codeMatches[0] != candidate) {
						reason = "ambiguous_url_code_mapping"
					} else {
						target = &candidate
					}
				}
			}
		} else if !hasURL && len(codeMatches) == 1 {
			candidate := codeMatches[0]
			target = &candidate
		} else if hasCode {
			reason = "missing_or_ambiguous_shortcode"
		} else {
			reason = "missing_mapping_identity"
		}
		if target == nil {
			extras = append(extras, ExtraResult{Reason: reason, Item: raw})
		} else {
			mapped[*target] = append(mapped[*target], raw)
		}
	}

	rows := make([]BulkInputResult, 0, len(urls))
	counts := BulkCounts{}
	for i, inputURL := range urls {
		row := BulkInputResult{InputURL: inputURL, Segments: []Segment{}, Items: []any{}, AttributionVerification: "unknown"}
		associated := mapped[i]
		switch {
		case len(associated) == 0:
			if complete {
				row.Status, row.Error = BulkItemMissingResult, "No Dataset item maps to this input URL"
			} else {
				row.Status, row.Error = BulkItemUnknown, "Dataset is incomplete; absence of a result is unknown"
			}
		case len(associated) > 1:
			row.Status, row.Items, row.Error = BulkItemDuplicateResult, associated, "Multiple Dataset items map to this input URL"
			row.AttributionVerification = "verified"
		default:
			item := associated[0].(map[string]any)
			row.Items = []any{item}
			if outputURL, ok := item["url"].(string); ok {
				identity, err := canonicalVideoIdentity(outputURL)
				requested, _ := canonicalVideoIdentity(inputURL)
				if err == nil && identity == requested {
					row.AttributionVerification = "verified"
				}
			} else if code, ok := item["code"].(string); ok && code == videoShortcode(inputURL) {
				row.AttributionVerification = "unverified"
			}
			actorError := false
			if errMsg, exists := item["errMsg"]; exists && errMsg != nil {
				msg, ok := errMsg.(string)
				if !ok {
					row.Status, row.Error = BulkItemUnknown, "Actor error field has an unsupported type"
				} else if strings.TrimSpace(msg) != "" {
					row.Status, row.Error = BulkItemActorError, msg
					actorError = true
				}
			}
			if row.Status == BulkItemUnknown || row.Status == BulkItemActorError {
				// Preserve the conservative classification above.
			} else if text, ok := item["text"].(string); ok && strings.TrimSpace(text) != "" {
				row.Status, row.Text = BulkItemSuccessTranscript, text
				if rawSegments, exists := item["segments"]; exists && rawSegments != nil {
					list, ok := rawSegments.([]any)
					if !ok {
						row.Status, row.Text, row.Error = BulkItemUnknown, "", "Transcript segments have an unsupported type"
					} else {
						for _, value := range list {
							if seg, ok := value.(map[string]any); ok {
								row.Segments = append(row.Segments, Segment(seg))
							} else {
								row.Status, row.Text, row.Error = BulkItemUnknown, "", "Transcript segment has an unsupported type"
								break
							}
						}
					}
				}
			} else if !actorError && (func() bool {
				value, exists := item["text"]
				if !exists || value == nil {
					return true
				}
				s, ok := value.(string)
				return ok && strings.TrimSpace(s) == ""
			})() {
				row.Status, row.Error = BulkItemNoTranscript, "Mapped Dataset item has no non-empty transcript"
			} else {
				row.Status, row.Error = BulkItemUnknown, "Transcript text has an unsupported type"
			}
		}
		rows = append(rows, row)
		countBulk(&counts, row.Status)
	}
	uncertain := !complete || len(extras) > 0 || counts.MissingResult > 0 || counts.DuplicateResult > 0 || counts.Unknown > 0
	overall := BulkUnknown
	if !uncertain {
		switch {
		case counts.SuccessTranscript == len(urls):
			overall = BulkAllSuccess
		case counts.SuccessTranscript > 0:
			overall = BulkPartialSuccess
		case counts.ActorError+counts.NoTranscript == len(urls):
			overall = BulkAllFailed
		}
	}
	return rows, extras, counts, overall
}

func countBulk(counts *BulkCounts, status BulkItemStatus) {
	switch status {
	case BulkItemSuccessTranscript:
		counts.SuccessTranscript++
	case BulkItemActorError:
		counts.ActorError++
	case BulkItemNoTranscript:
		counts.NoTranscript++
	case BulkItemMissingResult:
		counts.MissingResult++
	case BulkItemDuplicateResult:
		counts.DuplicateResult++
	default:
		counts.Unknown++
	}
}

// GetTranscripts submits all URLs in exactly one Native Bulk Actor Run.
func (c *Client) GetTranscripts(ctx context.Context, request BulkRequest) BulkResult {
	clean, err := ValidateBulkRequest(request, c.config.DatasetLimit)
	if err != nil {
		return BulkResult{Status: BulkUnknown, ExecutionStatus: StatusTransportError, URLs: append([]string(nil), request.URLs...),
			Inputs: []BulkInputResult{}, ExtraResults: []ExtraResult{}, RawItems: []any{}, ActorID: c.config.ActorID,
			BuildNumber: c.config.BuildNumber, BuildID: c.config.BuildID, BuildVerification: "unverified", Stage: "input_validation", Error: err.Error(), Cause: &Error{Kind: ErrorInput, Stage: "input_validation", Err: err}}
	}
	input := buildBulkActorInput(clean)
	inputContext := &JournalInputContext{Mode: "native_bulk", Input: input}
	exec := c.executeRun(ctx, "native_bulk", input, inputContext)
	base := BulkResult{Status: BulkUnknown, ExecutionStatus: exec.ExecutionStatus, Inputs: []BulkInputResult{}, ExtraResults: []ExtraResult{},
		Counts: BulkCounts{}, URLs: clean.URLs, RunID: exec.RunID, DatasetID: exec.DatasetID, RunStatus: exec.RunStatus,
		ActorID: c.config.ActorID, BuildNumber: exec.BuildNumber, BuildID: exec.BuildID, BuildVerification: terminalAttributionVerification(exec.BuildVerification),
		DatasetComplete: exec.Complete, RawItems: exec.Items, Error: exec.Error, Stage: exec.Stage, Cause: exec.Cause}
	if base.RawItems == nil {
		base.RawItems = []any{}
	}
	if exec.ExecutionStatus != StatusSuccess {
		base.Counts.Unknown = len(clean.URLs)
		for _, inputURL := range clean.URLs {
			base.Inputs = append(base.Inputs, BulkInputResult{InputURL: inputURL, Status: BulkItemUnknown, Segments: []Segment{}, Items: []any{}, AttributionVerification: "unverified", Error: exec.Error})
		}
		return base
	}
	base.Inputs, base.ExtraResults, base.Counts, base.Status = attributeBulkItems(clean.URLs, exec.Items, exec.Complete)
	terminal := c.journalEntry(string(base.Status), "native_bulk", base.RunID, base.DatasetID, base.RunStatus,
		base.BuildNumber, base.BuildID, base.BuildVerification, capValue(c.config.MaxTotalChargeUSD))
	terminal.InputContext = inputContext
	if err := c.appendJournal(ctx, terminal); err != nil {
		base.Status, base.ExecutionStatus, base.Stage = BulkUnknown, StatusTransportError, "journal_terminal"
		base.Error, base.Cause = "Run completed but terminal Journal write failed", &Error{Kind: ErrorJournal, Stage: "journal_terminal", Err: err}
	}
	return base
}
