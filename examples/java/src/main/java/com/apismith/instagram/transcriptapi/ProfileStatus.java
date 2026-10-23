package com.apismith.instagram.transcriptapi;
import com.fasterxml.jackson.annotation.JsonValue;
public enum ProfileStatus { SUCCESS("success"), EMPTY("empty"), ACTOR_ERROR("actor_error"), UNKNOWN("unknown"), RUN_FAILED("run_failed"); private final String value; ProfileStatus(String v){value=v;} @JsonValue public String value(){return value;} @Override public String toString(){return value;} }
