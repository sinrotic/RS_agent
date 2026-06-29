package com.sinrotic.rs.user.domain.entity;

import java.time.LocalDateTime;

/**
 * Session and account fields required to resolve the current account.
 */
public record AuthSessionCurrentAccountRecord(
        String sessionId,
        String accountId,
        String profileUserId,
        LocalDateTime accessExpiresAt,
        LocalDateTime revokedAt,
        String username,
        String nickname,
        String accountStatus
) {
}
