package com.apismith.instagram.transcriptapi;
import com.fasterxml.jackson.databind.JsonNode;
public record ExtraResult(String status, String reason, JsonNode item) { }
