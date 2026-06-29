package com.sinrotic.rs.user.domain.vo;

import java.util.Map;

/**
 * Internal session context consumed by recommendation and Agent services.
 */
public record SessionContextVO(
        String sessionId,
        String accountId,
        String profileUserId,
        Map<String, Object> activePreferences,
        String profileSummary
) {
}
