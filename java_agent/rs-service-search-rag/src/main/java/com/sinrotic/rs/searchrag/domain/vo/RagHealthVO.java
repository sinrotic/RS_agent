package com.sinrotic.rs.searchrag.domain.vo;

import java.util.List;

/**
 * RAG service health summary.
 */
public record RagHealthVO(
        String status,
        List<RagHealthProviderVO> providers
) {
}
