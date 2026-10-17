package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.vo.RagHealthVO;
import com.sinrotic.rs.recommend.service.impl.InMemoryRagTraceService;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class InMemoryRagTraceServiceTest {

    @Test
    void healthReportsConfiguredIndexes() {
        InMemoryRagTraceService service = new InMemoryRagTraceService(
                "rag_bm25_test",
                "rag_milvus_v2_test"
        );

        RagHealthVO health = service.health();

        assertThat(health.providers()).anySatisfy(provider -> {
            assertThat(provider.provider()).isEqualTo("elasticsearch_bm25");
            assertThat(provider.indexName()).isEqualTo("rag_bm25_test");
        });
        assertThat(health.providers()).anySatisfy(provider -> {
            assertThat(provider.provider()).isEqualTo("milvus_vector");
            assertThat(provider.collectionName()).isEqualTo("rag_milvus_v2_test");
        });
    }
}
