package com.apismith.instagram.transcriptapi;
import com.fasterxml.jackson.databind.JsonNode;
public record ProfilePost(String url, String type, String ownerUsername, String caption, JsonNode timestamp,
        String videoUrl, JsonNode videoDuration, String status, JsonNode raw, String error) { }
