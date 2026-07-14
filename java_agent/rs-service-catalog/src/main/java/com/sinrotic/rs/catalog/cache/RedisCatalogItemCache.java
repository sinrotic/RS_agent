package com.sinrotic.rs.catalog.cache;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.catalog.domain.entity.CatalogItem;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;

@Component
@ConditionalOnProperty(name = "rs.catalog.cache.enabled", havingValue = "true")
public class RedisCatalogItemCache implements CatalogItemCache {

    private static final Logger log = LoggerFactory.getLogger(RedisCatalogItemCache.class);
    private static final String KEY_PREFIX = "rs:catalog:item:v1:";

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final Duration itemTtl;

    public RedisCatalogItemCache(
            StringRedisTemplate redisTemplate,
            ObjectMapper objectMapper,
            @Value("${rs.catalog.cache.item-ttl-seconds:86400}") long itemTtlSeconds
    ) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.itemTtl = Duration.ofSeconds(Math.max(1, itemTtlSeconds));
    }

    @Override
    public Map<String, CatalogItem> getAll(List<String> itemIds) {
        List<String> normalizedIds = normalizeIds(itemIds);
        if (normalizedIds.isEmpty()) {
            return Map.of();
        }
        List<String> keys = normalizedIds.stream().map(this::key).toList();
        try {
            List<String> values = redisTemplate.opsForValue().multiGet(keys);
            if (values == null || values.isEmpty()) {
                return Map.of();
            }
            Map<String, CatalogItem> hits = new LinkedHashMap<>();
            for (int index = 0; index < Math.min(normalizedIds.size(), values.size()); index++) {
                String value = values.get(index);
                if (value == null || value.isBlank()) {
                    continue;
                }
                String itemId = normalizedIds.get(index);
                try {
                    CatalogItem item = objectMapper.readValue(value, CatalogItem.class);
                    if (itemId.equals(item.itemId())) {
                        hits.put(itemId, item);
                    } else {
                        evictQuietly(key(itemId));
                    }
                } catch (JsonProcessingException malformedValue) {
                    evictQuietly(key(itemId));
                }
            }
            return Collections.unmodifiableMap(hits);
        } catch (RuntimeException redisFailure) {
            log.warn("Catalog Redis read failed; falling back to MySQL: {}", redisFailure.getMessage());
            return Map.of();
        }
    }

    @Override
    public void putAll(Collection<CatalogItem> items) {
        if (items == null || items.isEmpty()) {
            return;
        }
        for (CatalogItem item : items) {
            if (item == null || item.itemId() == null || item.itemId().isBlank()) {
                continue;
            }
            try {
                redisTemplate.opsForValue().set(
                        key(item.itemId()),
                        objectMapper.writeValueAsString(item),
                        itemTtl
                );
            } catch (JsonProcessingException | RuntimeException cacheFailure) {
                log.warn("Catalog Redis write failed for item {}: {}", item.itemId(), cacheFailure.getMessage());
            }
        }
    }

    private List<String> normalizeIds(List<String> itemIds) {
        if (itemIds == null || itemIds.isEmpty()) {
            return List.of();
        }
        LinkedHashSet<String> uniqueIds = new LinkedHashSet<>();
        for (String itemId : itemIds) {
            if (itemId != null && !itemId.isBlank()) {
                uniqueIds.add(itemId.trim());
            }
        }
        return new ArrayList<>(uniqueIds);
    }

    private String key(String itemId) {
        return KEY_PREFIX + itemId;
    }

    private void evictQuietly(String key) {
        try {
            redisTemplate.delete(key);
        } catch (RuntimeException ignored) {
        }
    }
}
