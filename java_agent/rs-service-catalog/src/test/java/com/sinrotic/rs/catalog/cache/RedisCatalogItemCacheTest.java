package com.sinrotic.rs.catalog.cache;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.catalog.domain.entity.CatalogItem;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.math.BigDecimal;
import java.time.Duration;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class RedisCatalogItemCacheTest {

    private StringRedisTemplate redisTemplate;
    private ValueOperations<String, String> valueOperations;
    private ObjectMapper objectMapper;
    private RedisCatalogItemCache cache;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        redisTemplate = mock(StringRedisTemplate.class);
        valueOperations = mock(ValueOperations.class);
        objectMapper = new ObjectMapper();
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        cache = new RedisCatalogItemCache(redisTemplate, objectMapper, 3600);
    }

    @Test
    void getAllReturnsPartialHitsFromOneRedisBatch() throws Exception {
        CatalogItem item = item("A1");
        when(valueOperations.multiGet(List.of(
                "rs:catalog:item:v2:A1",
                "rs:catalog:item:v2:A2"
        ))).thenReturn(Arrays.asList(objectMapper.writeValueAsString(item), null));

        Map<String, CatalogItem> result = cache.getAll(List.of("A1", "A2"));

        assertEquals(item, result.get("A1"));
        assertEquals(1, result.size());
    }

    @Test
    void putAllWritesCanonicalJsonWithConfiguredTtl() {
        cache.putAll(List.of(item("A1")));

        verify(valueOperations).set(
                eq("rs:catalog:item:v2:A1"),
                anyString(),
                eq(Duration.ofSeconds(3600))
        );
    }

    @Test
    void malformedJsonIsEvictedAndTreatedAsMiss() {
        String key = "rs:catalog:item:v2:A1";
        when(valueOperations.multiGet(List.of(key))).thenReturn(List.of("not-json"));

        Map<String, CatalogItem> result = cache.getAll(List.of("A1"));

        assertTrue(result.isEmpty());
        verify(redisTemplate).delete(key);
    }

    @Test
    void redisFailureIsContainedAsCacheMiss() {
        when(valueOperations.multiGet(List.of("rs:catalog:item:v2:A1")))
                .thenThrow(new IllegalStateException("redis down"));

        assertTrue(cache.getAll(List.of("A1")).isEmpty());
    }

    private CatalogItem item(String itemId) {
        return new CatalogItem(
                itemId,
                itemId,
                "Desk Organizer",
                "Office",
                "Office > Storage",
                "Home Box",
                "Home Box Store",
                new BigDecimal("18.50"),
                "https://example.com/item.jpg",
                "Compact organizer",
                "Multi-compartment organizer",
                Map.of("Color", "White"),
                "{}",
                "active"
        );
    }
}
