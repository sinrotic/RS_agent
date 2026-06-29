package com.sinrotic.rs.user.service.token;

import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

@Service
@ConditionalOnMissingBean(TokenSessionStore.class)
public class InMemoryTokenSessionStore implements TokenSessionStore {

    private final ConcurrentMap<String, TokenSession> accessTokenSessions = new ConcurrentHashMap<>();
    private final ConcurrentMap<String, TokenSession> refreshTokenSessions = new ConcurrentHashMap<>();
    private final ConcurrentMap<String, TokenSession> sessionIndex = new ConcurrentHashMap<>();

    @Override
    public void save(TokenSession session) {
        accessTokenSessions.put(session.accessTokenHash(), session);
        refreshTokenSessions.put(session.refreshTokenHash(), session);
        sessionIndex.put(session.sessionId(), session);
    }

    @Override
    public Optional<TokenSession> findByAccessTokenHash(String accessTokenHash) {
        return Optional.ofNullable(accessTokenSessions.get(accessTokenHash))
                .filter(session -> session.accessExpiresAt().isAfter(LocalDateTime.now()));
    }

    @Override
    public Optional<TokenSession> findByRefreshTokenHash(String refreshTokenHash) {
        return Optional.ofNullable(refreshTokenSessions.get(refreshTokenHash))
                .filter(session -> session.refreshExpiresAt().isAfter(LocalDateTime.now()));
    }

    @Override
    public void revokeSession(String sessionId) {
        TokenSession session = sessionIndex.remove(sessionId);
        if (session == null) {
            return;
        }
        accessTokenSessions.remove(session.accessTokenHash());
        refreshTokenSessions.remove(session.refreshTokenHash());
    }
}
