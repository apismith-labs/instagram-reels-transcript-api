package com.apismith.instagram.transcriptapi;
import com.fasterxml.jackson.annotation.JsonValue;
public enum BulkItemStatus { SUCCESS_TRANSCRIPT("success_transcript"), ACTOR_ERROR("actor_error"), NO_TRANSCRIPT("no_transcript"), MISSING_RESULT("missing_result"), DUPLICATE_RESULT("duplicate_result"), UNKNOWN("unknown"); private final String value; BulkItemStatus(String v){value=v;} @JsonValue public String value(){return value;} @Override public String toString(){return value;} }
