package com.sinrotic.rs.recommend.domain.vo;

import java.util.List;

/**
 * Recommendation RAG health summary.
 */
public record RagHealthVO(
        String status,
        List<RagHealthProviderVO> providers
) {
}
