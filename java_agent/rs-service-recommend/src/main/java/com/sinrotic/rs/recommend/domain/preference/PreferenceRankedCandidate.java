package com.sinrotic.rs.recommend.domain.preference;

import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;

import java.util.List;

public record PreferenceRankedCandidate(
        ItemEmbeddingText item,
        double baseScore,
        double preferenceAdjustment,
        double finalScore,
        List<String> reasonTags
) {
}
