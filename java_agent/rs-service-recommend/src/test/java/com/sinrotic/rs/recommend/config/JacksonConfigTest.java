package com.sinrotic.rs.recommend.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

class JacksonConfigTest {

    @Test
    void roundTripsOnlinePreferenceTimestamps() throws Exception {
        var mapper = new JacksonConfig().objectMapper();
        var preference = new com.sinrotic.rs.recommend.domain.preference.ItemPreference(
                "event-1", "like", "item-1", "bags", "brand", Map.of(), 1,
                java.time.Instant.parse("2026-09-05T00:00:00Z"), "profile");
        var snapshot = new com.sinrotic.rs.recommend.domain.preference.OnlinePreferenceSnapshot(
                1, Map.of("item-1", preference), java.util.List.of("event-1"));
        assertEquals(snapshot, mapper.readValue(mapper.writeValueAsString(snapshot),
                com.sinrotic.rs.recommend.domain.preference.OnlinePreferenceSnapshot.class));
    }

    @Test
    void providesObjectMapperForRecommendBeans() throws Exception {
        ObjectMapper objectMapper = new JacksonConfig().objectMapper();

        assertEquals("{\"material\":\"paper\"}", objectMapper.writeValueAsString(Map.of("material", "paper")));
    }
}
