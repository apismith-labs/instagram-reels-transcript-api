package transcriptapi

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"
)

var (
	profileUsernamePattern = regexp.MustCompile(`^[A-Za-z0-9._]+$`)
	profileDatePattern     = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}$`)
	profileRelativePattern = regexp.MustCompile(`^\d+[dwmy]$`)
	profilePostURLPattern  = regexp.MustCompile(`^https://(?:www\.)?instagram\.com/(?:p|reel|reels)/[A-Za-z0-9_-]+/?$`)
)

type profileActorInput struct {
	Usernames          []string `json:"usernames"`
	ResultsLimit       *int     `json:"resultsLimit,omitempty"`
	OnlyPostsNewerThan string   `json:"onlyPostsNewerThan,omitempty"`
	SkipPinnedPosts    *bool    `json:"skipPinnedPosts,omitempty"`
	IncludeSharesCount *bool    `json:"includeSharesCount,omitempty"`
}

// ValidateProfileRequest validates the Profile allowlist before any request.
func ValidateProfileRequest(request ProfileRequest) (ProfileRequest, error) {
	if len(request.Usernames) == 0 {
		return ProfileRequest{}, fmt.Errorf("at least one explicit username is required")
	}
	seen := map[string]bool{}
	clean := ProfileRequest{Usernames: make([]string, 0, len(request.Usernames)), ResultsLimit: request.ResultsLimit,
		OnlyPostsNewerThan: request.OnlyPostsNewerThan, SkipPinnedPosts: request.SkipPinnedPosts, IncludeSharesCount: request.IncludeSharesCount}
	for i, username := range request.Usernames {
		if username == "" || strings.TrimSpace(username) != username || !profileUsernamePattern.MatchString(username) ||
			!strings.ContainsAny(username, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") || strings.HasPrefix(username, ".") || strings.HasSuffix(username, ".") || strings.Contains(username, "..") {
			return ProfileRequest{}, fmt.Errorf("usernames[%d] must be a valid Instagram username without @ or whitespace", i)
		}
		key := strings.ToLower(username)
		if seen[key] {
			return ProfileRequest{}, fmt.Errorf("usernames[%d] duplicates or ambiguously aliases another username", i)
		}
		seen[key] = true
		clean.Usernames = append(clean.Usernames, username)
	}
	if request.ResultsLimit != nil && *request.ResultsLimit <= 0 {
		return ProfileRequest{}, fmt.Errorf("resultsLimit must be a positive integer")
	}
	if request.OnlyPostsNewerThan != "" {
		value := request.OnlyPostsNewerThan
		if profileDatePattern.MatchString(value) {
			if _, err := time.Parse("2006-01-02", value); err != nil {
				return ProfileRequest{}, fmt.Errorf("onlyPostsNewerThan must be a real YYYY-MM-DD date")
			}
		} else if profileRelativePattern.MatchString(value) {
			amount, _ := strconv.Atoi(value[:len(value)-1])
			if amount <= 0 {
				return ProfileRequest{}, fmt.Errorf("onlyPostsNewerThan relative period must be positive")
			}
		} else {
			return ProfileRequest{}, fmt.Errorf("onlyPostsNewerThan accepts YYYY-MM-DD or a positive relative period; ISO timestamps are not verified")
		}
	}
	return clean, nil
}

func profileInput(request ProfileRequest) profileActorInput {
	return profileActorInput{Usernames: request.Usernames, ResultsLimit: request.ResultsLimit, OnlyPostsNewerThan: request.OnlyPostsNewerThan,
		SkipPinnedPosts: request.SkipPinnedPosts, IncludeSharesCount: request.IncludeSharesCount}
}

// GetProfilePosts runs one Profile Actor Run. Profile status is based on post metadata, not transcripts.
func (c *Client) GetProfilePosts(ctx context.Context, request ProfileRequest) ProfileResult {
	clean, err := ValidateProfileRequest(request)
	if err != nil {
		return ProfileResult{Status: ProfileUnknown, ExecutionStatus: StatusTransportError, Usernames: append([]string(nil), request.Usernames...), Posts: []ProfilePost{}, RawItems: []any{}, ActorID: c.config.ActorID, BuildNumber: c.config.BuildNumber, BuildID: c.config.BuildID, BuildVerification: "unverified", Stage: "input_validation", Error: err.Error(), Cause: &Error{Kind: ErrorInput, Stage: "input_validation", Err: err}}
	}
	input := profileInput(clean)
	label := "profile:" + strings.Join(clean.Usernames, ",")
	context := &JournalInputContext{Mode: "profile", Input: input}
	exec := c.executeRun(ctx, label, input, context)
	result := ProfileResult{Status: ProfileUnknown, ExecutionStatus: exec.ExecutionStatus, Usernames: clean.Usernames, Posts: []ProfilePost{}, RawItems: exec.Items,
		RunID: exec.RunID, DatasetID: exec.DatasetID, RunStatus: exec.RunStatus, ActorID: c.config.ActorID, BuildNumber: exec.BuildNumber,
		BuildID: exec.BuildID, BuildVerification: terminalAttributionVerification(exec.BuildVerification), DatasetComplete: exec.Complete, Error: exec.Error, Stage: exec.Stage, Cause: exec.Cause}
	if result.RawItems == nil {
		result.RawItems = []any{}
	}
	if exec.ExecutionStatus != StatusSuccess {
		return result
	}
	failed, unknown := 0, false
	for _, raw := range exec.Items {
		post, valid := normalizeProfilePost(raw, clean.Usernames)
		result.Posts = append(result.Posts, post)
		if post.Status == "actor_error" {
			failed++
		} else if !valid {
			unknown = true
		}
	}
	switch {
	case failed > 0:
		result.Status = ProfileActorError
		result.Error = "One or more Profile items contain a non-empty errMsg"
	case !exec.Complete:
		result.Status = ProfileUnknown
		result.Error = "Dataset is incomplete; Profile result completeness is unknown"
	case unknown:
		result.Status = ProfileUnknown
		result.Error = "Dataset contains Profile items with unknown metadata or ownership"
	case len(result.Posts) == 0:
		result.Status = ProfileEmpty
	default:
		result.Status = ProfileSuccess
	}
	terminal := c.journalEntry(string(result.Status), label, result.RunID, result.DatasetID, result.RunStatus, result.BuildNumber, result.BuildID, result.BuildVerification, capValue(c.config.MaxTotalChargeUSD))
	terminal.InputContext = context
	if err := c.appendJournal(ctx, terminal); err != nil {
		result.Status, result.ExecutionStatus, result.Stage, result.Error = ProfileUnknown, StatusTransportError, "journal_terminal", "Run completed but terminal Journal write failed"
		result.Cause = &Error{Kind: ErrorJournal, Stage: "journal_terminal", Err: err}
	}
	return result
}

func normalizeProfilePost(raw any, usernames []string) (ProfilePost, bool) {
	post := ProfilePost{Status: "unknown", Raw: raw}
	item, ok := raw.(map[string]any)
	if !ok {
		post.Error = "Dataset item is not an object"
		return post, false
	}
	if value, ok := item["url"].(string); ok && profilePostURLPattern.MatchString(value) {
		post.URL = value
	}
	if value, ok := item["type"].(string); ok && strings.TrimSpace(value) != "" {
		post.Type = value
	}
	if value, ok := item["ownerUsername"].(string); ok && strings.TrimSpace(value) != "" {
		post.OwnerUsername = value
	}
	if value, ok := item["caption"].(string); ok {
		post.Caption = value
	}
	post.Timestamp = item["timestamp"]
	if value, ok := item["videoUrl"].(string); ok {
		post.VideoURL = value
	}
	if value, ok := item["videoDuration"].(float64); ok {
		post.VideoDuration = value
	}
	if value, ok := item["videoDuration"].(int); ok {
		post.VideoDuration = value
	}
	if value, ok := item["videoDuration"].(json.Number); ok {
		if parsed, err := value.Float64(); err == nil {
			post.VideoDuration = parsed
		}
	}
	if value, exists := item["errMsg"]; exists && value != nil && strings.TrimSpace(fmt.Sprint(value)) != "" {
		post.Status, post.Error = "actor_error", fmt.Sprint(value)
		return post, true
	}
	metadata := post.Type != "" || post.OwnerUsername != "" || strings.TrimSpace(post.Caption) != "" || post.Timestamp != nil || nonEmptyProfileString(item["id"]) || nonEmptyProfileString(item["pk"]) || nonEmptyProfileString(item["img"])
	if post.URL == "" || !metadata {
		post.Error = "Dataset item lacks recognizable Profile post metadata"
		return post, false
	}
	ownerKnown := true
	if len(usernames) > 1 {
		ownerKnown = false
		for _, username := range usernames {
			if username == post.OwnerUsername {
				ownerKnown = true
			}
		}
	} else if post.OwnerUsername != "" && post.OwnerUsername != usernames[0] {
		ownerKnown = false
	}
	if !ownerKnown {
		post.Error = "Post owner is missing or does not match a requested account"
		return post, false
	}
	post.Status = "success"
	return post, true
}

func nonEmptyProfileString(value any) bool {
	text, ok := value.(string)
	return ok && strings.TrimSpace(text) != ""
}
