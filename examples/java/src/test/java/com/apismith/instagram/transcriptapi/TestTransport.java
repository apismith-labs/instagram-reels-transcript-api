package com.apismith.instagram.transcriptapi;

import java.io.IOException;
import java.time.Duration;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

public final class TestTransport implements Transport {
    public record Call(String method, String path, Object body, Map<String,String> query) { }
    private final ArrayDeque<Object> replies = new ArrayDeque<>();
    public final List<Call> calls = new ArrayList<>();
    public int posts;
    public TestTransport reply(int status, String body) { replies.add(new TransportResponse(status, body)); return this; }
    public TestTransport reply(int status, String body, Map<String,List<String>> headers) { replies.add(new TransportResponse(status, body, headers)); return this; }
    public TestTransport fail(IOException error) { replies.add(error); return this; }
    @Override public boolean guaranteesSingleShotPost() { return true; }
    @Override public TransportResponse send(String method, String path, Object body, Map<String,String> query, Duration timeout) throws IOException {
        calls.add(new Call(method,path,body,Map.copyOf(query)));
        if ("POST".equals(method)) posts++;
        Object next = replies.poll();
        if (next instanceof IOException error) throw error;
        if (next == null) throw new IOException("no scripted response");
        return (TransportResponse) next;
    }
    public static TestTransport successful(String items) {
        return new TestTransport()
            .reply(201,"{\"data\":{\"id\":\"R1\",\"defaultDatasetId\":\"D1\",\"status\":\"RUNNING\",\"actId\":\"apple_yang/instagram-transcripts-scraper\"}}")
            .reply(200,"{\"data\":{\"id\":\"R1\",\"defaultDatasetId\":\"D1\",\"status\":\"SUCCEEDED\",\"actId\":\"apple_yang/instagram-transcripts-scraper\",\"buildNumber\":\"0.0.50\",\"buildId\":\"aJLRmMdQapLQRT4sJ\"}}")
            .reply(200,items);
    }
}
