package com.sinrotic.rs.agent.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

class JacksonConfigTest {

    @Test
    void providesObjectMapperForPersistentSessionBeans() throws Exception {
        ObjectMapper objectMapper = new JacksonConfig().objectMapper();

        assertEquals("{\"session_id\":\"s1\"}", objectMapper.writeValueAsString(Map.of("session_id", "s1")));
        assertEquals(
                "{\"occurred_at\":\"2026-09-02T14:24:00Z\"}",
                objectMapper.writeValueAsString(Map.of("occurred_at", Instant.parse("2026-09-02T14:24:00Z")))
        );
    }
}
