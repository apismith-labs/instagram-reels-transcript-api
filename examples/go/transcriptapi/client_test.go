package transcriptapi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

const testURL = "https://www.instagram.com/reel/synthetic123/"

type memoryJournal struct {
	mu      sync.Mutex
	entries []JournalEntry
	err     error
}

func (j *memoryJournal) Append(ctx context.Context, entry JournalEntry) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	j.mu.Lock()
	defer j.mu.Unlock()
	if j.err != nil {
		return j.err
	}
	j.entries = append(j.entries, entry)
	return nil
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func newClient(t *testing.T, transport http.RoundTripper, journal Journal, extra func(*Config)) *Client {
	t.Helper()
	config := Config{Token: "synthetic-token", ActorID: "owner/actor", HTTPClient: &http.Client{Transport: transport},
		Journal: journal, Sleep: func(context.Context, time.Duration) error { return nil },
		DatasetLimit: 5}
	if extra != nil {
		extra(&config)
	}
	client, err := NewClient(config)
	if err != nil {
		t.Fatal(err)
	}
	return client
}

func respond(status int, body string) *http.Response {
	return &http.Response{StatusCode: status, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body))}
}

func TestValidateVideoURL(t *testing.T) {
	valid := []string{
		"https://www.instagram.com/reel/abc_123/",
		"https://instagram.com/reels/abc-123",
		"https://www.instagram.com/p/abc123/",
	}
	for _, raw := range valid {
		got, err := ValidateVideoURL(raw)
		if err != nil || got != raw {
			t.Fatalf("ValidateVideoURL(%q) = %q, %v", raw, got, err)
		}
	}
	invalid := []string{"", " https://www.instagram.com/reel/x/", "http://www.instagram.com/reel/x/",
		"https://instagram.com.evil.test/reel/x/", "https://instagram.com/reel/x/?a=1", "https://instagram.com/reel/x/#frag",
		"https://u:p@instagram.com/reel/x/", "https://instagram.com/stories/x/", "https://instagram.com/reel/a/b/",
		"[link](https://instagram.com/reel/x/)", "https://instagram.com/reel/has space/"}
	for _, raw := range invalid {
		if _, err := ValidateVideoURL(raw); err == nil {
			t.Errorf("ValidateVideoURL(%q) unexpectedly succeeded", raw)
		}
	}
}

func TestNewClientConfigurationFailsBeforeTransport(t *testing.T) {
	t.Setenv("APIFY_TOKEN", "synthetic-environment-token")
	base := Config{Token: "synthetic", Journal: &memoryJournal{}}
	for _, change := range []func(*Config){
		func(c *Config) { c.Token = " " },
		func(c *Config) { c.RequireChargeCap = true },
		func(c *Config) { c.RequireChargeCap = true; c.MaxTotalChargeUSD = 0 },
		func(c *Config) { c.RequireChargeCap = true; c.MaxTotalChargeUSD = 0.3; c.BuildID = "wrong" },
	} {
		config := base
		change(&config)
		if _, err := NewClient(config); err == nil {
			t.Error("expected configuration error")
		}
	}
	if _, err := NewClient(Config{Token: "synthetic"}); err == nil || !errors.Is(err, ErrNoJournal) {
		t.Fatalf("expected journal requirement, got %v", err)
	}
	if _, err := NewClient(Config{Journal: &memoryJournal{}}); err == nil {
		t.Fatal("NewClient unexpectedly read APIFY_TOKEN from process environment")
	}
}

func TestInvalidURLAndIntentJournalFailureCauseZeroPOST(t *testing.T) {
	posts := 0
	transport := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.Method == http.MethodPost {
			posts++
		}
		return nil, errors.New("unexpected request")
	})
	journal := &memoryJournal{}
	client := newClient(t, transport, journal, nil)
	if got := client.GetTranscript(context.Background(), "not a URL"); got.Status != StatusTransportError || posts != 0 || len(journal.entries) != 0 {
		t.Fatalf("invalid URL made progress: %+v posts=%d", got, posts)
	} else {
		var typed *Error
		if !errors.As(got.Cause, &typed) || typed.Kind != ErrorInput {
			t.Fatalf("invalid URL lacks typed input error: %+v", got.Cause)
		}
	}
	journal.err = errors.New("disk full")
	if got := client.GetTranscript(context.Background(), testURL); got.Status != StatusTransportError || posts != 0 {
		t.Fatalf("intent journal failure did not fail closed: %+v posts=%d", got, posts)
	}
}

func TestRunCreationQueryInputAndNoRetryOn4295xxOrNetworkFailure(t *testing.T) {
	for _, scenario := range []struct {
		name       string
		wantStatus Status
		fn         roundTripFunc
	}{
		{"429", StatusCreationUnknown, func(r *http.Request) (*http.Response, error) { return respond(429, `{"error":"do not expose"}`), nil }},
		{"5xx", StatusCreationUnknown, func(r *http.Request) (*http.Response, error) { return respond(503, "secret body"), nil }},
		{"network", StatusCreationUnknown, func(r *http.Request) (*http.Response, error) { return nil, errors.New("connection reset") }},
		{"cap rejected", StatusTransportError, func(r *http.Request) (*http.Response, error) { return respond(400, "cap rejected"), nil }},
	} {
		t.Run(scenario.name, func(t *testing.T) {
			posts := 0
			transport := roundTripFunc(func(r *http.Request) (*http.Response, error) {
				posts++
				if r.Method != http.MethodPost {
					t.Fatalf("unexpected method %s", r.Method)
				}
				query, _ := url.ParseQuery(r.URL.RawQuery)
				if query.Get("build") != ControlledBuildNumber || query.Get("restartOnError") != "false" || query.Get("maxTotalChargeUsd") != "0.3" {
					t.Fatalf("wrong Run query: %v", query)
				}
				var input map[string]any
				if err := json.NewDecoder(r.Body).Decode(&input); err != nil {
					t.Fatal(err)
				}
				if len(input) != 1 || input["videoUrl"] != testURL {
					t.Fatalf("wrong actor input: %v", input)
				}
				if r.Header.Get("Authorization") != "Bearer synthetic-token" {
					t.Fatal("authorization header missing")
				}
				return scenario.fn(r)
			})
			journal := &memoryJournal{}
			client := newClient(t, transport, journal, func(c *Config) { c.RequireChargeCap = true; c.MaxTotalChargeUSD = 0.3 })
			got := client.GetTranscript(context.Background(), testURL)
			if posts != 1 || got.Status != scenario.wantStatus {
				t.Fatalf("status=%s want=%s posts=%d", got.Status, scenario.wantStatus, posts)
			}
			wantStage := "run_create_unknown"
			if scenario.wantStatus == StatusTransportError {
				wantStage = "run_create_rejected"
			}
			if len(journal.entries) != 2 || journal.entries[1].Stage != wantStage {
				t.Fatalf("journal=%+v", journal.entries)
			}
			if journal.entries[0].RestartOnError || journal.entries[1].RestartOnError {
				t.Fatalf("Journal recorded restartOnError=true: %+v", journal.entries)
			}
			if strings.Contains(got.Error, "do not expose") || strings.Contains(got.Error, "secret body") {
				t.Fatalf("response body leaked: %q", got.Error)
			}
		})
	}
}

func TestSuccessfulRunVerifiesBuildClassifiesTranscriptAndDatasetCompleteness(t *testing.T) {
	for _, scenario := range []struct {
		name       string
		buildNum   string
		buildID    string
		items      string
		wantStatus Status
		complete   bool
	}{
		{"success", ControlledBuildNumber, ControlledBuildID, `[{"text":"transcribed","segments":[{"start":0,"end":1,"text":"x"}]}]`, StatusSuccess, true},
		{"empty", ControlledBuildNumber, ControlledBuildID, `[]`, StatusEmpty, true},
		{"no transcript", ControlledBuildNumber, ControlledBuildID, `[{"title":"metadata"}]`, StatusNoTranscript, true},
		{"actor error", ControlledBuildNumber, ControlledBuildID, `[{"errMsg":"synthetic failure"}]`, StatusActorError, true},
		{"incomplete", ControlledBuildNumber, ControlledBuildID, `[{"text":"transcribed","segments":[]},{"text":"extra"},{"text":"extra"},{"text":"extra"},{"text":"extra"}]`, StatusUnknown, false},
		{"build number mismatch", "0.0.51", ControlledBuildID, `[{"text":"should not read"}]`, StatusTransportError, false},
		{"build id mismatch", ControlledBuildNumber, "wrong-build-id", `[{"text":"should not read"}]`, StatusTransportError, false},
	} {
		t.Run(scenario.name, func(t *testing.T) {
			posts, datasets := 0, 0
			transport := roundTripFunc(func(r *http.Request) (*http.Response, error) {
				switch {
				case r.Method == http.MethodPost:
					posts++
					query, _ := url.ParseQuery(r.URL.RawQuery)
					if query.Get("restartOnError") != "false" || query.Get("build") != ControlledBuildNumber || query.Get("maxTotalChargeUsd") != "0.3" {
						t.Fatalf("query %v", query)
					}
					var input map[string]any
					_ = json.NewDecoder(r.Body).Decode(&input)
					if len(input) != 1 || input["videoUrl"] != testURL {
						t.Fatalf("input %v", input)
					}
					return respond(201, fmt.Sprintf(`{"data":{"id":"run-1","defaultDatasetId":"ds-1","buildNumber":%q,"buildId":%q}}`, ControlledBuildNumber, ControlledBuildID)), nil
				case strings.HasSuffix(r.URL.Path, "/items"):
					datasets++
					if r.URL.Query().Get("limit") != "5" {
						t.Fatalf("Dataset limit missing: %v", r.URL.Query())
					}
					return respond(200, scenario.items), nil
				default:
					return respond(200, fmt.Sprintf(`{"data":{"id":"run-1","status":"SUCCEEDED","defaultDatasetId":"ds-1","buildNumber":%q,"buildId":%q}}`, scenario.buildNum, scenario.buildID)), nil
				}
			})
			journal := &memoryJournal{}
			client := newClient(t, transport, journal, func(c *Config) { c.RequireChargeCap = true; c.MaxTotalChargeUSD = 0.3 })
			got := client.GetTranscript(context.Background(), testURL)
			if posts != 1 {
				t.Fatalf("POST count %d", posts)
			}
			if got.Status != scenario.wantStatus {
				t.Fatalf("status=%s want=%s error=%s", got.Status, scenario.wantStatus, got.Error)
			}
			if scenario.wantStatus == StatusTransportError {
				if datasets != 0 || got.RunID != "run-1" || got.DatasetID != "ds-1" || got.BuildVerification != "mismatch" {
					t.Fatalf("mismatch evidence lost: %+v", got)
				}
				return
			}
			if got.DatasetComplete != scenario.complete {
				t.Fatalf("complete=%v want=%v", got.DatasetComplete, scenario.complete)
			}
			if got.RunID != "run-1" || got.DatasetID != "ds-1" || got.BuildVerification != "verified" || got.RunStatus != "SUCCEEDED" {
				t.Fatalf("identity missing: %+v", got)
			}
			if got.Status == StatusSuccess && (got.Text != "transcribed" || len(got.Segments) != 1 || len(got.RawItems) != 1) {
				t.Fatalf("transcript missing: %+v", got)
			}
		})
	}
}

func TestMalformedDatasetIsNotMisreportedAsEmpty(t *testing.T) {
	posts := 0
	transport := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		switch {
		case r.Method == http.MethodPost:
			posts++
			return respond(201, `{"data":{"id":"r","defaultDatasetId":"d","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`), nil
		case strings.HasSuffix(r.URL.Path, "/items"):
			return respond(200, "null"), nil
		default:
			return respond(200, `{"data":{"id":"r","status":"SUCCEEDED","defaultDatasetId":"d","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`), nil
		}
	})
	got := newClient(t, transport, &memoryJournal{}, nil).GetTranscript(context.Background(), testURL)
	if posts != 1 || got.Status != StatusTransportError || got.Stage != "dataset_read" || got.RunID != "r" {
		t.Fatalf("malformed Dataset became a business success: %+v posts=%d", got, posts)
	}
}

func TestMalformedTranscriptFieldsAreUnknown(t *testing.T) {
	for _, item := range []map[string]any{{"text": 7}, {"errMsg": 7}, {"text": "valid", "segments": "not-an-array"}} {
		status, _, _, _, _ := classifyItems([]any{item}, true, testURL)
		if status != StatusUnknown {
			t.Errorf("item %#v got status %s", item, status)
		}
	}
}

func TestRunFailureContextCancellationAndCreationUnknownMalformed(t *testing.T) {
	t.Run("run failed", func(t *testing.T) {
		posts := 0
		transport := roundTripFunc(func(r *http.Request) (*http.Response, error) {
			if r.Method == http.MethodPost {
				posts++
				return respond(201, `{"data":{"id":"r","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`), nil
			}
			return respond(200, `{"data":{"id":"r","status":"FAILED","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`), nil
		})
		got := newClient(t, transport, &memoryJournal{}, nil).GetTranscript(context.Background(), testURL)
		if got.Status != StatusRunFailed || posts != 1 {
			t.Fatalf("%+v posts=%d", got, posts)
		}
	})
	t.Run("malformed post response", func(t *testing.T) {
		posts := 0
		transport := roundTripFunc(func(r *http.Request) (*http.Response, error) { posts++; return respond(201, "not json"), nil })
		got := newClient(t, transport, &memoryJournal{}, nil).GetTranscript(context.Background(), testURL)
		if got.Status != StatusCreationUnknown || posts != 1 {
			t.Fatalf("%+v posts=%d", got, posts)
		}
	})
	t.Run("context canceled before intent", func(t *testing.T) {
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		posts := 0
		transport := roundTripFunc(func(r *http.Request) (*http.Response, error) { posts++; return nil, context.Canceled })
		got := newClient(t, transport, &memoryJournal{}, nil).GetTranscript(ctx, testURL)
		if got.Status != StatusTransportError || posts != 0 {
			t.Fatalf("%+v posts=%d", got, posts)
		}
	})
	t.Run("canceled post outcome is unknown", func(t *testing.T) {
		posts := 0
		transport := roundTripFunc(func(r *http.Request) (*http.Response, error) { posts++; return nil, context.Canceled })
		got := newClient(t, transport, &memoryJournal{}, nil).GetTranscript(context.Background(), testURL)
		var typed *Error
		if got.Status != StatusCreationUnknown || posts != 1 || !errors.As(got.Cause, &typed) || typed.Kind != ErrorCreation {
			t.Fatalf("%+v posts=%d typed=%+v", got, posts, typed)
		}
	})
}

func TestJournalWriteFailureBeforeAndAfterPOSTIsFailClosed(t *testing.T) {
	t.Run("intent", func(t *testing.T) {
		posts := 0
		journal := &memoryJournal{err: errors.New("disk unavailable")}
		client := newClient(t, roundTripFunc(func(r *http.Request) (*http.Response, error) { posts++; return respond(201, "{}"), nil }), journal, nil)
		got := client.GetTranscript(context.Background(), testURL)
		if got.Status != StatusTransportError || posts != 0 {
			t.Fatalf("%+v posts=%d", got, posts)
		}
	})
	t.Run("run id persistence", func(t *testing.T) {
		posts := 0
		journal := &failAfterJournal{failAt: 2}
		transport := roundTripFunc(func(r *http.Request) (*http.Response, error) {
			posts++
			return respond(201, `{"data":{"id":"known-run","defaultDatasetId":"known-dataset"}}`), nil
		})
		got := newClient(t, transport, journal, nil).GetTranscript(context.Background(), testURL)
		if got.Status != StatusTransportError || got.RunID != "known-run" || got.DatasetID != "known-dataset" || posts != 1 {
			t.Fatalf("%+v posts=%d", got, posts)
		}
	})
}

type failAfterJournal struct{ count, failAt int }

func (j *failAfterJournal) Append(context.Context, JournalEntry) error {
	j.count++
	if j.count == j.failAt {
		return errors.New("injected journal failure")
	}
	return nil
}

func TestJSONLJournalIsAppendOnlyPrivateAndDoesNotSerializeSecrets(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "nested", "journal.jsonl")
	journal, err := OpenJSONLJournal(path)
	if err != nil {
		t.Fatal(err)
	}
	defer journal.Close()
	if err := journal.Append(context.Background(), JournalEntry{Stage: "intent", ActorID: "synthetic", SourceURL: testURL, RestartOnError: false}); err != nil {
		t.Fatal(err)
	}
	if err := journal.Append(context.Background(), JournalEntry{Stage: "complete", RunID: "run"}); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), "synthetic-token") || strings.Contains(string(data), "Authorization") {
		t.Fatal("journal contains credential data")
	}
	if lines := strings.Count(strings.TrimSpace(string(data)), "\n") + 1; lines != 2 {
		t.Fatalf("got %d journal lines", lines)
	}
	if runtimePerm := fileMode(path); runtimePerm&0o777 != 0o600 {
		t.Fatalf("journal mode %#o", runtimePerm&0o777)
	}
}

func TestJSONLJournalSerializesConcurrentAppends(t *testing.T) {
	path := filepath.Join(t.TempDir(), "journal.jsonl")
	journal, err := OpenJSONLJournal(path)
	if err != nil {
		t.Fatal(err)
	}
	const writers = 40
	var wg sync.WaitGroup
	errCh := make(chan error, writers)
	for i := 0; i < writers; i++ {
		wg.Add(1)
		go func(n int) {
			defer wg.Done()
			errCh <- journal.Append(context.Background(), JournalEntry{Stage: fmt.Sprintf("entry-%d", n)})
		}(i)
	}
	wg.Wait()
	close(errCh)
	for err := range errCh {
		if err != nil {
			t.Fatal(err)
		}
	}
	if err := journal.Close(); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Count(strings.TrimSpace(string(data)), "\n") + 1; got != writers {
		t.Fatalf("journal lines=%d want=%d", got, writers)
	}
}

func fileMode(path string) os.FileMode {
	info, err := os.Stat(path)
	if err != nil {
		return 0
	}
	return info.Mode()
}

func TestUniqueOutputPreservesExistingFile(t *testing.T) {
	dir := t.TempDir()
	now := time.Date(2026, 10, 22, 0, 0, 0, 0, time.UTC)
	result := Result{Status: StatusSuccess, Segments: []Segment{}, RawItems: []any{}}
	first, err := WriteResultUnique(dir, result, now)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(first, []byte("sentinel"), 0o600); err != nil {
		t.Fatal(err)
	}
	second, err := WriteResultUnique(dir, result, now)
	if err != nil {
		t.Fatal(err)
	}
	if first == second {
		t.Fatal("output path was reused")
	}
	data, err := os.ReadFile(first)
	if err != nil || string(data) != "sentinel" {
		t.Fatal("existing output was overwritten")
	}
	if fileMode(second)&0o777 != 0o600 {
		t.Fatalf("output mode %#o", fileMode(second)&0o777)
	}
}

func TestHTTPEndToEndUsingOfflineRecorderTransport(t *testing.T) {
	posts := 0
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer synthetic-token" {
			t.Errorf("missing auth header")
		}
		switch {
		case r.Method == http.MethodPost:
			posts++
			if r.URL.Query().Get("restartOnError") != "false" || r.URL.Query().Get("build") != ControlledBuildNumber {
				t.Errorf("query %v", r.URL.Query())
			}
			w.WriteHeader(http.StatusCreated)
			_, _ = io.WriteString(w, `{"data":{"id":"run","defaultDatasetId":"dataset","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`)
		case strings.HasSuffix(r.URL.Path, "/items"):
			_, _ = io.WriteString(w, `[{"text":"ok","segments":[]}]`)
		default:
			_, _ = io.WriteString(w, `{"data":{"id":"run","status":"SUCCEEDED","defaultDatasetId":"dataset","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`)
		}
	})
	transport := roundTripFunc(func(req *http.Request) (*http.Response, error) {
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, req)
		return recorder.Result(), nil
	})
	client := newClient(t, transport, &memoryJournal{}, nil)
	got := client.GetTranscript(context.Background(), testURL)
	if got.Status != StatusSuccess || posts != 1 {
		t.Fatalf("%+v posts=%d", got, posts)
	}
}

func TestRunCreationRedirectsNeverReplayPOSTOrFollowLocation(t *testing.T) {
	for _, scenario := range []struct {
		code int
		name string
	}{
		{http.StatusMovedPermanently, "301"},
		{http.StatusFound, "302"},
		{http.StatusSeeOther, "303"},
		{http.StatusTemporaryRedirect, "307"},
		{http.StatusPermanentRedirect, "308"},
	} {
		for _, injected := range []bool{false, true} {
			name := "default-client"
			if injected {
				name = "injected-client"
			}
			t.Run(scenario.name+"/"+name, func(t *testing.T) {
				createRequests, targetRequests := 0, 0
				transport := roundTripFunc(func(r *http.Request) (*http.Response, error) {
					if r.URL.Host == "other.synthetic" {
						targetRequests++
						return respond(http.StatusOK, "unexpected redirect request"), nil
					}
					createRequests++
					if r.Method != http.MethodPost {
						t.Errorf("creation request method=%s", r.Method)
					}
					response := respond(scenario.code, "redirect response")
					response.Header.Set("Location", "https://other.synthetic/redirect-target")
					return response, nil
				})
				journal := &memoryJournal{}
				config := Config{Token: "synthetic-token", ActorID: "owner/actor", Journal: journal,
					Sleep: func(context.Context, time.Duration) error { return nil }}
				if injected {
					config.HTTPClient = &http.Client{Timeout: time.Second, Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error {
						t.Error("caller's redirect policy must not be used for creation POSTs")
						return nil
					}}
				}
				client, err := NewClient(config)
				if err != nil {
					t.Fatal(err)
				}
				if !injected {
					client.client.Transport = transport
					client.createClient.Transport = transport
				}
				client.base = "https://apify.synthetic/v2"
				got := client.GetTranscript(context.Background(), testURL)
				if got.Status != StatusCreationUnknown {
					t.Fatalf("redirect status %d produced %s: %+v", scenario.code, got.Status, got)
				}
				if createRequests != 1 || targetRequests != 0 {
					t.Fatalf("redirect status %d made creation=%d target=%d requests", scenario.code, createRequests, targetRequests)
				}
				if len(journal.entries) != 2 || journal.entries[0].Stage != "intent" || journal.entries[1].Stage != "run_create_unknown" {
					t.Fatalf("redirect reconciliation missing from Journal: %+v", journal.entries)
				}
			})
		}
	}
}

func TestDatasetNonObjectItemsAreUnknownAndPreservedOverHTTP(t *testing.T) {
	for _, scenario := range []struct {
		name, body string
		want       Status
		wantRaw    int
	}{
		{"numbers", `[1,2]`, StatusUnknown, 2},
		{"null", `[null]`, StatusUnknown, 1},
		{"mixed", `[{"url":"https://www.instagram.com/reel/synthetic123/","text":"must not pass"},1]`, StatusUnknown, 2},
		{"invalid json", `[`, StatusTransportError, 0},
		{"trailing data", `[] trailing`, StatusTransportError, 0},
	} {
		t.Run(scenario.name, func(t *testing.T) {
			posts := 0
			transport := roundTripFunc(func(r *http.Request) (*http.Response, error) {
				switch {
				case r.Method == http.MethodPost:
					posts++
					return respond(201, `{"data":{"id":"run","defaultDatasetId":"ds","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`), nil
				case strings.HasSuffix(r.URL.Path, "/items"):
					return respond(200, scenario.body), nil
				default:
					return respond(200, `{"data":{"id":"run","status":"SUCCEEDED","defaultDatasetId":"ds","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`), nil
				}
			})
			got := newClient(t, transport, &memoryJournal{}, nil).GetTranscript(context.Background(), testURL)
			if got.Status != scenario.want || got.RunID != "run" || posts != 1 {
				t.Fatalf("status=%s run=%q posts=%d, want=%s", got.Status, got.RunID, posts, scenario.want)
			}
			if len(got.RawItems) != scenario.wantRaw {
				t.Fatalf("raw item count=%d want=%d; items=%#v", len(got.RawItems), scenario.wantRaw, got.RawItems)
			}
			if scenario.name == "numbers" && got.RawItems[0] != json.Number("1") {
				t.Fatalf("numeric raw item was not preserved: %#v", got.RawItems[0])
			}
			if scenario.name == "null" && got.RawItems[0] != nil {
				t.Fatalf("null raw item was not preserved: %#v", got.RawItems[0])
			}
			if scenario.name == "mixed" && got.Text != "" {
				t.Fatalf("transcript from mixed malformed Dataset was exposed: %q", got.Text)
			}
		})
	}
}

func TestSingleURLAttributionIsConservative(t *testing.T) {
	matching := `https://www.instagram.com/reel/synthetic123/`
	for _, scenario := range []struct {
		name, items, wantStatus, wantVerification string
		wantText                                  string
	}{
		{"exact", `[{"url":"` + matching + `","text":"matched"}]`, string(StatusSuccess), "verified", "matched"},
		{"host alias", `[{"url":"https://instagram.com/reel/synthetic123/","text":"matched"}]`, string(StatusSuccess), "verified", "matched"},
		{"reels alias", `[{"url":"https://instagram.com/reels/synthetic123/","text":"matched"}]`, string(StatusSuccess), "verified", "matched"},
		{"different work", `[{"url":"https://instagram.com/reel/different/","text":"foreign transcript"}]`, string(StatusUnknown), "mismatch", ""},
		{"missing URL", `[{"text":"legacy shape"}]`, string(StatusSuccess), "unverified", "legacy shape"},
		{"invalid URL", `[{"url":"not-a-url","text":"must not pass"}]`, string(StatusUnknown), "unknown", ""},
		{"wrong URL type", `[{"url":7,"text":"must not pass"}]`, string(StatusUnknown), "unknown", ""},
		{"multiple with mismatch", `[{"url":"` + matching + `","text":"first"},{"url":"https://instagram.com/reel/other/","text":"foreign"}]`, string(StatusUnknown), "mismatch", ""},
	} {
		t.Run(scenario.name, func(t *testing.T) {
			posts, datasetReads := 0, 0
			transport := roundTripFunc(func(r *http.Request) (*http.Response, error) {
				switch {
				case r.Method == http.MethodPost:
					posts++
					return respond(201, `{"data":{"id":"run","defaultDatasetId":"ds","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`), nil
				case strings.HasSuffix(r.URL.Path, "/items"):
					datasetReads++
					return respond(200, scenario.items), nil
				default:
					return respond(200, `{"data":{"id":"run","status":"SUCCEEDED","defaultDatasetId":"ds","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`), nil
				}
			})
			got := newClient(t, transport, &memoryJournal{}, nil).GetTranscript(context.Background(), testURL)
			if posts != 1 || datasetReads != 1 || string(got.Status) != scenario.wantStatus || got.AttributionVerification != scenario.wantVerification {
				t.Fatalf("status=%s attribution=%s posts=%d datasetReads=%d", got.Status, got.AttributionVerification, posts, datasetReads)
			}
			if got.Text != scenario.wantText {
				t.Fatalf("text=%q want=%q", got.Text, scenario.wantText)
			}
			if len(got.RawItems) != 1 && scenario.name != "multiple with mismatch" {
				t.Fatalf("raw Dataset items were not retained: %#v", got.RawItems)
			}
		})
	}
}
