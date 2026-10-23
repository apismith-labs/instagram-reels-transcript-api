package com.apismith.instagram.transcriptapi;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;
public record CsvRowResult(String row, String sourceUrl, Status status, String runId, String datasetId, String text,
        List<JsonNode> segments, int segmentsCount, List<JsonNode> rawItems, Boolean datasetComplete, String error) { }
