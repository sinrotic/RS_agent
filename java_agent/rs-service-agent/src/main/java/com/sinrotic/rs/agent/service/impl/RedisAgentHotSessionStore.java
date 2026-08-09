package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.config.AgentSessionStoreProperties;
import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.domain.session.AgentSessionSnapshot;
import com.sinrotic.rs.agent.service.AgentHotSessionStore;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.Duration;
import java.util.List;
import java.util.Optional;

/** Redis-backed hot-session store. Conversation content remains internal to the Agent runtime. */
public class RedisAgentHotSessionStore implements AgentHotSessionStore {

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final AgentSessionStoreProperties properties;

    public RedisAgentHotSessionStore(
            StringRedisTemplate redisTemplate,
            ObjectMapper objectMapper,
            AgentSessionStoreProperties properties
    ) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.properties = properties;
    }

    @Override
    public void append(AgentSessionEvent event) {
        redisTemplate.opsForList().rightPush(eventsKey(event.sessionId()), write(event));
        refreshTtl(event.sessionId());
    }

    @Override
    public List<AgentSessionEvent> events(String sessionId) {
        List<String> rawEvents = redisTemplate.opsForList().range(eventsKey(sessionId), 0, -1);
        if (rawEvents == null || rawEvents.isEmpty()) {
            return List.of();
        }
        return rawEvents.stream().map(rawEvent -> read(rawEvent, AgentSessionEvent.class)).toList();
    }

    @Override
    public void replaceEvents(String sessionId, List<AgentSessionEvent> replacement) {
        String key = eventsKey(sessionId);
        redisTemplate.delete(key);
        List<String> serialized = List.copyOf(replacement == null ? List.of() : replacement).stream()
                .map(this::write)
                .toList();
        if (!serialized.isEmpty()) {
            redisTemplate.opsForList().rightPushAll(key, serialized);
            refreshTtl(sessionId);
        }
    }

    @Override
    public void storeSnapshot(AgentSessionSnapshot snapshot) {
        Duration ttl = properties.getTtl();
        if (hasTtl(ttl)) {
            redisTemplate.opsForValue().set(snapshotKey(snapshot.sessionId()), write(snapshot), ttl);
        } else {
            redisTemplate.opsForValue().set(snapshotKey(snapshot.sessionId()), write(snapshot));
        }
    }

    @Override
    public Optional<AgentSessionSnapshot> latestSnapshot(String sessionId) {
        String rawSnapshot = redisTemplate.opsForValue().get(snapshotKey(sessionId));
        if (rawSnapshot == null || rawSnapshot.isBlank()) {
            return Optional.empty();
        }
        return Optional.of(read(rawSnapshot, AgentSessionSnapshot.class));
    }

    private void refreshTtl(String sessionId) {
        Duration ttl = properties.getTtl();
        if (hasTtl(ttl)) {
            redisTemplate.expire(eventsKey(sessionId), ttl);
        }
    }

    private boolean hasTtl(Duration ttl) {
        return ttl != null && !ttl.isZero() && !ttl.isNegative();
    }

    private String write(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("failed to serialize agent session value", error);
        }
    }

    private <T> T read(String value, Class<T> type) {
        try {
            return objectMapper.readValue(value, type);
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("failed to deserialize agent session value", error);
        }
    }

    private String eventsKey(String sessionId) {
        return properties.getKeyPrefix() + sessionId + ":events";
    }

    private String snapshotKey(String sessionId) {
        return properties.getKeyPrefix() + sessionId + ":snapshot";
    }
}
