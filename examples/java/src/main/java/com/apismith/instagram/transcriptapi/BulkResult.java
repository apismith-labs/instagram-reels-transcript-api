package com.apismith.instagram.transcriptapi;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;
import java.util.Map;
public record BulkResult(BulkStatus status, Status executionStatus, List<BulkInputResult> results, List<ExtraResult> extras,
        Map<BulkItemStatus,Integer> counts, String runId, String datasetId, boolean datasetComplete,
        List<JsonNode> rawItems, AttributionVerification attributionVerification, String error, String stage) { }
