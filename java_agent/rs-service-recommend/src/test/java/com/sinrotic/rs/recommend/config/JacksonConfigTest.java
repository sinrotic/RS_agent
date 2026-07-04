package com.sinrotic.rs.recommend.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

class JacksonConfigTest {

    @Test
    void providesObjectMapperForRecommendBeans() throws Exception {
        ObjectMapper objectMapper = new JacksonConfig().objectMapper();

        assertEquals("{\"material\":\"paper\"}", objectMapper.writeValueAsString(Map.of("material", "paper")));
    }
}
