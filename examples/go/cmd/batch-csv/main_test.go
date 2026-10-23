package main

import (
	"bytes"
	"context"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/apismith-labs/instagram-reels-transcript-api/examples/go/transcriptapi"
)

type testJournal struct{ appends int }

func (j *testJournal) Append(context.Context, transcriptapi.JournalEntry) error {
	j.appends++
	return nil
}

type testTransport struct{ posts int }

func (t *testTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	if r.Method == http.MethodPost {
		t.posts++
	}
	return nil, nil
}

func TestCSVCLIDryRunValidatesButNeverReadsCredentialsOrPosts(t *testing.T) {
	path := filepath.Join(t.TempDir(), "中文 space.csv")
	if err := os.WriteFile(path, []byte("url\r\nhttps://instagram.com/reel/abc123/\r\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	reads := 0
	transport := &testTransport{}
	var stdout, stderr bytes.Buffer
	code := run([]string{"--dry-run", path}, func(string) string { reads++; return "synthetic" }, &stdout, &stderr, &http.Client{Transport: transport}, &testJournal{})
	if code != 0 || reads != 0 || transport.posts != 0 || !strings.Contains(stdout.String(), `"maximumRuns":1`) {
		t.Fatalf("code=%d reads=%d posts=%d stdout=%s stderr=%s", code, reads, transport.posts, stdout.String(), stderr.String())
	}
}

func TestCSVCLIRequiresExplicitExecuteOrDryRunAndValidatesFirst(t *testing.T) {
	path := filepath.Join(t.TempDir(), "input.csv")
	if err := os.WriteFile(path, []byte("name\nalice\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	reads := 0
	transport := &testTransport{}
	var stderr bytes.Buffer
	code := run([]string{"--execute", path}, func(string) string { reads++; return "synthetic" }, nil, &stderr, &http.Client{Transport: transport}, &testJournal{})
	if code != 2 || reads != 0 || transport.posts != 0 || !strings.Contains(stderr.String(), "missing required `url` column") {
		t.Fatalf("code=%d reads=%d posts=%d stderr=%s", code, reads, transport.posts, stderr.String())
	}
}
