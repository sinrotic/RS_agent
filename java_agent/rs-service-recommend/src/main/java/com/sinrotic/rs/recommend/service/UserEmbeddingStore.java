package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.recall.UserEmbedding;

import java.util.Optional;

/**
 * Reads and writes cached user embeddings, backed by Scylla in production.
 */
public interface UserEmbeddingStore {

    Optional<UserEmbedding> find(String modelName, String userId);

    void save(UserEmbedding embedding);
}
