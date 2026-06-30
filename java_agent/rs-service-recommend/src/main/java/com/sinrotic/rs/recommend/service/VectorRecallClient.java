package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.recall.VectorRecallItem;

import java.util.List;

/**
 * Searches item embeddings, backed by Milvus in production.
 */
public interface VectorRecallClient {

    List<VectorRecallItem> searchSimilarItems(String collectionName, List<Float> queryVector, int limit);
}
