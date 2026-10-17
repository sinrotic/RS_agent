package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;

import java.util.List;

public interface CatalogEmbeddingTextClient {

    List<ItemEmbeddingText> fetchActiveItemEmbeddingTexts(String afterItemId, int limit);

    default List<ItemEmbeddingText> fetchItemEmbeddingTexts(List<String> itemIds) {
        return List.of();
    }

    default List<ItemEmbeddingText> discover(String seed, int limit) {
        return fetchActiveItemEmbeddingTexts("", limit);
    }

    default List<ItemEmbeddingText> categoryCandidates(String category, String seed, int limit) { return List.of(); }
}
