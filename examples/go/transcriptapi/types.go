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
	HTTPClient        HTTPDoer
	Journal           Journal
	Sleep             func(context.Context, time.Duration) error
	Now               func() time.Time
	PollInterval      time.Duration
	MaxPolls          int
	DatasetLimit      int
}

// HTTPDoer permits tests and callers to inject a transport without global state.
type HTTPDoer interface {
	Do(*http.Request) (*http.Response, error)
}

type Journal interface {
	Append(context.Context, JournalEntry) error
}

type JournalEntry struct {
	At                time.Time `json:"at"`
	Stage             string    `json:"stage"`
	ActorID           string    `json:"actorId"`
	SourceURL         string    `json:"sourceUrl"`
	RunID             string    `json:"runId,omitempty"`
	DatasetID         string    `json:"datasetId,omitempty"`
	RunStatus         string    `json:"runStatus,omitempty"`
	BuildNumber       string    `json:"buildNumber,omitempty"`
	BuildID           string    `json:"buildId,omitempty"`
	BuildVerification string    `json:"buildVerification,omitempty"`
	MaxTotalChargeUSD *float64  `json:"maxTotalChargeUsd,omitempty"`
	RestartOnError    bool      `json:"restartOnError"`
	Error             string    `json:"error,omitempty"`
}

type Segment map[string]any

type Result struct {
	Status            Status           `json:"status"`
	RunStatus         string           `json:"runStatus,omitempty"`
	RunID             string           `json:"runId,omitempty"`
	DatasetID         string           `json:"datasetId,omitempty"`
	SourceURL         string           `json:"sourceUrl"`
	ActorID           string           `json:"actorId"`
	BuildNumber       string           `json:"buildNumber,omitempty"`
	BuildID           string           `json:"buildId,omitempty"`
	BuildVerification string           `json:"buildVerification"`
	DatasetComplete   bool             `json:"datasetComplete"`
	Text              string           `json:"text,omitempty"`
	Segments          []Segment        `json:"segments"`
	RawItems          []map[string]any `json:"rawItems"`
	Error             string           `json:"error,omitempty"`
	Stage             string           `json:"stage,omitempty"`
	Cause             error            `json:"-"`
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
