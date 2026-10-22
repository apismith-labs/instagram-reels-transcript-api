package transcriptapi

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sync"
)

// JSONLJournal serializes append operations and syncs each record before returning.
type JSONLJournal struct {
	mu   sync.Mutex
	file *os.File
}

func OpenJSONLJournal(path string) (*JSONLJournal, error) {
	if path == "" {
		return nil, errors.New("journal path is required")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return nil, err
	}
	if err := f.Chmod(0o600); err != nil {
		_ = f.Close()
		return nil, err
	}
	return &JSONLJournal{file: f}, nil
}

func (j *JSONLJournal) Append(ctx context.Context, entry JournalEntry) error {
	if j == nil {
		return errors.New("journal is closed")
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	encoded, err := json.Marshal(entry)
	if err != nil {
		return err
	}
	j.mu.Lock()
	defer j.mu.Unlock()
	if j.file == nil {
		return errors.New("journal is closed")
	}
	w := bufio.NewWriter(j.file)
	if _, err := w.Write(append(encoded, '\n')); err != nil {
		return err
	}
	if err := w.Flush(); err != nil {
		return err
	}
	return j.file.Sync()
}

func (j *JSONLJournal) Close() error {
	if j == nil {
		return nil
	}
	j.mu.Lock()
	defer j.mu.Unlock()
	if j.file == nil {
		return nil
	}
	err := j.file.Close()
	j.file = nil
	return err
}
