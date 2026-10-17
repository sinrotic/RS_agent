package com.sinrotic.rs.user.domain.vo;

public record EndUserSessionVO(
        String sessionId,
        String status,
        int turnCount,
        SessionSummaryDocumentVO summaryDocument
) {
}
