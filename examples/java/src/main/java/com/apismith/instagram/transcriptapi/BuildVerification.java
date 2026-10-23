package com.apismith.instagram.transcriptapi;
import com.fasterxml.jackson.annotation.JsonValue;
public enum BuildVerification { VERIFIED("verified"), MISMATCH("mismatch"), UNVERIFIED("unverified"), UNKNOWN("unknown"); private final String value; BuildVerification(String v){value=v;} @JsonValue public String value(){return value;} @Override public String toString(){return value;} }
