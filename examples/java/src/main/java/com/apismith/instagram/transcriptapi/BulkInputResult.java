package com.apismith.instagram.transcriptapi;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;
public record BulkInputResult(String url, BulkItemStatus status, String text, List<JsonNode> segments, List<JsonNode> items, String error) { }
