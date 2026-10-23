package com.apismith.instagram.transcriptapi;

import java.util.List;
import java.util.Map;

public record TransportResponse(int statusCode, String body, Map<String,List<String>> headers) {
    public TransportResponse(int statusCode,String body){this(statusCode,body,Map.of());}
    public TransportResponse { headers=headers==null?Map.of():Map.copyOf(headers); }
    public String firstHeader(String name){return headers.entrySet().stream().filter(e->e.getKey().equalsIgnoreCase(name)).flatMap(e->e.getValue().stream()).findFirst().orElse(null);}
}
