package main

import (
	"bytes"
	"context"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
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
	code := run([]string{"--dry-run", path}, func(key string) string {
		if key == "APIFY_TOKEN" {
			reads++
		}
		return ""
	}, &stdout, &stderr, &http.Client{Transport: transport}, &testJournal{})
	if code != 0 || reads != 0 || transport.posts != 0 || !strings.Contains(stdout.String(), `"maximumRuns":1`) {
		t.Fatalf("code=%d reads=%d posts=%d stdout=%s stderr=%s", code, reads, transport.posts, stdout.String(), stderr.String())
	}
}

func TestCSVCLIDryRunEstimatesPerRunCapsExactly(t *testing.T) {
	for _, tc := range []struct{ rows, cap, total string }{{"3", "0.10", "0.30"}, {"100", "0.30", "30.00"}} {
		path := filepath.Join(t.TempDir(), "input.csv")
		var csv strings.Builder
		csv.WriteString("url\n")
		for i := 0; i < mustAtoi(tc.rows); i++ {
			csv.WriteString("https://instagram.com/reel/item" + strings.Repeat("a", i%4+3) + strconv.Itoa(i) + "/\n")
		}
		if err := os.WriteFile(path, []byte(csv.String()), 0o600); err != nil {
			t.Fatal(err)
		}
		reads, posts := 0, 0
		var stdout, stderr bytes.Buffer
		transport := &testTransport{}
		code := run([]string{"--max-total-charge-usd", tc.cap, path}, func(string) string { reads++; return "" }, &stdout, &stderr, &http.Client{Transport: transport}, &testJournal{})
		posts = transport.posts
		if code != 0 || reads != 1 || posts != 0 || !strings.Contains(stdout.String(), `"estimatedMaximumRunCapsTotalUsd":"`+tc.total+`"`) {
			t.Fatalf("case=%+v code=%d reads=%d posts=%d stdout=%s stderr=%s", tc, code, reads, posts, stdout.String(), stderr.String())
		}
	}
}

func mustAtoi(value string) int {
	result, err := strconv.Atoi(value)
	if err != nil {
		panic(err)
	}
	return result
}

func TestCSVCLIDryRunDoesNotInventTotalWithoutCap(t *testing.T) {
	path := filepath.Join(t.TempDir(), "input.csv")
	if err := os.WriteFile(path, []byte("url\nhttps://instagram.com/reel/abc123/\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	var stdout bytes.Buffer
	code := run([]string{path}, func(string) string { return "" }, &stdout, nil, nil, nil)
	if code != 0 || strings.Contains(stdout.String(), "estimatedMaximumRunCapsTotalUsd") || strings.Contains(stdout.String(), "perRunCapUsd") {
		t.Fatalf("invented cap: %s", stdout.String())
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
