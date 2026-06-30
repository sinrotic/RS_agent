package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.domain.recall.ItemVectorDocument;
import com.sinrotic.rs.recommend.domain.vo.SemanticItemIndexResultVO;
import com.sinrotic.rs.recommend.service.impl.DefaultSemanticItemIndexService;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

class DefaultSemanticItemIndexServiceTest {

    @Test
    void rebuildEmbedsCatalogMysqlPagesAndUpsertsVectorsToMilvus() {
        FakeCatalogEmbeddingTextClient catalogClient = new FakeCatalogEmbeddingTextClient(List.of(
                List.of(item("B001", "Title: Backpack"), item("B002", "Title: Stapler")),
                List.of(item("B003", "Title: Notebook")),
                List.of()
        ));
        FakeTextEmbeddingClient embeddingClient = new FakeTextEmbeddingClient();
        FakeItemVectorIndexClient indexClient = new FakeItemVectorIndexClient();
        DefaultSemanticItemIndexService service = new DefaultSemanticItemIndexService(
                catalogClient,
                embeddingClient,
                indexClient,
                "bge-m3",
                "rs_agent_semantic_items_bge_m3_v1"
        );

        SemanticItemIndexResultVO result = service.rebuild("idx_req_001", 2, 5);

        assertEquals(3, result.indexedCount());
        assertEquals(2, result.pageCount());
        assertEquals("B003", result.lastItemId());
        assertEquals(3, catalogClient.afterItemIds.size());
        assertEquals(null, catalogClient.afterItemIds.get(0));
        assertEquals("B002", catalogClient.afterItemIds.get(1));
        assertEquals("B003", catalogClient.afterItemIds.get(2));
        assertEquals(List.of("Title: Backpack", "Title: Stapler"), embeddingClient.batches.getFirst());
        assertEquals("rs_agent_semantic_items_bge_m3_v1", indexClient.collections.getFirst());
        assertEquals(List.of("B001", "B002"), indexClient.batches.getFirst().stream().map(ItemVectorDocument::itemId).toList());
        assertEquals(List.of(0.1f, 0.2f, 0.3f), indexClient.batches.getFirst().getFirst().vector());
    }

    private ItemEmbeddingText item(String itemId, String text) {
        return new ItemEmbeddingText(
                itemId,
                text,
                itemId + " title",
                "Office",
                "Office > Supplies",
                "Brand",
                new BigDecimal("9.99"),
                Map.of("material", "paper")
        );
    }

    private static final class FakeCatalogEmbeddingTextClient implements CatalogEmbeddingTextClient {
        private final List<List<ItemEmbeddingText>> pages;
        private final List<String> afterItemIds = new ArrayList<>();
        private int calls;

        private FakeCatalogEmbeddingTextClient(List<List<ItemEmbeddingText>> pages) {
            this.pages = pages;
        }

        @Override
        public List<ItemEmbeddingText> fetchActiveItemEmbeddingTexts(String afterItemId, int limit) {
            afterItemIds.add(afterItemId);
            return pages.get(calls++);
        }
    }

    private static final class FakeTextEmbeddingClient implements TextEmbeddingClient {
        private final List<List<String>> batches = new ArrayList<>();

        @Override
        public List<List<Float>> embedTexts(String modelKey, String requestId, List<String> texts) {
            batches.add(new ArrayList<>(texts));
            return texts.stream()
                    .map(ignored -> List.of(0.1f, 0.2f, 0.3f))
                    .toList();
        }
    }

    private static final class FakeItemVectorIndexClient implements ItemVectorIndexClient {
        private final List<String> collections = new ArrayList<>();
        private final List<List<ItemVectorDocument>> batches = new ArrayList<>();

        @Override
        public int upsertItems(String collectionName, List<ItemVectorDocument> documents) {
            collections.add(collectionName);
            batches.add(new ArrayList<>(documents));
            return documents.size();
        }
    }
}
