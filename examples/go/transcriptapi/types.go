package transcriptapi

import (
	"context"
	"errors"
	"net/http"
	"time"
)

const (
	ControlledBuildNumber = "0.0.50"
	ControlledBuildID     = "aJLRmMdQapLQRT4sJ"
	DefaultActorID        = "apple_yang/instagram-transcripts-scraper"
	DefaultDatasetLimit   = 1000
)

type Status string

const (
	StatusSuccess         Status = "success"
	StatusActorError      Status = "actor_error"
	StatusEmpty           Status = "empty"
	StatusNoTranscript    Status = "no_transcript"
	StatusUnknown         Status = "unknown"
	StatusTransportError  Status = "transport_error"
	StatusRunFailed       Status = "run_failed"
	StatusCreationUnknown Status = "creation_unknown"
)

type ErrorKind string

const (
	ErrorConfiguration ErrorKind = "configuration"
	ErrorInput         ErrorKind = "input"
	ErrorProtocol      ErrorKind = "protocol"
	ErrorTransport     ErrorKind = "transport"
	ErrorCreation      ErrorKind = "creation_unknown"
	ErrorJournal       ErrorKind = "journal"
)

// Error describes a safe, classifiable failure. Error text never includes response bodies.
type Error struct {
	Kind  ErrorKind
	Stage string
	Err   error
}

func (e *Error) Error() string {
	if e == nil {
		return ""
	}
	if e.Err == nil {
		return string(e.Kind) + " at " + e.Stage
	}
	return string(e.Kind) + " at " + e.Stage + ": " + e.Err.Error()
}

func (e *Error) Unwrap() error { return e.Err }

type Config struct {
	Token             string
	ActorID           string
	BuildNumber       string
	BuildID           string
	MaxTotalChargeUSD float64
	RequireChargeCap  bool
	// HTTPClient supports standard net/http redirects. Run creation uses a copy
	// with redirect following disabled; custom RoundTrippers must perform one
	// exchange and must not implement their own redirect loop.
	HTTPClient   *http.Client
	Journal      Journal
	Sleep        func(context.Context, time.Duration) error
	Now          func() time.Time
	PollInterval time.Duration
	MaxPolls     int
	DatasetLimit int
}

type Journal interface {
	Append(context.Context, JournalEntry) error
}

type JournalReader interface {
	ReadEntries(context.Context) ([]JournalEntry, error)
}

type JournalEntry struct {
	At                time.Time            `json:"at"`
	Stage             string               `json:"stage"`
	ActorID           string               `json:"actorId"`
	SourceURL         string               `json:"sourceUrl"`
	RunID             string               `json:"runId,omitempty"`
	RunActorID        string               `json:"runActorId,omitempty"`
	DatasetID         string               `json:"datasetId,omitempty"`
	RunStatus         string               `json:"runStatus,omitempty"`
	BuildNumber       string               `json:"buildNumber,omitempty"`
	BuildID           string               `json:"buildId,omitempty"`
	BuildVerification string               `json:"buildVerification,omitempty"`
	MaxTotalChargeUSD *float64             `json:"maxTotalChargeUsd,omitempty"`
	RestartOnError    bool                 `json:"restartOnError"`
	InputContext      *JournalInputContext `json:"inputContext,omitempty"`
	Error             string               `json:"error,omitempty"`
}

// JournalInputContext binds a persisted Run to the exact mode and Actor input.
// It is optional so existing JSONL records remain readable.
type JournalInputContext struct {
	Mode  string `json:"mode"`
	Input any    `json:"input"`
}

type Segment map[string]any

type Result struct {
	Status                  Status    `json:"status"`
	RunStatus               string    `json:"runStatus,omitempty"`
	RunID                   string    `json:"runId,omitempty"`
	DatasetID               string    `json:"datasetId,omitempty"`
	SourceURL               string    `json:"sourceUrl"`
	ActorID                 string    `json:"actorId"`
	BuildNumber             string    `json:"buildNumber,omitempty"`
	BuildID                 string    `json:"buildId,omitempty"`
	BuildVerification       string    `json:"buildVerification"`
	DatasetComplete         bool      `json:"datasetComplete"`
	Text                    string    `json:"text,omitempty"`
	Segments                []Segment `json:"segments"`
	RawItems                []any     `json:"rawItems"`
	AttributionVerification string    `json:"attributionVerification"`
	Error                   string    `json:"error,omitempty"`
	Stage                   string    `json:"stage,omitempty"`
	Cause                   error     `json:"-"`
}

var (
	ErrInvalidURL = errors.New("URL must be an HTTPS Instagram Reel or post URL without query or fragment")
	ErrNoJournal  = errors.New("a persistent Journal is required before creating an Actor Run")
)

func ExitCode(status Status) int {
	switch status {
	case StatusSuccess:
		return 0
	case StatusActorError:
		return 4
	case StatusEmpty:
		return 5
	case StatusNoTranscript:
		return 6
	case StatusUnknown:
		return 7
	case StatusTransportError:
		return 8
	case StatusRunFailed:
		return 9
	case StatusCreationUnknown:
		return 10
	default:
		return 8
	}
}

type BulkStatus string

const (
	BulkAllSuccess     BulkStatus = "all_success"
	BulkPartialSuccess BulkStatus = "partial_success"
	BulkAllFailed      BulkStatus = "all_failed"
	BulkUnknown        BulkStatus = "unknown"
)

type BulkItemStatus string

const (
	BulkItemSuccessTranscript BulkItemStatus = "success_transcript"
	BulkItemActorError        BulkItemStatus = "actor_error"
	BulkItemNoTranscript      BulkItemStatus = "no_transcript"
	BulkItemMissingResult     BulkItemStatus = "missing_result"
	BulkItemDuplicateResult   BulkItemStatus = "duplicate_result"
	BulkItemUnknown           BulkItemStatus = "unknown"
)

type BulkRequest struct {
	URLs               []string
	ResultsLimit       *int
	SkipPinnedPosts    *bool
	IncludeSharesCount *bool
}

type BulkInputResult struct {
	InputURL                string         `json:"inputUrl"`
	Status                  BulkItemStatus `json:"status"`
	Text                    string         `json:"text,omitempty"`
	Segments                []Segment      `json:"segments"`
	Items                   []any          `json:"items"`
	AttributionVerification string         `json:"attributionVerification"`
	Error                   string         `json:"error,omitempty"`
}

type ExtraResult struct {
	Reason string `json:"reason"`
	Item   any    `json:"item"`
}

type BulkCounts struct {
	SuccessTranscript int `json:"success_transcript"`
	ActorError        int `json:"actor_error"`
	NoTranscript      int `json:"no_transcript"`
	MissingResult     int `json:"missing_result"`
	DuplicateResult   int `json:"duplicate_result"`
	Unknown           int `json:"unknown"`
}

type BulkResult struct {
	Status            BulkStatus        `json:"status"`
	ExecutionStatus   Status            `json:"executionStatus"`
	Inputs            []BulkInputResult `json:"inputs"`
	ExtraResults      []ExtraResult     `json:"extraResults"`
	Counts            BulkCounts        `json:"counts"`
	URLs              []string          `json:"urls"`
	RunID             string            `json:"runId,omitempty"`
	DatasetID         string            `json:"datasetId,omitempty"`
	RunStatus         string            `json:"runStatus,omitempty"`
	ActorID           string            `json:"actorId"`
	BuildNumber       string            `json:"buildNumber,omitempty"`
	BuildID           string            `json:"buildId,omitempty"`
	BuildVerification string            `json:"buildVerification"`
	DatasetComplete   bool              `json:"datasetComplete"`
	RawItems          []any             `json:"rawItems"`
	Error             string            `json:"error,omitempty"`
	Stage             string            `json:"stage,omitempty"`
	Cause             error             `json:"-"`
}

func BulkExitCode(result BulkResult) int {
	if result.ExecutionStatus != StatusSuccess && result.Status == BulkUnknown {
		return ExitCode(result.ExecutionStatus)
	}
	switch result.Status {
	case BulkAllSuccess:
		return 0
	case BulkPartialSuccess:
		return 11
	case BulkAllFailed:
		return 12
	default:
		return 13
	}
}

type ProfileRequest struct {
	Usernames          []string
	ResultsLimit       *int
	OnlyPostsNewerThan string
	SkipPinnedPosts    *bool
	IncludeSharesCount *bool
}

type ProfileStatus string

const (
	ProfileSuccess    ProfileStatus = "success"
	ProfileEmpty      ProfileStatus = "empty"
	ProfileActorError ProfileStatus = "actor_error"
	ProfileUnknown    ProfileStatus = "unknown"
)

type ProfilePost struct {
	URL           string `json:"url,omitempty"`
	Type          string `json:"type,omitempty"`
	OwnerUsername string `json:"ownerUsername,omitempty"`
	Caption       string `json:"caption,omitempty"`
	Timestamp     any    `json:"timestamp,omitempty"`
	VideoURL      string `json:"videoUrl,omitempty"`
	VideoDuration any    `json:"videoDuration,omitempty"`
	Status        string `json:"status"`
	Error         string `json:"error,omitempty"`
	Raw           any    `json:"raw"`
}

type ProfileResult struct {
	Status            ProfileStatus `json:"status"`
	ExecutionStatus   Status        `json:"executionStatus"`
	Usernames         []string      `json:"usernames"`
	Posts             []ProfilePost `json:"posts"`
	RawItems          []any         `json:"rawItems"`
	RunID             string        `json:"runId,omitempty"`
	DatasetID         string        `json:"datasetId,omitempty"`
	RunStatus         string        `json:"runStatus,omitempty"`
	ActorID           string        `json:"actorId"`
	BuildNumber       string        `json:"buildNumber,omitempty"`
	BuildID           string        `json:"buildId,omitempty"`
	BuildVerification string        `json:"buildVerification"`
	DatasetComplete   bool          `json:"datasetComplete"`
	Error             string        `json:"error,omitempty"`
	Stage             string        `json:"stage,omitempty"`
	Cause             error         `json:"-"`
}

func ProfileExitCode(result ProfileResult) int {
	if result.ExecutionStatus != StatusSuccess {
		return ExitCode(result.ExecutionStatus)
	}
	switch result.Status {
	case ProfileSuccess, ProfileEmpty:
		return 0
	case ProfileActorError:
		return 4
	default:
		return 7
	}
}

type CSVRowResult struct {
	Row       int       `json:"row"`
	URL       string    `json:"url"`
	Status    Status    `json:"status"`
	RunID     string    `json:"runId,omitempty"`
	DatasetID string    `json:"datasetId,omitempty"`
	Text      string    `json:"text,omitempty"`
	Segments  []Segment `json:"segments"`
	RawItems  []any     `json:"rawItems"`
	Error     string    `json:"error,omitempty"`
}

type CSVBatchResult struct {
	Status          string         `json:"status"`
	Rows            []CSVRowResult `json:"rows"`
	PlannedRows     int            `json:"plannedRows"`
	UnattemptedRows int            `json:"unattemptedRows"`
	Success         int            `json:"success"`
	Failed          int            `json:"failed"`
	Counts          map[Status]int `json:"counts"`
}
