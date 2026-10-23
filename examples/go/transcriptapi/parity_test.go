package transcriptapi

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"reflect"
	"strings"
	"testing"
)

func TestBulkAttributionConservativeAndRawPreserving(t *testing.T) {
	urls := []string{testURL, "https://instagram.com/reels/other123"}
	items := []any{
		map[string]any{"url": "https://instagram.com/reels/synthetic123", "code": "synthetic123", "text": "one", "segments": []any{map[string]any{"start": 1}}},
		map[string]any{"code": "other123", "title": "metadata"},
		map[string]any{"url": "https://instagram.com/reel/extraneous/", "text": "extra"},
	}
	rows, extras, counts, status := attributeBulkItems(urls, items, true)
	if rows[0].Status != BulkItemSuccessTranscript || rows[0].AttributionVerification != "verified" || rows[0].Text != "one" || len(rows[0].Segments) != 1 {
		t.Fatalf("first attribution: %+v", rows[0])
	}
	if rows[1].Status != BulkItemNoTranscript || rows[1].AttributionVerification != "unverified" {
		t.Fatalf("shortcode fallback: %+v", rows[1])
	}
	if len(extras) != 1 || !reflect.DeepEqual(extras[0].Item, items[2]) {
		t.Fatalf("extra item lost: %#v", extras)
	}
	if counts.SuccessTranscript != 1 || counts.NoTranscript != 1 || status != BulkUnknown {
		t.Fatalf("counts/status: %+v %s", counts, status)
	}
	rows, _, counts, status = attributeBulkItems(urls, items[:1], false)
	if rows[1].Status != BulkItemUnknown || counts.Unknown != 1 || status != BulkUnknown {
		t.Fatalf("incomplete dataset was overstated: %+v %+v %s", rows, counts, status)
	}
	conflict := []any{map[string]any{"url": urls[0], "code": "other123", "text": "must remain extra"}}
	rows, extras, _, status = attributeBulkItems(urls, conflict, true)
	if len(extras) != 1 || rows[0].Status != BulkItemMissingResult || status != BulkUnknown {
		t.Fatalf("URL/code conflict was attributed: %+v %#v %s", rows, extras, status)
	}
}

func TestBulkValidationRejectsAliasesAndDatasetOverrunBeforePOST(t *testing.T) {
	posts := 0
	client := newClient(t, roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.Method == http.MethodPost {
			posts++
		}
		return nil, fmt.Errorf("unexpected request")
	}), &memoryJournal{}, nil)
	for _, request := range []BulkRequest{{URLs: []string{testURL, "https://instagram.com/reels/synthetic123"}}, {URLs: []string{testURL, testURL, testURL, testURL, testURL, testURL}}} {
		got := client.GetTranscripts(context.Background(), request)
		if got.Status != BulkUnknown || got.ExecutionStatus != StatusTransportError || posts != 0 {
			t.Fatalf("invalid bulk request proceeded: %+v posts=%d", got, posts)
		}
	}
}

func TestGetTranscriptsUsesExactlyOnePOSTAndBulkInputOnly(t *testing.T) {
	urls := []string{testURL, "https://instagram.com/reel/other123/", "https://instagram.com/reel/third123/"}
	posts, gets := 0, 0
	client := newClient(t, roundTripFunc(func(r *http.Request) (*http.Response, error) {
		switch r.Method {
		case http.MethodPost:
			posts++
			query, _ := url.ParseQuery(r.URL.RawQuery)
			if query.Get("restartOnError") != "false" || query.Get("build") != ControlledBuildNumber || query.Get("maxTotalChargeUsd") != "0.3" {
				t.Fatalf("bad Run options: %v", query)
			}
			var input map[string]any
			if err := json.NewDecoder(r.Body).Decode(&input); err != nil {
				t.Fatal(err)
			}
			if len(input) != 1 || input["bulkUrls"] == nil {
				t.Fatalf("Run query leaked into Actor input: %v", input)
			}
			return respond(201, `{"data":{"id":"bulk-run","defaultDatasetId":"bulk-ds","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`), nil
		case http.MethodGet:
			gets++
			if strings.HasSuffix(r.URL.Path, "/items") {
				return respond(200, `[{"url":"https://instagram.com/reel/synthetic123/","code":"synthetic123","text":"a","segments":[]},{"url":"https://instagram.com/reel/other123/","code":"other123","text":"b","segments":[]},{"url":"https://instagram.com/reel/third123/","code":"third123","text":"c","segments":[]}]`), nil
			}
			return respond(200, `{"data":{"id":"bulk-run","status":"SUCCEEDED","defaultDatasetId":"bulk-ds","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`), nil
		default:
			t.Fatalf("unexpected method %s", r.Method)
			return nil, nil
		}
	}), &memoryJournal{}, func(config *Config) { config.RequireChargeCap = true; config.MaxTotalChargeUSD = 0.3 })
	got := client.GetTranscripts(context.Background(), BulkRequest{URLs: urls})
	if posts != 1 || gets != 2 || got.Status != BulkAllSuccess || len(got.Inputs) != 3 {
		t.Fatalf("unexpected Bulk result %+v posts=%d gets=%d", got, posts, gets)
	}
}

func TestNativeBulkOneRunForSmallAndTenInputLists(t *testing.T) {
	for _, count := range []int{1, 10} {
		t.Run(fmt.Sprintf("inputs_%d", count), func(t *testing.T) {
			urls := make([]string, count)
			items := make([]map[string]string, count)
			for i := 0; i < count; i++ {
				code := fmt.Sprintf("item%03d", i)
				urls[i] = "https://instagram.com/reel/" + code + "/"
				items[i] = map[string]string{"url": urls[i], "code": code, "text": "transcript"}
			}
			body, _ := json.Marshal(items)
			posts := 0
			client := newClient(t, roundTripFunc(func(r *http.Request) (*http.Response, error) {
				if r.Method == http.MethodPost {
					posts++
					return respond(201, `{"data":{"id":"one-run","defaultDatasetId":"one-dataset","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`), nil
				}
				if strings.HasSuffix(r.URL.Path, "/items") {
					return respond(200, string(body)), nil
				}
				return respond(200, `{"data":{"id":"one-run","status":"SUCCEEDED","defaultDatasetId":"one-dataset","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`), nil
			}), &memoryJournal{}, func(config *Config) { config.DatasetLimit = 20 })
			result := client.GetTranscripts(context.Background(), BulkRequest{URLs: urls})
			if posts != 1 || result.Status != BulkAllSuccess || len(result.Inputs) != count {
				t.Fatalf("inputs=%d posts=%d result=%+v", count, posts, result)
			}
		})
	}
}

func TestProfileMetadataClassificationAndValidation(t *testing.T) {
	request := ProfileRequest{Usernames: []string{"alice"}, ResultsLimit: func() *int { n := 1; return &n }()}
	if _, err := ValidateProfileRequest(request); err != nil {
		t.Fatal(err)
	}
	if _, err := ValidateProfileRequest(ProfileRequest{Usernames: []string{"@alice"}}); err == nil {
		t.Fatal("accepted @ username")
	}
	post, valid := normalizeProfilePost(map[string]any{"url": "https://instagram.com/p/post123/", "type": "Image", "ownerUsername": "alice", "timestamp": "raw-time"}, []string{"alice"})
	if !valid || post.Status != "success" || post.Timestamp != "raw-time" || post.OwnerUsername != "alice" {
		t.Fatalf("profile metadata rejected: %+v", post)
	}
	post, valid = normalizeProfilePost(map[string]any{"url": "https://instagram.com/p/post123/", "type": "Image", "ownerUsername": "bob"}, []string{"alice"})
	if valid || post.Status != "unknown" {
		t.Fatalf("conflicting owner accepted: %+v", post)
	}
	post, valid = normalizeProfilePost(map[string]any{"url": "https://instagram.com/p/post123/", "errMsg": "not available"}, []string{"alice"})
	if !valid || post.Status != "actor_error" {
		t.Fatalf("Actor error lost: %+v", post)
	}
}

func TestCSVReadBOMCRLFAndWholeFileValidation(t *testing.T) {
	rows, err := ReadCSVBatch(strings.NewReader("\ufeffurl,note\r\n" + testURL + ",x\r\n"))
	if err != nil || len(rows) != 1 || rows[0].Row != 2 || rows[0].URL != testURL {
		t.Fatalf("rows=%+v err=%v", rows, err)
	}
	legacy, err := ReadCSVBatch(strings.NewReader("videoUrl\n" + testURL + "\n"))
	if err != nil || len(legacy) != 1 {
		t.Fatalf("existing videoUrl sample header was rejected: %+v %v", legacy, err)
	}
	for _, input := range []string{"", "name\n", "url\nnot-a-url\n"} {
		if _, err := ReadCSVBatch(strings.NewReader(input)); input != "" && err == nil {
			t.Fatalf("accepted invalid CSV %q", input)
		}
	}
}

func TestResumeTranscriptUsesRecordedInputAndNeverPOSTs(t *testing.T) {
	journal := &memoryJournal{}
	input := map[string]any{"videoUrl": testURL}
	journal.entries = []JournalEntry{{Stage: "run_created", ActorID: "owner/actor", RunActorID: "actor-internal-1", RunID: "resume-1", DatasetID: "resume-ds", BuildNumber: ControlledBuildNumber, BuildID: ControlledBuildID,
		InputContext: &JournalInputContext{Mode: "single", Input: input}}}
	posts, gets := 0, 0
	client := newClient(t, roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.Method == http.MethodPost {
			posts++
			t.Fatal("Resume created a Run")
		}
		gets++
		if strings.HasSuffix(r.URL.Path, "/items") {
			return respond(200, `[{"url":"`+testURL+`","text":"transcript","segments":[]}]`), nil
		}
		return respond(200, `{"data":{"id":"resume-1","actId":"actor-internal-1","status":"SUCCEEDED","defaultDatasetId":"resume-ds","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`), nil
	}), journal, nil)
	result := client.ResumeTranscript(context.Background(), "resume-1", testURL)
	if result.Status != StatusSuccess || result.RunID != "resume-1" || posts != 0 || gets != 3 {
		t.Fatalf("resume result=%+v posts=%d gets=%d", result, posts, gets)
	}
	wrong := client.ResumeTranscript(context.Background(), "resume-1", "https://instagram.com/reel/other123/")
	if wrong.Status != StatusUnknown || wrong.Stage != "resume_input_mismatch" || posts != 0 || gets != 3 {
		t.Fatalf("mismatched resume was not fail-closed: %+v", wrong)
	}
}

func TestResumeNativeBulkUsesRecordedInputAndNeverPOSTs(t *testing.T) {
	input := map[string]any{"bulkUrls": []any{testURL}}
	journal := &memoryJournal{entries: []JournalEntry{{Stage: "run_created", ActorID: "owner/actor", RunActorID: "actor-bulk", RunID: "bulk-resume", DatasetID: "bulk-ds", BuildNumber: ControlledBuildNumber, BuildID: ControlledBuildID, InputContext: &JournalInputContext{Mode: "native_bulk", Input: input}}}}
	posts, gets := 0, 0
	client := newClient(t, roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.Method == http.MethodPost {
			posts++
			t.Fatal("Bulk Resume created a Run")
		}
		gets++
		if strings.HasSuffix(r.URL.Path, "/items") {
			return respond(200, `[{"url":"`+testURL+`","code":"synthetic123","text":"resumed","segments":[]}]`), nil
		}
		return respond(200, `{"data":{"id":"bulk-resume","actId":"actor-bulk","status":"SUCCEEDED","defaultDatasetId":"bulk-ds","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`), nil
	}), journal, nil)
	result := client.ResumeTranscripts(context.Background(), "bulk-resume", BulkRequest{URLs: []string{testURL}})
	if result.Status != BulkAllSuccess || result.RunID != "bulk-resume" || posts != 0 || gets != 3 {
		t.Fatalf("Bulk Resume result=%+v posts=%d gets=%d", result, posts, gets)
	}
}

func TestResumeRefusesActorIdentityDriftWithoutDatasetReadOrPOST(t *testing.T) {
	journal := &memoryJournal{entries: []JournalEntry{{Stage: "run_created", ActorID: "owner/actor", RunActorID: "expected-actor", RunID: "resume-2", DatasetID: "resume-ds", BuildNumber: ControlledBuildNumber, BuildID: ControlledBuildID,
		InputContext: &JournalInputContext{Mode: "single", Input: map[string]any{"videoUrl": testURL}}}}}
	posts, itemReads := 0, 0
	client := newClient(t, roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.Method == http.MethodPost {
			posts++
		}
		if strings.HasSuffix(r.URL.Path, "/items") {
			itemReads++
			return respond(200, `[]`), nil
		}
		return respond(200, `{"data":{"id":"resume-2","actId":"different-actor","status":"SUCCEEDED","defaultDatasetId":"resume-ds","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`), nil
	}), journal, nil)
	result := client.ResumeTranscript(context.Background(), "resume-2", testURL)
	if result.Status != StatusUnknown || result.Stage != "resume_actor_mismatch" || posts != 0 || itemReads != 0 {
		t.Fatalf("actor drift was not rejected: %+v posts=%d dataset=%d", result, posts, itemReads)
	}
}

func TestResumeRunIDAndBuildMismatchFailClosedWithoutPOST(t *testing.T) {
	for _, mismatch := range []string{"id", "build"} {
		t.Run(mismatch, func(t *testing.T) {
			journal := &memoryJournal{entries: []JournalEntry{{Stage: "run_created", ActorID: "owner/actor", RunActorID: "actor1", RunID: "recorded-run", DatasetID: "ds", BuildNumber: ControlledBuildNumber, BuildID: ControlledBuildID, InputContext: &JournalInputContext{Mode: "single", Input: map[string]any{"videoUrl": testURL}}}}}
			posts, datasetReads := 0, 0
			client := newClient(t, roundTripFunc(func(r *http.Request) (*http.Response, error) {
				if r.Method == http.MethodPost {
					posts++
				}
				if strings.HasSuffix(r.URL.Path, "/items") {
					datasetReads++
					return respond(200, `[]`), nil
				}
				id, build := "recorded-run", ControlledBuildNumber
				if mismatch == "id" {
					id = "other-run"
				}
				if mismatch == "build" {
					build = "0.0.51"
				}
				return respond(200, fmt.Sprintf(`{"data":{"id":%q,"actId":"actor1","status":"SUCCEEDED","defaultDatasetId":"ds","buildNumber":%q,"buildId":"%s"}}`, id, build, ControlledBuildID)), nil
			}), journal, nil)
			result := client.ResumeTranscript(context.Background(), "recorded-run", testURL)
			wantStage := "build_mismatch"
			wantStatus := StatusTransportError
			if mismatch == "id" {
				wantStage = "resume_run_identity"
				wantStatus = StatusUnknown
			}
			if result.Status != wantStatus || result.Stage != wantStage || posts != 0 || datasetReads != 0 {
				t.Fatalf("mismatch was not rejected: %+v posts=%d datasetReads=%d", result, posts, datasetReads)
			}
		})
	}
}

func TestGetProfilePostsUsesProfileMetadataAndOneRun(t *testing.T) {
	posts := 0
	client := newClient(t, roundTripFunc(func(r *http.Request) (*http.Response, error) {
		switch {
		case r.Method == http.MethodPost:
			posts++
			var input map[string]any
			_ = json.NewDecoder(r.Body).Decode(&input)
			if input["usernames"] == nil || input["resultsLimit"] != float64(1) || input["videoUrl"] != nil {
				t.Fatalf("wrong Profile input: %v", input)
			}
			return respond(201, `{"data":{"id":"profile-run","defaultDatasetId":"profile-ds","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`), nil
		case strings.HasSuffix(r.URL.Path, "/items"):
			return respond(200, `[{"url":"https://instagram.com/p/post123/","type":"Image","ownerUsername":"alice","timestamp":"raw-value","caption":"hello"}]`), nil
		default:
			return respond(200, `{"data":{"id":"profile-run","status":"SUCCEEDED","defaultDatasetId":"profile-ds","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`), nil
		}
	}), &memoryJournal{}, nil)
	limit := 1
	result := client.GetProfilePosts(context.Background(), ProfileRequest{Usernames: []string{"alice"}, ResultsLimit: &limit})
	if posts != 1 || result.Status != ProfileSuccess || result.ExecutionStatus != StatusSuccess || result.RunStatus != "SUCCEEDED" || len(result.Posts) != 1 || result.Posts[0].Status != "success" || result.Posts[0].Timestamp != "raw-value" {
		t.Fatalf("Profile result=%+v posts=%d", result, posts)
	}
}

func TestCSVBatchCreatesOneIndependentRunPerRowAndKeepsPartialResults(t *testing.T) {
	posts, runs := 0, 0
	journal := &memoryJournal{}
	client := newClient(t, roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.Method == http.MethodPost {
			posts++
			runs++
			return respond(201, fmt.Sprintf(`{"data":{"id":"run-%d","defaultDatasetId":"ds-%d","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`, runs, runs)), nil
		}
		if strings.HasSuffix(r.URL.Path, "/items") {
			return respond(200, fmt.Sprintf(`[{"url":"https://instagram.com/reel/%s/","text":"text-%d","segments":[]}]`, []string{"first123", "second123"}[runs-1], runs)), nil
		}
		return respond(200, fmt.Sprintf(`{"data":{"id":"run-%d","status":"SUCCEEDED","defaultDatasetId":"ds-%d","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`, runs, runs)), nil
	}), journal, nil)
	rows := []CSVInputRow{{Row: 2, URL: "https://instagram.com/reel/first123/"}, {Row: 3, URL: "https://instagram.com/reel/second123/"}}
	result := client.GetTranscriptsFromCSV(context.Background(), rows)
	if posts != 2 || runs != 2 || result.Success != 2 || result.Failed != 0 || len(result.Rows) != 2 || result.Rows[0].RunID == result.Rows[1].RunID {
		t.Fatalf("CSV result=%+v posts=%d runs=%d", result, posts, runs)
	}
	created := []JournalEntry{}
	for _, entry := range journal.entries {
		if entry.Stage == "run_created" {
			created = append(created, entry)
		}
	}
	if len(created) != 2 || created[0].InputContext == nil || created[0].InputContext.Mode != "csv_batch" || created[1].InputContext == nil || created[1].InputContext.Mode != "csv_batch" {
		t.Fatalf("missing row Journal context: %+v", journal.entries)
	}
	first, _ := canonicalJSON(created[0].InputContext.Input)
	second, _ := canonicalJSON(created[1].InputContext.Input)
	if !strings.Contains(string(first), `"row":2`) || !strings.Contains(string(second), `"row":3`) {
		t.Fatalf("CSV row IDs missing from Journal: %s %s", first, second)
	}
}

func TestCSVBatchIsolatesActorFailureAndContinuesWithOtherRows(t *testing.T) {
	posts, run := 0, 0
	client := newClient(t, roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.Method == http.MethodPost {
			posts++
			run++
			return respond(201, fmt.Sprintf(`{"data":{"id":"r%d","defaultDatasetId":"d%d","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`, run, run)), nil
		}
		if strings.HasSuffix(r.URL.Path, "/items") {
			if run == 1 {
				return respond(200, `[{"url":"https://instagram.com/reel/first123/","errMsg":"synthetic failure"}]`), nil
			}
			return respond(200, `[{"url":"https://instagram.com/reel/second123/","text":"ok","segments":[]}]`), nil
		}
		return respond(200, fmt.Sprintf(`{"data":{"id":"r%d","status":"SUCCEEDED","defaultDatasetId":"d%d","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}`, run, run)), nil
	}), &memoryJournal{}, nil)
	result := client.GetTranscriptsFromCSV(context.Background(), []CSVInputRow{{Row: 2, URL: "https://instagram.com/reel/first123/"}, {Row: 3, URL: "https://instagram.com/reel/second123/"}})
	if posts != 2 || result.Failed != 1 || result.Success != 1 || len(result.Rows) != 2 || result.Rows[0].Status != StatusActorError || result.Rows[1].Status != StatusSuccess {
		t.Fatalf("CSV partial failure was lost: %+v posts=%d", result, posts)
	}
}

func TestCSVBatchCreationUnknownStopsBeforeNextRow(t *testing.T) {
	posts := 0
	client := newClient(t, roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.Method == http.MethodPost {
			posts++
			return respond(503, "synthetic"), nil
		}
		return nil, fmt.Errorf("GET unexpected")
	}), &memoryJournal{}, nil)
	rows := []CSVInputRow{{Row: 2, URL: "https://instagram.com/reel/first123/"}, {Row: 3, URL: "https://instagram.com/reel/second123/"}}
	result := client.GetTranscriptsFromCSV(context.Background(), rows)
	if posts != 1 || result.Status != "stopped_unknown" || len(result.Rows) != 1 || result.Rows[0].Status != StatusCreationUnknown || CSVBatchExitCode(result) != 10 {
		t.Fatalf("CSV resumed after unknown creation: %+v posts=%d", result, posts)
	}
}

func TestCSVAndProfileExitCodeSemantics(t *testing.T) {
	if CSVBatchExitCode(CSVBatchResult{Status: "all_success"}) != 0 || CSVBatchExitCode(CSVBatchResult{Status: "partial_success", Failed: 1}) != 11 || CSVBatchExitCode(CSVBatchResult{Status: "all_failed", Failed: 2}) != 11 {
		t.Fatal("CSV business exit code mismatch")
	}
	if ProfileExitCode(ProfileResult{Status: ProfileSuccess, ExecutionStatus: StatusSuccess}) != 0 || ProfileExitCode(ProfileResult{Status: ProfileActorError, ExecutionStatus: StatusSuccess}) != 4 || ProfileExitCode(ProfileResult{Status: ProfileUnknown, ExecutionStatus: StatusRunFailed}) != 9 {
		t.Fatal("Profile exit code mismatch")
	}
}
