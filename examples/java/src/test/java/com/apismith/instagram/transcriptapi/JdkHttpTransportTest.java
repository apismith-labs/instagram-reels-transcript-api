package com.apismith.instagram.transcriptapi;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import java.net.InetSocketAddress;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.jupiter.api.Assertions.*;
class JdkHttpTransportTest {
 @Test void postRedirectIsReturnedAndNeverFollowed()throws Exception{AtomicInteger calls=new AtomicInteger();HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);server.createContext("/acts/test/runs",exchange->{calls.incrementAndGet();exchange.getResponseHeaders().add("Location","/second");exchange.sendResponseHeaders(307,-1);exchange.close();});server.createContext("/second",exchange->{calls.incrementAndGet();exchange.sendResponseHeaders(200,0);exchange.close();});server.start();try{var transport=new JdkHttpTransport("synthetic",Duration.ofSeconds(2),"http://127.0.0.1:"+server.getAddress().getPort());var response=transport.send("POST","/acts/test/runs",Map.of("videoUrl","https://www.instagram.com/reel/a/"),Map.of(),Duration.ofSeconds(2));assertEquals(307,response.statusCode());assertEquals(1,calls.get());}finally{server.stop(0);}}
}
