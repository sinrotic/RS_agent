package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.service.impl.*;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;

class RecommendationCachedHttpClientTest {
    private RecommendationInferenceCache cache() { return new RecommendationInferenceCache("embed-v1", "rank-v1", 1_000_000, 300); }
    private ItemEmbeddingText item(String text) {
        return new ItemEmbeddingText("actual", text, "Headphones", "audio", "Headphones", "", BigDecimal.ONE, Map.of());
    }
    @Test void embeddingRequestIdsDoNotPreventSharingButChangedTextDoes() {
        var builder = RestClient.builder(); var server = MockRestServiceServer.bindTo(builder).build();
        var client = new RestModelTextEmbeddingClient(builder, "http://model", cache());
        server.expect(requestTo("http://model/internal/model/embed"))
                .andExpect(content().json("{\"model_key\":\"bge\",\"request_id\":\"first\",\"inputs\":{\"texts\":[\"query\"]},\"options\":{\"normalize\":true}}"))
                .andRespond(withSuccess("{\"vectors\":[{\"id\":\"text_0\",\"vector\":[0.1,0.2]}]}", MediaType.APPLICATION_JSON));
        var first = client.embedTexts("bge", "first", List.of("query"));
        assertThat(client.embedTexts("bge", "second-user", List.of("query"))).isEqualTo(first);
        server.verify(); server.reset();
        server.expect(requestTo("http://model/internal/model/embed"))
                .andRespond(withSuccess("{\"vectors\":[{\"id\":\"text_0\",\"vector\":[0.3,0.4]}]}", MediaType.APPLICATION_JSON));
        assertThat(client.embedTexts("bge", "new", List.of("different query"))).isNotEqualTo(first);
        server.verify();
    }
    @Test void rankCacheUsesTextContentAndDoesNotCacheInvalidDownstreamResponses() {
        var builder = RestClient.builder(); var server = MockRestServiceServer.bindTo(builder).build();
        var client = new RestHomeModelRanker(builder, "http://model", cache());
        server.expect(requestTo("http://model/internal/model/rank"))
                .andRespond(withSuccess("{\"items\":[{\"item_id\":\"actual\",\"score\":0.8}]}", MediaType.APPLICATION_JSON));
        assertThat(client.score("first", "headphones", List.of(item("old text")))).containsEntry("actual", .8);
        assertThat(client.score("other-user", "headphones", List.of(item("old text")))).containsEntry("actual", .8);
        server.verify(); server.reset();
        server.expect(requestTo("http://model/internal/model/rank"))
                .andRespond(withSuccess("{\"items\":[{\"item_id\":\"foreign\",\"score\":0.7}]}", MediaType.APPLICATION_JSON));
        assertThatThrownBy(() -> client.score("changed", "headphones", List.of(item("new text"))))
                .isInstanceOf(IllegalStateException.class);
        server.verify(); server.reset();
        server.expect(requestTo("http://model/internal/model/rank"))
                .andRespond(withSuccess("{\"items\":[{\"item_id\":\"actual\",\"score\":0.7}]}", MediaType.APPLICATION_JSON));
        assertThat(client.score("retry", "headphones", List.of(item("new text")))).containsEntry("actual", .7);
        server.verify();
    }
}
