package com.apismith.instagram.transcriptapi;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;

@JsonIgnoreProperties(ignoreUnknown=true)
public record JournalRecord(String at, String stage, String mode, String actorId, String sourceUrl,
        String runId, String runActorId, String datasetId, String runStatus, String buildNumber, String buildId,
        String buildVerification, BigDecimal maxTotalChargeUsd, Boolean restartOnError,
        JsonNode inputContext, String error) { }
