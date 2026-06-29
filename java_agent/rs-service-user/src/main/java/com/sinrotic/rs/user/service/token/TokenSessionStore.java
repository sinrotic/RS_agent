package com.sinrotic.rs.user.service.token;

import java.util.Optional;

public interface TokenSessionStore {

    void save(TokenSession session);

    Optional<TokenSession> findByAccessTokenHash(String accessTokenHash);

    Optional<TokenSession> findByRefreshTokenHash(String refreshTokenHash);

    void revokeSession(String sessionId);
}
