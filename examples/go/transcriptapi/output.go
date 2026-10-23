package transcriptapi

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"time"
)

var outputPrefixPattern = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{0,63}$`)

// WriteResultUnique writes a result without replacing an existing output file.
func WriteResultUnique(directory string, result Result, now time.Time) (string, error) {
	return WriteJSONUnique(directory, "go-single-url", result, now)
}

// WriteJSONUnique stores any public result using a mode-specific unique filename.
func WriteJSONUnique(directory, prefix string, value any, now time.Time) (string, error) {
	if now.IsZero() {
		now = time.Now()
	}
	if !outputPrefixPattern.MatchString(prefix) {
		return "", fmt.Errorf("output prefix must contain only lowercase letters, digits, and hyphens")
	}
	if err := os.MkdirAll(directory, 0o700); err != nil {
		return "", err
	}
	encoded, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return "", err
	}
	base := prefix + "-" + now.UTC().Format("20060102T150405.000000000Z")
	for suffix := 0; ; suffix++ {
		name := fmt.Sprintf("%s-%d.json", base, suffix)
		path := filepath.Join(directory, name)
		file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
		if os.IsExist(err) {
			continue
		}
		if err != nil {
			return "", err
		}
		writeErr := func() error {
			if _, err := file.Write(append(encoded, '\n')); err != nil {
				return err
			}
			if err := file.Chmod(0o600); err != nil {
				return err
			}
			if err := file.Sync(); err != nil {
				return err
			}
			return file.Close()
		}()
		if writeErr != nil {
			_ = file.Close()
			_ = os.Remove(path)
			return "", writeErr
		}
		return path, nil
	}
}
