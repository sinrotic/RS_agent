package com.sinrotic.rs.recommend.domain.recall;

/**
 * Item hit returned by a vector index.
 */
public record VectorRecallItem(
        String itemId,
        double score
) {
}
