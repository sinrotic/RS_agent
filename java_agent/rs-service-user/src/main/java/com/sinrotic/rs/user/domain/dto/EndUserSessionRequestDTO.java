package com.sinrotic.rs.user.domain.dto;

public record EndUserSessionRequestDTO(
        String sessionId,
        String reason
) {

    public String resolvedReason() {
        return reason == null || reason.isBlank() ? "manual" : reason.trim();
    }
}
