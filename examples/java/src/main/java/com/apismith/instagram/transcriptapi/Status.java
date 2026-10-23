package com.apismith.instagram.transcriptapi;
import com.fasterxml.jackson.annotation.JsonValue;

public enum Status {
    SUCCESS("success"), ACTOR_ERROR("actor_error"), EMPTY("empty"), NO_TRANSCRIPT("no_transcript"),
    UNKNOWN("unknown"), TRANSPORT_ERROR("transport_error"), RUN_FAILED("run_failed"),
    CREATION_UNKNOWN("creation_unknown"), INVALID_INPUT("invalid_input"), STOPPED_UNKNOWN("stopped_unknown");
    private final String value;
    Status(String value) { this.value = value; }
    @JsonValue public String value() { return value; }
    @Override public String toString() { return value; }
}
