package com.sinrotic.rs.recommend.config;

import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.service.impl.RestHomeModelRanker;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.math.BigDecimal;
import java.util.*;
import static org.assertj.core.api.Assertions.*;

class RecommendationHttpConfigurationTest {
    @Test void separateAdaptersReuseTheHttpConnectionAndSendValidRankBodies() throws Exception {
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 16);
        var ports = java.util.concurrent.ConcurrentHashMap.<Integer>newKeySet();
        var bodies = new java.util.concurrent.CopyOnWriteArrayList<String>();
        server.createContext("/internal/model/rank", exchange -> {
            try (exchange) {
                bodies.add(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
                ports.add(exchange.getRemoteAddress().getPort());
                byte[] body = "{\"items\":[{\"item_id\":\"item\",\"score\":0.8}]}".getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                exchange.sendResponseHeaders(200, body.length);
                exchange.getResponseBody().write(body);
            }
        });
        server.start();
        try {
            var config = new RecommendationHttpConfiguration();
            String url = "http://127.0.0.1:" + server.getAddress().getPort();
            var first = new RestHomeModelRanker(config.recommendationRestClientBuilder(), url);
            var second = new RestHomeModelRanker(config.recommendationRestClientBuilder(), url);
            var items = List.of(new ItemEmbeddingText("item", "real product text", "Headphones", "Headphones", "Headphones", "", BigDecimal.ONE, Map.of()));
            assertThat(first.score("first", "query", items)).containsEntry("item", .8);
            assertThat(second.score("second", "query", items)).containsEntry("item", .8);
            assertThat(ports).hasSize(1);
            assertThat(bodies).hasSize(2);
            var mapper = new com.fasterxml.jackson.databind.ObjectMapper();
            for (String body : bodies) {
                var json = mapper.readTree(body);
                assertThat(json.path("inputs").path("candidates").get(0).path("text").asText()).isEqualTo("real product text");
                assertThat(json.path("inputs").path("query").asText()).isEqualTo("query");
            }
        } finally { server.stop(0); }
    }
}
