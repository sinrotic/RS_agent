package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import java.util.List;
import java.util.Map;

public interface HomeModelRanker {
    Map<String, Double> score(String requestId, String query, List<ItemEmbeddingText> candidates);
}
