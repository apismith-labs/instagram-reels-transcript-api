package transcriptapi

import (
	"context"
	"encoding/csv"
	"fmt"
	"io"
	"strings"
	"unicode/utf8"
)

type CSVInputRow struct {
	Row int    `json:"row"`
	URL string `json:"url"`
}

// ReadCSVBatch validates the complete UTF-8 CSV before callers start any Run.
// The accepted schema is intentionally small: a header containing one `url` column.
func ReadCSVBatch(reader io.Reader) ([]CSVInputRow, error) {
	data, err := io.ReadAll(reader)
	if err != nil {
		return nil, fmt.Errorf("read CSV: %w", err)
	}
	if !utf8.Valid(data) {
		return nil, fmt.Errorf("CSV must be valid UTF-8")
	}
	text := strings.TrimPrefix(string(data), "\uFEFF")
	parser := csv.NewReader(strings.NewReader(text))
	parser.FieldsPerRecord = -1
	header, err := parser.Read()
	if err == io.EOF {
		return []CSVInputRow{}, nil
	}
	if err != nil {
		return nil, fmt.Errorf("CSV header: %w", err)
	}
	column := -1
	for i, name := range header {
		normalized := strings.ToLower(strings.TrimSpace(name))
		if normalized == "url" || normalized == "videourl" {
			if column >= 0 {
				return nil, fmt.Errorf("CSV header has multiple supported URL columns")
			}
			column = i
		}
	}
	if column < 0 {
		return nil, fmt.Errorf("CSV is missing required `url` column")
	}
	rows := []CSVInputRow{}
	for {
		record, readErr := parser.Read()
		if readErr == io.EOF {
			break
		}
		line, _ := parser.FieldPos(0)
		if readErr != nil {
			return nil, fmt.Errorf("CSV line %d: %w", line, readErr)
		}
		if len(record) == 1 && strings.TrimSpace(record[0]) == "" {
			continue
		}
		if column >= len(record) {
			return nil, fmt.Errorf("CSV line %d: missing URL field", line)
		}
		raw := strings.TrimSpace(record[column])
		if raw == "" {
			return nil, fmt.Errorf("CSV line %d: URL field is empty", line)
		}
		valid, validationErr := ValidateVideoURL(raw)
		if validationErr != nil {
			return nil, fmt.Errorf("CSV line %d: invalid URL %q: %w", line, raw, validationErr)
		}
		rows = append(rows, CSVInputRow{Row: line, URL: valid})
	}
	return rows, nil
}

// GetTranscriptsFromCSV executes one independent Run per input row, serially.
func (c *Client) GetTranscriptsFromCSV(ctx context.Context, rows []CSVInputRow) CSVBatchResult {
	result := CSVBatchResult{Status: "empty", Rows: make([]CSVRowResult, 0, len(rows)), Counts: map[Status]int{}, PlannedRows: len(rows)}
	validated := make([]CSVInputRow, 0, len(rows))
	for _, row := range rows {
		valid, err := ValidateVideoURL(row.URL)
		if row.Row <= 0 || err != nil {
			result.Status = "invalid_input"
			result.Failed = 1
			result.Counts[StatusTransportError] = 1
			result.Rows = append(result.Rows, CSVRowResult{Row: row.Row, URL: row.URL, Status: StatusTransportError, Segments: []Segment{}, RawItems: []any{}, Error: "invalid CSV input row"})
			return result
		}
		row.URL = valid
		validated = append(validated, row)
	}
	for _, row := range validated {
		inputContext := &JournalInputContext{Mode: "csv_batch", Input: map[string]any{"row": row.Row, "videoUrl": row.URL}}
		item := c.getTranscript(ctx, row.URL, inputContext)
		result.Rows = append(result.Rows, CSVRowResult{Row: row.Row, URL: row.URL, Status: item.Status, RunID: item.RunID, DatasetID: item.DatasetID,
			Text: item.Text, Segments: item.Segments, RawItems: item.RawItems, Error: item.Error})
		result.Counts[item.Status]++
		if item.Status == StatusSuccess {
			result.Success++
		} else {
			result.Failed++
		}
		if item.Status == StatusCreationUnknown || item.Stage == "journal_intent" || item.Stage == "journal_run_created" || item.Stage == "journal_terminal" {
			result.Status = "stopped_unknown"
			break
		}
	}
	if result.Status != "stopped_unknown" {
		switch {
		case len(rows) == 0:
			result.Status = "empty"
		case result.Failed == 0:
			result.Status = "all_success"
		case result.Success == 0:
			result.Status = "all_failed"
		default:
			result.Status = "partial_success"
		}
	}
	result.UnattemptedRows = result.PlannedRows - len(result.Rows)
	return result
}

func CSVBatchExitCode(result CSVBatchResult) int {
	if result.Status == "invalid_input" {
		return 2
	}
	for _, row := range result.Rows {
		switch row.Status {
		case StatusCreationUnknown:
			return 10
		case StatusRunFailed:
			return 9
		case StatusTransportError:
			return 8
		}
	}
	if result.Failed > 0 {
		return 11
	}
	return 0
}
