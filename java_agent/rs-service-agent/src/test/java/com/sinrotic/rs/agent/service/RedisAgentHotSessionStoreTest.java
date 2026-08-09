package com.sinrotic.rs.agent.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.config.AgentSessionStoreProperties;
import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.domain.session.AgentSessionSnapshot;
import com.sinrotic.rs.agent.service.impl.RedisAgentHotSessionStore;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.ListOperations;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class RedisAgentHotSessionStoreTest {

    @Test
    void appendsNamespacedEventAndRefreshesConfiguredTtl() {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        ListOperations<String, String> listOperations = mock(ListOperations.class);
        ValueOperations<String, String> valueOperations = mock(ValueOperations.class);
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        AgentSessionStoreProperties properties = properties();

        new RedisAgentHotSessionStore(redisTemplate, new ObjectMapper().findAndRegisterModules(), properties)
                .append(event("event-1"));

        verify(listOperations).rightPush(eq("rs:test:session-1:events"), anyString());
        verify(redisTemplate).expire("rs:test:session-1:events", Duration.ofMinutes(10));
    }

    @Test
    void restoresEventsAndLatestSnapshotFromNamespacedKeys() throws Exception {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        ListOperations<String, String> listOperations = mock(ListOperations.class);
        ValueOperations<String, String> valueOperations = mock(ValueOperations.class);
        ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();
        AgentSessionEvent event = event("event-1");
        AgentSessionSnapshot snapshot = new AgentSessionSnapshot(
                "snapshot-1", "session-1", "compact-1", "event-1", 1, 2,
                Map.of("summary", "short"), Instant.parse("2026-08-08T00:00:00Z")
        );
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(listOperations.range("rs:test:session-1:events", 0, -1))
                .thenReturn(List.of(objectMapper.writeValueAsString(event)));
        when(valueOperations.get("rs:test:session-1:snapshot"))
                .thenReturn(objectMapper.writeValueAsString(snapshot));

        RedisAgentHotSessionStore store = new RedisAgentHotSessionStore(redisTemplate, objectMapper, properties());

        assertThat(store.events("session-1")).containsExactly(event);
        assertThat(store.latestSnapshot("session-1")).contains(snapshot);
    }

    @Test
    void replacesEventsWithoutWritingAListForAnEmptyReplacement() {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        ListOperations<String, String> listOperations = mock(ListOperations.class);
        when(redisTemplate.opsForList()).thenReturn(listOperations);

        new RedisAgentHotSessionStore(redisTemplate, new ObjectMapper().findAndRegisterModules(), properties())
                .replaceEvents("session-1", List.of());

        verify(redisTemplate).delete("rs:test:session-1:events");
        verify(listOperations, org.mockito.Mockito.never()).rightPushAll(eq("rs:test:session-1:events"), org.mockito.ArgumentMatchers.<String>anyList());
    }

    private AgentSessionStoreProperties properties() {
        AgentSessionStoreProperties properties = new AgentSessionStoreProperties();
        properties.setKeyPrefix("rs:test:");
        properties.setTtl(Duration.ofMinutes(10));
        return properties;
    }

    private AgentSessionEvent event(String eventId) {
        return new AgentSessionEvent(
                eventId, "session-1", "request-1", "turn_completed", 0, "", Map.of("text", "hello"), "", "",
                Instant.parse("2026-08-08T00:00:00Z")
        );
    }
}
