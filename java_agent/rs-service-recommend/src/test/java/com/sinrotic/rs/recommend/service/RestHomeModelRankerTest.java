package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.service.impl.RestHomeModelRanker;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;

class RestHomeModelRankerTest {
    @Test void keepsRuntimeScoreAndRejectsForeignIds() {
        var builder = RestClient.builder();
        var server = MockRestServiceServer.bindTo(builder).build();
        var ranker = new RestHomeModelRanker(builder, "http://model");
        var candidates = List.of(new ItemEmbeddingText("actual", "headphones", "headphones", "audio", "audio", "", BigDecimal.ONE, Map.of()));
        server.expect(requestTo("http://model/internal/model/rank"))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("actual")))
                .andRespond(withSuccess("{\"items\":[{\"item_id\":\"actual\",\"score\":0.99}]}", MediaType.APPLICATION_JSON));
        assertEquals(.99, ranker.score("request", "headphones", candidates).get("actual"));
        server.verify();
        server.reset();
        server.expect(requestTo("http://model/internal/model/rank"))
                .andRespond(withSuccess("{\"items\":[{\"item_id\":\"foreign\",\"score\":0.99}]}", MediaType.APPLICATION_JSON));
        assertThrows(IllegalStateException.class, () -> ranker.score("request", "headphones", candidates));
    }
}
