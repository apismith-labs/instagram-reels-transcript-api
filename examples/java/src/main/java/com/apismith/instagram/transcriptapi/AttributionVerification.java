package com.apismith.instagram.transcriptapi;
import com.fasterxml.jackson.annotation.JsonValue;
public enum AttributionVerification { VERIFIED("verified"), MISMATCH("mismatch"), UNKNOWN("unknown"); private final String value; AttributionVerification(String v){value=v;} @JsonValue public String value(){return value;} @Override public String toString(){return value;} }
