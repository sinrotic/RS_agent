package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;

import java.util.List;

public interface CatalogEmbeddingTextClient {

    List<ItemEmbeddingText> fetchActiveItemEmbeddingTexts(String afterItemId, int limit);
}
