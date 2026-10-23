package com.apismith.instagram.transcriptapi;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;
import java.util.stream.Collectors;

/** Built-in transport with automatic redirects disabled. */
public final class JdkHttpTransport implements Transport {
    private final String token;
    private final HttpClient client;
    private final String baseUrl;
    public JdkHttpTransport(String token, Duration connectTimeout){this(token,connectTimeout,"https://api.apify.com/v2");}
    JdkHttpTransport(String token, Duration connectTimeout, String baseUrl){this.token=token;this.baseUrl=baseUrl;this.client=HttpClient.newBuilder().followRedirects(HttpClient.Redirect.NEVER).connectTimeout(connectTimeout).build();}
    @Override public boolean guaranteesSingleShotPost(){return true;}
    @Override public TransportResponse send(String method,String path,Object body,Map<String,String> query,Duration timeout)throws IOException,InterruptedException{
        String suffix=query==null||query.isEmpty()?"":"?"+query.entrySet().stream().map(e->encode(e.getKey())+"="+encode(e.getValue())).collect(Collectors.joining("&"));
        HttpRequest.Builder b=HttpRequest.newBuilder(URI.create(baseUrl+path+suffix)).timeout(timeout).header("Authorization","Bearer "+token).header("Accept","application/json");
        if("POST".equals(method))b.header("Content-Type","application/json").POST(HttpRequest.BodyPublishers.ofString(JsonSupport.MAPPER.writeValueAsString(body),StandardCharsets.UTF_8));else b.GET();
        HttpResponse<String> r=client.send(b.build(),HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        return new TransportResponse(r.statusCode(),r.body(),r.headers().map());
    }
    private static String encode(String value){return URLEncoder.encode(value,StandardCharsets.UTF_8);}
}
