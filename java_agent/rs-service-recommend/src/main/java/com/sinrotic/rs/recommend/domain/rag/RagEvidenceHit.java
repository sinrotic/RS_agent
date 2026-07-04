package com.sinrotic.rs.recommend.domain.rag;

import java.util.List;
import java.util.Map;

public record RagEvidenceHit(
        String provider,
        String itemId,
        String field,
        String text,
        String source,
        double score,
        int rank,
        Map<String, Object> metadata
) {

    public RagEvidenceHit {
        provider = provider == null ? "" : provider;
        itemId = itemId == null ? "" : itemId;
        field = field == null || field.isBlank() ? "evidence" : field;
        text = text == null ? "" : text;
        source = source == null ? "" : source;
        rank = Math.max(1, rank);
        metadata = metadata == null ? Map.of() : Map.copyOf(metadata);
    }

    public RagEvidenceHit withScore(double newScore) {
        return new RagEvidenceHit(provider, itemId, field, text, source, newScore, rank, metadata);
    }

    public RagEvidenceHit withRank(int newRank) {
        return new RagEvidenceHit(provider, itemId, field, text, source, score, newRank, metadata);
    }

    public String key() {
        return String.join("\u001f", List.of(itemId, field, text));
    }
}
