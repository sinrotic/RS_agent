package com.sinrotic.rs.gateway.filter;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Optional;
import java.time.LocalDateTime;

@Service
@ConditionalOnProperty(prefix = "rs.gateway.auth", name = "token-validation", havingValue = "redis")
public class RedisGatewayTokenValidator implements GatewayTokenValidator {

    private static final String ACCESS_KEY_PREFIX = "auth:access:";
    private static final String SESSION_KEY_PREFIX = "auth:session:";

    private final ReactiveStringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper = new ObjectMapper().registerModule(new JavaTimeModule());

    public RedisGatewayTokenValidator(ReactiveStringRedisTemplate redisTemplate) {
        this.redisTemplate = redisTemplate;
    }

    @Override
    public Mono<GatewayUserContext> validate(String accessToken) {
        if (accessToken == null || accessToken.isBlank()) {
            return Mono.empty();
        }
        String tokenHash = sha256Hex(accessToken);
        return redisTemplate.opsForValue()
                .get(ACCESS_KEY_PREFIX + tokenHash)
                .filter(payload -> !payload.isBlank())
                .flatMap(payload -> {
                    try {
                        JsonNode session = objectMapper.readTree(payload);
                        String sessionId = session.path("sessionId").asText("");
                        LocalDateTime expiresAt = objectMapper.treeToValue(session.path("accessExpiresAt"),LocalDateTime.class);
                        if (sessionId.isBlank() || !tokenHash.equals(session.path("accessTokenHash").asText())
                                || expiresAt == null || !expiresAt.isAfter(LocalDateTime.now())) return Mono.empty();
                        return redisTemplate.opsForValue().get(SESSION_KEY_PREFIX + sessionId)
                                .filter(payload::equals)
                                .flatMap(canonical -> Mono.justOrEmpty(readUserContext(canonical)));
                    } catch (JsonProcessingException failure) {
                        return Mono.empty();
                    }
                });
    }

    private Optional<GatewayUserContext> readUserContext(String payload) {
        try {
            JsonNode root = objectMapper.readTree(payload);
            if (!"active".equals(root.path("accountStatus").asText())
                    || root.path("accountId").asText("").isBlank()
                    || root.path("profileUserId").asText("").isBlank()) {
                return Optional.empty();
            }
            return Optional.of(new GatewayUserContext(
                    root.path("accountId").asText(null),
                    root.path("profileUserId").asText(null),
                    readRoles(root)
            ));
        } catch (JsonProcessingException ex) {
            return Optional.empty();
        }
    }

    private String readRoles(JsonNode root) {
        JsonNode roles = root.path("roles");
        if (roles.isArray()) {
            StringBuilder value = new StringBuilder();
            roles.forEach(role -> {
                if (!role.asText().isBlank()) {
                    if (!value.isEmpty()) {
                        value.append(',');
                    }
                    value.append(role.asText());
                }
            });
            return value.isEmpty() ? "USER" : value.toString();
        }
        String value = roles.asText("");
        return value.isBlank() ? "USER" : value;
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
