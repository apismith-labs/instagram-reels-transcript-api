package com.apismith.instagram.transcriptapi;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;
public record ProfileResult(ProfileStatus status, Status executionStatus, List<ProfilePost> posts, List<String> usernames,
        String runId, String datasetId, boolean datasetComplete, String error, List<JsonNode> rawItems) { }
