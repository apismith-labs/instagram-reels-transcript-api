package com.apismith.instagram.transcriptapi;
import com.fasterxml.jackson.annotation.JsonValue;
public enum BulkStatus { ALL_SUCCESS("all_success"), PARTIAL_SUCCESS("partial_success"), ALL_FAILED("all_failed"), UNKNOWN("unknown"); private final String value; BulkStatus(String v){value=v;} @JsonValue public String value(){return value;} @Override public String toString(){return value;} }
