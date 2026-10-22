package main

import (
	"strings"
	"testing"
)

func TestRetiredCSVEntryNeverRuns(t *testing.T) {
	err := runBatch()
	if err == nil || !strings.Contains(err.Error(), "retired") {
		t.Fatalf("expected a retired-entry error, got %v", err)
	}
}
