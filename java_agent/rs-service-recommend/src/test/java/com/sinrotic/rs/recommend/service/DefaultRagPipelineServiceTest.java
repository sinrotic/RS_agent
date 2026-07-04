package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.dto.RagPipelineRunRequestDTO;
import com.sinrotic.rs.recommend.domain.rag.RagEvidenceHit;
import com.sinrotic.rs.recommend.domain.vo.RagPipelineRunVO;
import com.sinrotic.rs.recommend.service.impl.DefaultRagPipelineService;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

class DefaultRagPipelineServiceTest {

    @Test
    void runFusesDualRecallWithUnweightedRrfThenAppliesBgeRerank() {
        FakeRecallClient bm25 = new FakeRecallClient("elasticsearch_bm25", List.of(
                hit("elasticsearch_bm25", "B001", "title", "Wireless earbuds with ANC", 11.0, 1),
                hit("elasticsearch_bm25", "B002", "description", "Bluetooth speaker for travel", 8.0, 2)
        ));
        FakeRecallClient vector = new FakeRecallClient("milvus_vector", List.of(
                hit("milvus_vector", "B002", "description", "Bluetooth speaker for travel", 0.91, 1),
                hit("milvus_vector", "B001", "title", "Wireless earbuds with ANC", 0.88, 2)
        ));
        FakeRerankClient rerank = new FakeRerankClient(List.of("B001", "B002"));
        DefaultRagPipelineService service = new DefaultRagPipelineService(
                List.of(bm25, vector),
                rerank,
                60,
                "bge-reranker-v2-m3"
        );

        RagPipelineRunVO result = service.run(new RagPipelineRunRequestDTO(
                "rag_req_001",
                "sess_001",
                "noise cancelling bluetooth earbuds",
                List.of("B001", "B002"),
                List.of("elasticsearch_bm25", "milvus_vector"),
                10,
                10,
                2,
                true
        ));

        assertEquals(4, result.stageCounts().rawRecallCount());
        assertEquals(2, result.stageCounts().mergedCount());
        assertEquals(2, result.stageCounts().rerankCount());
        assertEquals(Map.of("elasticsearch_bm25", 2, "milvus_vector", 2), result.sourceDistribution());
        assertEquals("title", result.support().get(0).field());
        assertEquals("Wireless earbuds with ANC", result.support().get(0).summary());
        assertEquals(List.of("B001", "B002"), rerank.receivedItemIds);
        assertEquals("bge-reranker-v2-m3", rerank.modelKey);
    }

    @Test
    void runFallsBackToRrfOrderWhenRerankReturnsNoRows() {
        FakeRecallClient bm25 = new FakeRecallClient("elasticsearch_bm25", List.of(
                hit("elasticsearch_bm25", "B001", "title", "First BM25 hit", 10.0, 1),
                hit("elasticsearch_bm25", "B002", "title", "Second BM25 hit", 9.0, 2)
        ));
        FakeRecallClient vector = new FakeRecallClient("milvus_vector", List.of(
                hit("milvus_vector", "B002", "title", "Second BM25 hit", 0.91, 1)
        ));
        DefaultRagPipelineService service = new DefaultRagPipelineService(
                List.of(bm25, vector),
                new FakeRerankClient(List.of()),
                60,
                "bge-reranker-v2-m3"
        );

        RagPipelineRunVO result = service.run(new RagPipelineRunRequestDTO(
                "rag_req_002",
                "sess_001",
                "speaker",
                List.of("B001", "B002"),
                List.of("elasticsearch_bm25", "milvus_vector"),
                10,
                10,
                2,
                false
        ));

        assertEquals("Second BM25 hit", result.support().get(0).summary());
        assertEquals("First BM25 hit", result.support().get(1).summary());
    }

    @Test
    void runExpandsRerankedEvidenceToFullTextWhenSmall2BigIsEnabled() {
        FakeRecallClient bm25 = new FakeRecallClient("elasticsearch_bm25", List.of(
                hit(
                        "elasticsearch_bm25",
                        "B001",
                        "description",
                        "compact ANC evidence",
                        10.0,
                        1,
                        Map.of("full_text", "Full product description with ANC, battery life, comfort, and commute usage details.")
                ),
                hit("elasticsearch_bm25", "B002", "description", "compact speaker evidence", 8.0, 2)
        ));
        DefaultRagPipelineService service = new DefaultRagPipelineService(
                List.of(bm25),
                new FakeRerankClient(List.of("B001")),
                60,
                "bge-reranker-v2-m3"
        );

        RagPipelineRunVO result = service.run(new RagPipelineRunRequestDTO(
                "rag_req_003",
                "sess_001",
                "commute earbuds",
                List.of("B001", "B002"),
                List.of("elasticsearch_bm25"),
                10,
                10,
                1,
                true
        ));

        assertEquals(1, result.stageCounts().rerankCount());
        assertEquals(1, result.stageCounts().small2bigCount());
        assertEquals("Full product description with ANC, battery life, comfort, and commute usage details.", result.support().getFirst().summary());
        assertEquals("description_full", result.support().getFirst().field());
    }

    private RagEvidenceHit hit(String provider, String itemId, String field, String text, double score, int rank) {
        return new RagEvidenceHit(provider, itemId, field, text, "catalog_rag_chunk", score, rank, Map.of());
    }

    private RagEvidenceHit hit(String provider, String itemId, String field, String text, double score, int rank, Map<String, Object> metadata) {
        return new RagEvidenceHit(provider, itemId, field, text, "catalog_rag_chunk", score, rank, metadata);
    }

    private static final class FakeRecallClient implements RagEvidenceRecallClient {
        private final String providerName;
        private final List<RagEvidenceHit> hits;

        private FakeRecallClient(String providerName, List<RagEvidenceHit> hits) {
            this.providerName = providerName;
            this.hits = hits;
        }

        @Override
        public String providerName() {
            return providerName;
        }

        @Override
        public List<RagEvidenceHit> retrieve(RagPipelineRunRequestDTO request) {
            return hits;
        }
    }

    private static final class FakeRerankClient implements RagRerankClient {
        private final List<String> rerankedItemIds;
        private final List<String> receivedItemIds = new ArrayList<>();
        private String modelKey;

        private FakeRerankClient(List<String> rerankedItemIds) {
            this.rerankedItemIds = rerankedItemIds;
        }

        @Override
        public List<RagEvidenceHit> rerank(String modelKey, String requestId, String query, List<RagEvidenceHit> candidates, int limit) {
            this.modelKey = modelKey;
            receivedItemIds.addAll(candidates.stream().map(RagEvidenceHit::itemId).toList());
            return rerankedItemIds.stream()
                    .flatMap(itemId -> candidates.stream().filter(candidate -> itemId.equals(candidate.itemId())).limit(1))
                    .limit(limit)
                    .toList();
        }
    }
}
