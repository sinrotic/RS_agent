package com.sinrotic.rs.user.domain.entity;

import java.time.LocalDateTime;

/**
 * Session and account fields required by refresh-token rotation.
 */
public record AuthSessionRefreshRecord(
        String sessionId,
        String accountId,
        String profileUserId,
        LocalDateTime refreshExpiresAt,
        LocalDateTime revokedAt,
        String username,
        String nickname,
        String accountStatus
) {
}
