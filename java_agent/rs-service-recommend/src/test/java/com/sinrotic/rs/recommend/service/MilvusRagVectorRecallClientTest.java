package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.dto.RagPipelineRunRequestDTO;
import com.sinrotic.rs.recommend.service.impl.MilvusRagVectorRecallClient;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class MilvusRagVectorRecallClientTest {

    @Test
    void retrieveRejectsMilvusBusinessErrorReturnedWithHttpSuccess() {
        RestClient.Builder restClientBuilder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(restClientBuilder).build();
        TextEmbeddingClient embeddingClient = (modelKey, requestId, texts) -> List.of(List.of(0.1f, 0.2f));
        MilvusRagVectorRecallClient client = new MilvusRagVectorRecallClient(
                embeddingClient,
                restClientBuilder,
                "http://milvus",
                "",
                "rag_v2_test",
                "bge-m3"
        );
        server.expect(requestTo("http://milvus/v2/vectordb/entities/search"))
                .andRespond(withSuccess("{\"code\":1100,\"message\":\"dimension mismatch\"}", MediaType.APPLICATION_JSON));

        RagPipelineRunRequestDTO request = new RagPipelineRunRequestDTO(
                "request-1",
                "session-1",
                "clipboard",
                List.of("item-1"),
                List.of("milvus_vector"),
                5,
                5,
                1,
                false
        );

        assertThatThrownBy(() -> client.retrieve(request))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("code 1100")
                .hasMessageContaining("dimension mismatch");
        server.verify();
    }
}
