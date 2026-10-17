package com.sinrotic.rs.recommend.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.service.impl.RestTrainedRankingClient;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import static org.junit.jupiter.api.Assertions.*;

class TrainedRankingServingTest {
    @Test void validatesModelVersionAndActualCompressionWithoutLosingProtectedItems() throws Exception {
        String valid="{\"version\":\"v1\",\"feature_version\":\"cold_deepfm_training_features_v2\",\"stage\":\"chain\",\"coarse_input_count\":2,\"coarse_output_count\":1,\"fine_output_count\":1,\"items\":[{\"item_id\":\"a\",\"cold_score\":0.2,\"deepfm_logit\":0.4,\"score\":0.6}]}";
        var response=new AtomicReference<>(valid);
        var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/internal/ranking/cold-deepfm",exchange->{
            exchange.getRequestBody().readAllBytes();byte[] body=response.get().getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(200,body.length);
            exchange.getResponseBody().write(body);exchange.close();
        });server.start();
        try {
            var client=new RestTrainedRankingClient(RestClient.builder(),new ObjectMapper(),"http://127.0.0.1:"+server.getAddress().getPort(),"v1");
            assertEquals("a",client.rank("u",List.of("a","b"),List.of("a"),"chain",1,1).items().getFirst().itemId());
            assertThrows(IllegalStateException.class,()->client.rank("u",List.of("a","b"),List.of("b"),"chain",1,1));
            response.set(valid.replace("\"v1\"","\"wrong\""));
            assertThrows(IllegalStateException.class,()->client.rank("u",List.of("a","b"),List.of(),"chain",1,1));
            response.set(valid.replace("\"fine_output_count\":1","\"fine_output_count\":0"));
            assertThrows(IllegalStateException.class,()->client.rank("u",List.of("a","b"),List.of(),"chain",1,1));
        } finally {server.stop(0);}
    }
}
