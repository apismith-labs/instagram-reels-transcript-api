package main

import (
	"bytes"
	"context"
	"net/http"
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

func TestBulkCLIRejectsInvalidInputBeforeReadingEnvironment(t *testing.T) {
	reads := 0
	transport := &testTransport{}
	var stderr bytes.Buffer
	code := run([]string{"https://instagram.com/reel/x/", "https://instagram.com/reels/x"}, func(string) string { reads++; return "synthetic" }, nil, &stderr, &http.Client{Transport: transport}, &testJournal{})
	if code != 2 || reads != 0 || transport.posts != 0 {
		t.Fatalf("code=%d env reads=%d posts=%d", code, reads, transport.posts)
	}
	code = run([]string{"--resume=", "https://instagram.com/reel/x/"}, func(string) string { reads++; return "synthetic" }, nil, &stderr, &http.Client{Transport: transport}, &testJournal{})
	if code != 2 || reads != 0 || transport.posts != 0 {
		t.Fatalf("empty --resume fell back to create: code=%d reads=%d posts=%d", code, reads, transport.posts)
	}
}

func TestBulkCLIHelpDoesNotReadEnvironment(t *testing.T) {
	reads := 0
	var stdout, stderr bytes.Buffer
	code := run([]string{"--help"}, func(string) string { reads++; return "synthetic" }, &stdout, &stderr, nil, &testJournal{})
	if code != 0 || reads != 0 || !strings.Contains(stderr.String(), "Usage") {
		t.Fatalf("code=%d reads=%d stderr=%q", code, reads, stderr.String())
	}
}
