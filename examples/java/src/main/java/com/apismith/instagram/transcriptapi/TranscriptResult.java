package com.apismith.instagram.transcriptapi;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;
public record TranscriptResult(Status status, String runStatus, String runId, String datasetId, String sourceUrl, String actorId,
        String buildNumber, String buildId, BuildVerification buildVerification, String buildEvidenceSource,
        boolean datasetComplete, boolean datasetCompleteKnown, String text, List<JsonNode> segments,
        List<JsonNode> rawItems, String error, String stage, AttributionVerification attributionVerification) { }
