package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.recall.UserEmbedding;
import com.sinrotic.rs.recommend.domain.recall.VectorRecallItem;
import com.sinrotic.rs.recommend.domain.vo.PipelineCandidateVO;
import com.sinrotic.rs.recommend.service.TwoTowerRecallProvider;
import com.sinrotic.rs.recommend.service.UserEmbeddingStore;
import com.sinrotic.rs.recommend.service.UserHistoryClient;
import com.sinrotic.rs.recommend.service.UserTowerModelClient;
import com.sinrotic.rs.recommend.service.VectorRecallClient;

import java.util.List;
import java.util.Optional;

/**
 * Orchestrates cached user embeddings, real-time user tower inference, and Milvus item recall.
 */
public class DefaultTwoTowerRecallProvider implements TwoTowerRecallProvider {

    public static final String MODEL_NAME = "two_tower_youtube_dnn_epoch1";
    public static final String ITEM_COLLECTION = "rs_agent_two_tower_items_v1";
    private static final int DEFAULT_HISTORY_LIMIT = 100;
    private static final int MIN_HISTORY_ITEMS = 2;

    private final UserEmbeddingStore userEmbeddingStore;
    private final UserHistoryClient userHistoryClient;
    private final UserTowerModelClient userTowerModelClient;
    private final VectorRecallClient vectorRecallClient;

    public DefaultTwoTowerRecallProvider(
            UserEmbeddingStore userEmbeddingStore,
            UserHistoryClient userHistoryClient,
            UserTowerModelClient userTowerModelClient,
            VectorRecallClient vectorRecallClient
    ) {
        this.userEmbeddingStore = userEmbeddingStore;
        this.userHistoryClient = userHistoryClient;
        this.userTowerModelClient = userTowerModelClient;
        this.vectorRecallClient = vectorRecallClient;
    }

    @Override
    public List<PipelineCandidateVO> recall(String userId, String requestId, int limit) {
        if (userId == null || userId.isBlank() || limit <= 0) {
            return List.of();
        }
        Optional<UserEmbedding> embedding = getOrBuildUserEmbedding(userId, requestId);
        if (embedding.isEmpty()) {
            return List.of();
        }
        return vectorRecallClient.searchSimilarItems(ITEM_COLLECTION, embedding.get().embedding(), limit).stream()
                .map(this::toCandidate)
                .toList();
    }

    private Optional<UserEmbedding> getOrBuildUserEmbedding(String userId, String requestId) {
        Optional<UserEmbedding> cached = userEmbeddingStore.find(MODEL_NAME, userId);
        if (cached.isPresent() && !cached.get().embedding().isEmpty()) {
            return cached;
        }

        List<String> historyItemIds = userHistoryClient.recentItemIds(userId, DEFAULT_HISTORY_LIMIT);
        if (historyItemIds.size() < MIN_HISTORY_ITEMS) {
            return Optional.empty();
        }
        Optional<UserEmbedding> inferred = userTowerModelClient.inferUserEmbedding(MODEL_NAME, requestId, userId, historyItemIds);
        inferred.filter(value -> !value.embedding().isEmpty()).ifPresent(userEmbeddingStore::save);
        return inferred.filter(value -> !value.embedding().isEmpty());
    }

    private PipelineCandidateVO toCandidate(VectorRecallItem item) {
        return new PipelineCandidateVO(
                item.itemId(),
                "two_tower",
                item.score(),
                null,
                null,
                null
        );
    }
}
