package com.sinrotic.rs.user.service.token;

import java.time.LocalDateTime;

public record TokenSession(
        String sessionId,
        String accountId,
        String username,
        String nickname,
        String profileUserId,
        String accessTokenHash,
        String refreshTokenHash,
        LocalDateTime accessExpiresAt,
        LocalDateTime refreshExpiresAt,
        String accountStatus,
        String roles
) {

    public TokenSession(
            String sessionId,
            String accountId,
            String username,
            String nickname,
            String profileUserId,
            String accessTokenHash,
            String refreshTokenHash,
            LocalDateTime accessExpiresAt,
            LocalDateTime refreshExpiresAt,
            String accountStatus
    ) {
        this(
                sessionId,
                accountId,
                username,
                nickname,
                profileUserId,
                accessTokenHash,
                refreshTokenHash,
                accessExpiresAt,
                refreshExpiresAt,
                accountStatus,
                "USER"
        );
    }
}
