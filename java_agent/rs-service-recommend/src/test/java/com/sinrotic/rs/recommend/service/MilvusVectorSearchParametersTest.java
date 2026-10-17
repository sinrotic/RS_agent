package com.sinrotic.rs.recommend.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.service.impl.MilvusRestVectorIndexClient;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.core.env.SystemEnvironmentPropertySource;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class MilvusVectorSearchParametersTest {
    @Test
    void containerEnvironmentConfiguresSearchWidthThroughSpring() {
        var builder = RestClient.builder();
        var server = MockRestServiceServer.bindTo(builder).build();
        server.expect(requestTo("http://milvus/v2/vectordb/entities/search"))
                .andExpect(jsonPath("$.searchParams.params.ef").value(1024))
                .andRespond(withSuccess("{\"code\":0,\"data\":[]}", MediaType.APPLICATION_JSON));
        new ApplicationContextRunner()
                .withInitializer(context -> context.getEnvironment().getPropertySources().addFirst(
                        new SystemEnvironmentPropertySource("container", Map.of("RS_RECOMMEND_VECTOR_SEARCH_EF", "1024"))))
                .withPropertyValues("rs.milvus.base-url=http://milvus")
                .withBean(RestClient.Builder.class, () -> builder)
                .withBean(ObjectMapper.class, ObjectMapper::new)
                .withBean(MilvusRestVectorIndexClient.class)
                .run(context -> context.getBean(MilvusRestVectorIndexClient.class)
                        .searchSimilarItems("expanded", List.of(0.1f, 0.2f), 100));
        server.verify();
    }

    @Test
    void defaultKeepsExistingServerSearchSettings() {
        var builder = RestClient.builder();
        var server = MockRestServiceServer.bindTo(builder).build();
        var client = new MilvusRestVectorIndexClient(builder, new ObjectMapper(), "http://milvus", "");
        server.expect(requestTo("http://milvus/v2/vectordb/entities/search"))
                .andExpect(jsonPath("$.searchParams").doesNotExist())
                .andRespond(withSuccess("{\"code\":0,\"data\":[]}", MediaType.APPLICATION_JSON));
        assertThat(client.searchSimilarItems("old", List.of(0.1f, 0.2f), 100)).isEmpty();
        server.verify();
    }

    @Test
    void configuredSearchWidthIsSentToMilvusAndNeverBelowRequestedTopK() {
        var builder = RestClient.builder();
        var server = MockRestServiceServer.bindTo(builder).build();
        var client = new MilvusRestVectorIndexClient(builder, new ObjectMapper(), "http://milvus", "");
        client.configureSearch(1024);
        for (int limit : List.of(100, 1500)) {
            server.expect(requestTo("http://milvus/v2/vectordb/entities/search"))
                    .andExpect(jsonPath("$.searchParams.params.ef").value(Math.max(1024, limit)))
                    .andExpect(jsonPath("$.limit").value(limit))
                    .andRespond(withSuccess("{\"code\":0,\"data\":[{\"item_id\":\"a\",\"distance\":0.8}]}", MediaType.APPLICATION_JSON));
        }
        for (int limit : List.of(100, 1500)) {
            assertThat(client.searchSimilarItems("expanded", List.of(0.1f, 0.2f), limit).getFirst().itemId()).isEqualTo("a");
        }
        server.verify();
    }

    @Test
    void invalidSearchWidthFailsAtConfigurationTime() {
        var client = new MilvusRestVectorIndexClient(RestClient.builder(), new ObjectMapper(), "http://milvus", "");
        assertThatThrownBy(() -> client.configureSearch(-1)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> client.configureSearch(32769)).isInstanceOf(IllegalArgumentException.class);
    }
}
