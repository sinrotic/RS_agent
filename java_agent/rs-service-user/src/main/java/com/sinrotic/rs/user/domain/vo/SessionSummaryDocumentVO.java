package com.sinrotic.rs.user.domain.vo;

public record SessionSummaryDocumentVO(
        String relativePath,
        boolean created,
        String error
) {
}
