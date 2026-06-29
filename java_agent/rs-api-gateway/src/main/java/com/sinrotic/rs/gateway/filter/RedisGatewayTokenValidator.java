package com.sinrotic.rs.gateway.filter;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Optional;

@Service
@ConditionalOnProperty(prefix = "rs.gateway.auth", name = "token-validation", havingValue = "redis")
public class RedisGatewayTokenValidator implements GatewayTokenValidator {

    private static final String ACCESS_KEY_PREFIX = "auth:access:";

    private final ReactiveStringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public RedisGatewayTokenValidator(ReactiveStringRedisTemplate redisTemplate) {
        this.redisTemplate = redisTemplate;
    }

    @Override
    public Optional<GatewayUserContext> validate(String accessToken) {
        if (accessToken == null || accessToken.isBlank()) {
            return Optional.empty();
        }
        String payload = redisTemplate.opsForValue()
                .get(ACCESS_KEY_PREFIX + sha256Hex(accessToken))
                .block();
        if (payload == null || payload.isBlank()) {
            return Optional.empty();
        }
        return readUserContext(payload);
    }

    private Optional<GatewayUserContext> readUserContext(String payload) {
        try {
            JsonNode root = objectMapper.readTree(payload);
            if (!"active".equals(root.path("accountStatus").asText())) {
                return Optional.empty();
            }
            return Optional.of(new GatewayUserContext(
                    root.path("accountId").asText(null),
                    root.path("profileUserId").asText(null),
                    "USER"
            ));
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("redis token session payload is not valid JSON", ex);
        }
    }

    private String sha256Hex(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is not available", exception);
        }
    }
}
