package com.apismith.instagram.transcriptapi;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;
import java.util.Map;
public record CsvBatchResult(String status, boolean stopped, int plannedRows, int processedRows, int unattemptedRows,
        int concurrency, Map<String,Integer> counts, List<CsvRowResult> rows, List<JsonNode> rawItems, String error) { }
