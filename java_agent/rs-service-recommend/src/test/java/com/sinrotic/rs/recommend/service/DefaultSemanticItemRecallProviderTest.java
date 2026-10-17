package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.domain.recall.VectorRecallItem;
import com.sinrotic.rs.recommend.service.impl.DefaultSemanticItemRecallProvider;
import com.sinrotic.rs.recommend.service.impl.RestProductQueryTowerClient;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.*;

class DefaultSemanticItemRecallProviderTest {

    @Test
    void embedsQuerySearchesMilvusAndRestoresRecallOrderAfterCatalogHydration() {
        TextEmbeddingClient embeddings = (modelKey, requestId, texts) -> {
            assertEquals("bge-m3", modelKey);
            assertEquals(List.of("noise cancelling headphones"), texts);
            return List.of(List.of(0.1f, 0.2f, 0.3f));
        };
        VectorRecallClient vectors = (collectionName, queryVector, limit) -> {
            assertEquals("rs_agent_semantic_items_bge_m3_v1", collectionName);
            assertEquals(List.of(0.1f, 0.2f, 0.3f), queryVector);
            return List.of(new VectorRecallItem("HEADPHONES", 0.9), new VectorRecallItem("EARBUDS", 0.8));
        };
        CatalogEmbeddingTextClient catalog = new CatalogEmbeddingTextClient() {
            @Override
            public List<ItemEmbeddingText> fetchActiveItemEmbeddingTexts(String afterItemId, int limit) {
                return List.of();
            }

            @Override
            public List<ItemEmbeddingText> fetchItemEmbeddingTexts(List<String> itemIds) {
                assertEquals(List.of("HEADPHONES", "EARBUDS"), itemIds);
                return List.of(item("EARBUDS"), item("HEADPHONES"));
            }
        };
        DefaultSemanticItemRecallProvider provider = new DefaultSemanticItemRecallProvider(
                embeddings, vectors, catalog, "bge-m3", "rs_agent_semantic_items_bge_m3_v1");

        List<ItemEmbeddingText> result = provider.recall("req-1", "noise cancelling headphones", 20);

        assertEquals(List.of("HEADPHONES", "EARBUDS"), result.stream().map(ItemEmbeddingText::itemId).toList());
    }

    @Test void trainedQueryUsesItsOwnItemSpaceAndBgeSupplementsMissingCoverage() {
        var tower = mock(RestProductQueryTowerClient.class);
        when(tower.enabled()).thenReturn(true); when(tower.collection()).thenReturn("product");
        when(tower.project(List.of(1f, 0f))).thenReturn(List.of(0f, 1f));
        var catalog = mock(CatalogEmbeddingTextClient.class);
        when(catalog.fetchItemEmbeddingTexts(anyList())).thenAnswer(call -> {
            List<String> ids = call.getArgument(0); assertTrue(ids.size() <= 100);
            return ids.stream().map(this::item).toList();
        });
        VectorRecallClient vectors = (collection, vector, limit) -> {
            if (collection.equals("product")) {
                assertEquals(List.of(0f, 1f), vector); assertEquals(130, limit);
                return java.util.stream.IntStream.range(0, 130).mapToObj(i -> new VectorRecallItem("p"+i,.5)).toList();
            }
            assertEquals(List.of(1f, 0f), vector);
            return java.util.stream.IntStream.range(0, 200).mapToObj(i -> new VectorRecallItem("b"+i,.9)).toList();
        };
        var provider = new DefaultSemanticItemRecallProvider((m,r,t)->List.of(List.of(1f,0f)), vectors, catalog, "bge", "legacy");
        provider.setQueryTower(tower);
        var items = provider.recall("query", "keyboard", 200);
        assertEquals(200, items.size()); assertEquals(130, items.stream().filter(i->i.itemId().startsWith("p")).count());
        when(tower.project(anyList())).thenThrow(new IllegalStateException("down"));
        items = provider.recall("fallback", "keyboard", 200);
        assertEquals(200, items.size()); assertTrue(items.stream().allMatch(i->i.itemId().startsWith("b")));
    }

    private ItemEmbeddingText item(String itemId) {
        return new ItemEmbeddingText(itemId, "text", itemId, "Audio", "Audio", "brand", BigDecimal.TEN, Map.of());
    }
}
