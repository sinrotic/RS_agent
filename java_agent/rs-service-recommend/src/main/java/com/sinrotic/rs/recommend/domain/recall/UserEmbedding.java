package com.sinrotic.rs.recommend.domain.recall;

import java.util.List;

/**
 * User vector used by two-tower recall.
 */
public record UserEmbedding(
        String modelName,
        String userId,
        List<Float> embedding,
        String source
) {

    public UserEmbedding {
        embedding = embedding == null ? List.of() : List.copyOf(embedding);
    }
}
