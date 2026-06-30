package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.recall.UserEmbedding;

import java.util.List;
import java.util.Optional;

/**
 * Calls model-service user tower inference.
 */
public interface UserTowerModelClient {

    Optional<UserEmbedding> inferUserEmbedding(String modelName, String requestId, String userId, List<String> historyItemIds);
}
