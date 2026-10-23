package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/apismith-labs/instagram-reels-transcript-api/examples/go/transcriptapi"
)

type fakeJournal struct{ err error }

func (j fakeJournal) Append(context.Context, transcriptapi.JournalEntry) error { return j.err }

type fakeHTTP struct{ posts int }

func (f *fakeHTTP) RoundTrip(r *http.Request) (*http.Response, error) {
	if r.Method == http.MethodPost {
		f.posts++
	}
	return nil, errors.New("unexpected transport call")
}

func baseEnv() map[string]string {
	return map[string]string{"APIFY_TOKEN": "synthetic-token", "APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD": "1", "APIFY_MAX_TOTAL_CHARGE_USD": "0.30"}
}

func TestCLIHelpAndBadInputsDoNotReadCredentialsOrPost(t *testing.T) {
	for _, args := range [][]string{{"--help"}, {}, {"not-a-url"}, {"[reel](https://instagram.com/reel/x/)"}, {"https://instagram.com/reel/x/", "extra"}, {"--resume=", "https://instagram.com/reel/x/"}} {
		reads := 0
		posts := &fakeHTTP{}
		var stdout, stderr bytes.Buffer
		code := run(args, dependencies{getenv: func(string) string { reads++; return "secret" }, stdout: &stdout, stderr: &stderr,
			transport: &http.Client{Transport: posts}, journal: fakeJournal{}})
		if reads != 0 {
			t.Errorf("args %v read environment %d times", args, reads)
		}
		help := len(args) == 1 && args[0] == "--help"
		if help && code != 0 {
			t.Errorf("help exit=%d", code)
		}
		if !help && code != 2 {
			t.Errorf("args %v exit=%d", args, code)
		}
		if posts.posts != 0 {
			t.Errorf("args %v posted", args)
		}
	}
}

func TestCLIRequiresConfiguredCapBeforeAnyRequest(t *testing.T) {
	for _, env := range []map[string]string{
		{"APIFY_TOKEN": "synthetic-token", "APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD": "1"},
		{"APIFY_TOKEN": "synthetic-token", "APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD": "1", "APIFY_MAX_TOTAL_CHARGE_USD": "NaN"},
	} {
		posts := &fakeHTTP{}
		var stderr bytes.Buffer
		code := run([]string{"https://instagram.com/reel/x/"}, dependencies{getenv: func(key string) string { return env[key] },
			stderr: &stderr, transport: &http.Client{Transport: posts}, journal: fakeJournal{}})
		if code != 2 || posts.posts != 0 {
			t.Fatalf("code=%d posts=%d error=%s", code, posts.posts, stderr.String())
		}
	}
}

func TestCLIMissingTokenFailsBeforeJournalOrTransport(t *testing.T) {
	posts := &fakeHTTP{}
	journalCalled := false
	var stderr bytes.Buffer
	code := run([]string{"https://instagram.com/reel/x/"}, dependencies{
		getenv: func(string) string { return "" }, stderr: &stderr, transport: &http.Client{Transport: posts},
		journal: journalFunc(func(context.Context, transcriptapi.JournalEntry) error { journalCalled = true; return nil }),
	})
	if code != 2 || posts.posts != 0 || journalCalled || !strings.Contains(stderr.String(), "APIFY_TOKEN is required") {
		t.Fatalf("code=%d posts=%d journal=%v stderr=%s", code, posts.posts, journalCalled, stderr.String())
	}
}

type journalFunc func(context.Context, transcriptapi.JournalEntry) error

func (f journalFunc) Append(ctx context.Context, entry transcriptapi.JournalEntry) error {
	return f(ctx, entry)
}

func TestCLIOnlyUsesInjectedEnvironmentAndDoesNotLoadDotEnv(t *testing.T) {
	env := baseEnv()
	posts := &fakeHTTP{}
	var stdout, stderr bytes.Buffer
	code := run([]string{"--output-dir", t.TempDir(), "https://instagram.com/reel/x/"}, dependencies{
		getenv: func(key string) string { return env[key] }, stdout: &stdout, stderr: &stderr, transport: &http.Client{Transport: posts},
		journal: fakeJournal{}, writeResult: func(_ string, result transcriptapi.Result, _ time.Time) (string, error) {
			if result.Status != transcriptapi.StatusCreationUnknown {
				t.Fatalf("unexpected result: %+v", result)
			}
			return "synthetic-result.json", nil
		},
	})
	if code != transcriptapi.ExitCode(transcriptapi.StatusCreationUnknown) || posts.posts != 1 {
		t.Fatalf("code=%d posts=%d", code, posts.posts)
	}
	if strings.Contains(stdout.String(), "synthetic-token") || strings.Contains(stderr.String(), "synthetic-token") {
		t.Fatal("credential leaked")
	}
}

func TestSummaryJSONShape(t *testing.T) {
	var buf bytes.Buffer
	value := cliOutput{Result: transcriptapi.Result{Status: transcriptapi.StatusEmpty, ActorID: transcriptapi.DefaultActorID,
		Segments: []transcriptapi.Segment{}, RawItems: []any{}, DatasetComplete: true}, OutputFile: "output.json"}
	if err := json.NewEncoder(&buf).Encode(value); err != nil {
		t.Fatal(err)
	}
	var parsed map[string]any
	if err := json.Unmarshal(buf.Bytes(), &parsed); err != nil {
		t.Fatal(err)
	}
	if parsed["status"] != "empty" || parsed["datasetComplete"] != true {
		t.Fatalf("summary %v", parsed)
	}
}
