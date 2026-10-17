package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.recall.UserEmbedding;

import java.util.Optional;

/**
 * Caches rebuildable user vectors; history-aware keys prevent stale interest vectors.
 */
public interface UserEmbeddingStore {

    Optional<UserEmbedding> find(String modelName, String userId);

    void save(UserEmbedding embedding);

    default Optional<UserEmbedding> find(String modelName, String userId, java.util.List<String> history) {
        return find(modelName, userId);
    }

    default void save(UserEmbedding embedding, java.util.List<String> history) { save(embedding); }
}
