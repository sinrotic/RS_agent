package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;

import java.util.List;

public interface SemanticItemRecallProvider {

    List<ItemEmbeddingText> recall(String requestId, String query, int limit);
}
