package com.sinrotic.rs.user.service.token;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.Optional;

@Service
@ConditionalOnProperty(prefix = "rs.auth.token-store", name = "type", havingValue = "redis")
public class RedisTokenSessionStore implements TokenSessionStore {

    private static final String ACCESS_KEY_PREFIX = "auth:access:";
    private static final String REFRESH_KEY_PREFIX = "auth:refresh:";
    private static final String SESSION_KEY_PREFIX = "auth:session:";

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;

    public RedisTokenSessionStore(StringRedisTemplate redisTemplate) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = new ObjectMapper().registerModule(new JavaTimeModule());
    }

    @Override
    public void save(TokenSession session) {
        String payload = writeSession(session);
        redisTemplate.opsForValue().set(
                ACCESS_KEY_PREFIX + session.accessTokenHash(),
                payload,
                ttlUntil(session.accessExpiresAt())
        );
        redisTemplate.opsForValue().set(
                REFRESH_KEY_PREFIX + session.refreshTokenHash(),
                payload,
                ttlUntil(session.refreshExpiresAt())
        );
        redisTemplate.opsForValue().set(
                SESSION_KEY_PREFIX + session.sessionId(),
                payload,
                ttlUntil(session.refreshExpiresAt())
        );
    }

    @Override
    public Optional<TokenSession> findByAccessTokenHash(String accessTokenHash) {
        return readSession(ACCESS_KEY_PREFIX + accessTokenHash)
                .filter(session -> session.accessExpiresAt().isAfter(LocalDateTime.now()));
    }

    @Override
    public Optional<TokenSession> findByRefreshTokenHash(String refreshTokenHash) {
        return readSession(REFRESH_KEY_PREFIX + refreshTokenHash)
                .filter(session -> session.refreshExpiresAt().isAfter(LocalDateTime.now()));
    }

    @Override
    public void revokeSession(String sessionId) {
        readSession(SESSION_KEY_PREFIX + sessionId).ifPresent(session -> {
            redisTemplate.delete(ACCESS_KEY_PREFIX + session.accessTokenHash());
            redisTemplate.delete(REFRESH_KEY_PREFIX + session.refreshTokenHash());
            redisTemplate.delete(SESSION_KEY_PREFIX + session.sessionId());
        });
    }

    private Optional<TokenSession> readSession(String key) {
        String payload = redisTemplate.opsForValue().get(key);
        if (payload == null || payload.isBlank()) {
            return Optional.empty();
        }
        try {
            return Optional.of(objectMapper.readValue(payload, TokenSession.class));
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("token session payload is not valid JSON", ex);
        }
    }

    private String writeSession(TokenSession session) {
        try {
            return objectMapper.writeValueAsString(session);
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("failed to serialize token session", ex);
        }
    }

    private Duration ttlUntil(LocalDateTime expiresAt) {
        Duration ttl = Duration.between(LocalDateTime.now(), expiresAt);
        return ttl.isNegative() || ttl.isZero() ? Duration.ofSeconds(1) : ttl;
    }
}
