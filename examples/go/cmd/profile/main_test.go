package main

import (
	"bytes"
	"context"
	"net/http"
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

func TestProfileCLIInvalidUsernameFailsBeforeEnvironment(t *testing.T) {
	reads := 0
	transport := &testTransport{}
	var stderr bytes.Buffer
	code := run([]string{"@alice"}, func(string) string { reads++; return "synthetic" }, nil, &stderr, &http.Client{Transport: transport}, &testJournal{})
	if code != 2 || reads != 0 || transport.posts != 0 {
		t.Fatalf("code=%d env reads=%d posts=%d", code, reads, transport.posts)
	}
}
