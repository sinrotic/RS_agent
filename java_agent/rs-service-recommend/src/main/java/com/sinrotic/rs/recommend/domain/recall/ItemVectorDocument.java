package com.sinrotic.rs.recommend.domain.recall;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

public record ItemVectorDocument(
        String itemId,
        List<Float> vector,
        String title,
        String category,
        String categoryPath,
        String brand,
        BigDecimal price,
        String embeddingText,
        Map<String, String> attributes
) {
}
