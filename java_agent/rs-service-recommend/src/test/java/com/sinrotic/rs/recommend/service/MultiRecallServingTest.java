package com.sinrotic.rs.recommend.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.service.impl.RestMultiSourceRecallProvider;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import static org.junit.jupiter.api.Assertions.*;

class MultiRecallServingTest {
    @Test void httpContractUsesBoundedLengthAndChecksArtifactVersion() throws Exception {
        var response = new AtomicReference<>("{\"version\":\"v1\",\"sources\":{\"itemcf_weak\":[{\"item_id\":\"product\",\"score\":0.8}]}}");
        var request = new AtomicReference<String>();
        var length = new AtomicReference<String>();
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/internal/recall/multi", exchange -> {
            request.set(new String(exchange.getRequestBody().readAllBytes(),StandardCharsets.UTF_8));
            length.set(exchange.getRequestHeaders().getFirst("Content-Length"));
            byte[] body = response.get().getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type","application/json");
            exchange.sendResponseHeaders(200,body.length);exchange.getResponseBody().write(body);exchange.close();
        });
        server.start();
        try {
            var client = new RestMultiSourceRecallProvider(RestClient.builder(),new ObjectMapper(),"http://127.0.0.1:"+server.getAddress().getPort(),"v1");
            var hits = client.recall("user",List.of("a","b"),List.of("itemcf_weak"),80);
            assertEquals("product",hits.get("itemcf_weak").getFirst().itemId());
            assertEquals(request.get().getBytes(StandardCharsets.UTF_8).length,Integer.parseInt(length.get()));
            response.set("{\"version\":\"wrong\",\"sources\":{\"itemcf_weak\":[]}}");
            assertThrows(IllegalStateException.class,()->client.recall("user",List.of("a","b"),List.of("itemcf_weak"),80));
        } finally { server.stop(0); }
    }
}
