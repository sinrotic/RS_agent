package com.sinrotic.rs.user.domain.entity;

import java.time.LocalDateTime;

/**
 * Database entity for rs_auth_session.
 */
public class AuthSession {
    private String sessionId;
    private String accountId;
    private String accessTokenHash;
    private String refreshTokenHash;
    private LocalDateTime accessExpiresAt;
    private LocalDateTime refreshExpiresAt;
    private LocalDateTime revokedAt;
    private String userAgent;
    private String ip;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
