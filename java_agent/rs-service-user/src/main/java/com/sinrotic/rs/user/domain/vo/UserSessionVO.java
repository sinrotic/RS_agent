package com.sinrotic.rs.user.domain.vo;

import java.time.LocalDateTime;
import java.util.Map;

/**
 * User session response for frontend and Agent flows.
 */
public record UserSessionVO(
        String sessionId,
        String accountId,
        String profileUserId,
        String entryScene,
        String status,
        Map<String, Object> activePreferences,
        LocalDateTime startedAt,
        LocalDateTime lastActiveAt
) {
}
