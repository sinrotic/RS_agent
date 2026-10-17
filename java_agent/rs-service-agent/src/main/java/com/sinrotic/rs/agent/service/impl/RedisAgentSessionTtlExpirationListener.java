package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.service.AgentSessionExpirationArchiveService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.redis.connection.Message;
import org.springframework.data.redis.connection.MessageListener;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.util.Optional;

@Component
@ConditionalOnProperty(prefix = "rs.agent.session-expiration", name = "listener-enabled", havingValue = "true")
public class RedisAgentSessionTtlExpirationListener implements MessageListener {

    private static final String TTL_MARKER_PREFIX = "agent:session:";

    private static final String TTL_MARKER_SUFFIX = ":ttl";

    private final AgentSessionExpirationArchiveService archiveService;

    public RedisAgentSessionTtlExpirationListener(AgentSessionExpirationArchiveService archiveService) {
        this.archiveService = archiveService;
    }

    @Override
    public void onMessage(Message message, byte[] pattern) {
        String expiredKey = new String(message.getBody(), StandardCharsets.UTF_8);
        sessionIdFromExpiredKey(expiredKey).ifPresent(archiveService::archiveExpiredSession);
    }

    public static Optional<String> sessionIdFromExpiredKey(String expiredKey) {
        if (expiredKey == null
                || !expiredKey.startsWith(TTL_MARKER_PREFIX)
                || !expiredKey.endsWith(TTL_MARKER_SUFFIX)) {
            return Optional.empty();
        }
        String sessionId = expiredKey.substring(
                TTL_MARKER_PREFIX.length(),
                expiredKey.length() - TTL_MARKER_SUFFIX.length()
        );
        if (sessionId.isBlank() || sessionId.contains(":")) {
            return Optional.empty();
        }
        return Optional.of(sessionId);
    }
}
