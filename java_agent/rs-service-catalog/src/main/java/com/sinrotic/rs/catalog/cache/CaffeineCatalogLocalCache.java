package com.sinrotic.rs.catalog.cache;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.sinrotic.rs.catalog.domain.entity.CatalogItem;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

@Component
@ConditionalOnProperty(name = "rs.catalog.local-cache.enabled", havingValue = "true", matchIfMissing = true)
public class CaffeineCatalogLocalCache implements CatalogLocalCache {

    private final Cache<String, CatalogItem> items;
    private final Cache<String, Boolean> missingItems;

    public CaffeineCatalogLocalCache(
            @Value("${rs.catalog.local-cache.max-items:10000}") long maxItems,
            @Value("${rs.catalog.local-cache.item-ttl-seconds:300}") long itemTtlSeconds,
            @Value("${rs.catalog.local-cache.negative-ttl-seconds:30}") long negativeTtlSeconds
    ) {
        items = Caffeine.newBuilder()
                .maximumSize(Math.max(1, maxItems))
                .expireAfterWrite(Duration.ofSeconds(Math.max(1, itemTtlSeconds)))
                .recordStats()
                .build();
        missingItems = Caffeine.newBuilder()
                .maximumSize(Math.max(1, maxItems / 10))
                .expireAfterWrite(Duration.ofSeconds(Math.max(1, negativeTtlSeconds)))
                .build();
    }

    @Override
    public Lookup getAll(Collection<String> itemIds) {
        if (itemIds == null || itemIds.isEmpty()) {
            return Lookup.empty();
        }
        Map<String, CatalogItem> hits = new LinkedHashMap<>();
        Set<String> knownMissing = new LinkedHashSet<>();
        for (String itemId : itemIds) {
            CatalogItem item = items.getIfPresent(itemId);
            if (item != null) {
                hits.put(itemId, item);
            } else if (Boolean.TRUE.equals(missingItems.getIfPresent(itemId))) {
                knownMissing.add(itemId);
            }
        }
        return new Lookup(Map.copyOf(hits), Set.copyOf(knownMissing));
    }

    @Override
    public void putAll(Collection<CatalogItem> values) {
        if (values == null) {
            return;
        }
        for (CatalogItem item : values) {
            if (item == null || item.itemId() == null || item.itemId().isBlank()) {
                continue;
            }
            items.put(item.itemId(), item);
            missingItems.invalidate(item.itemId());
        }
    }

    @Override
    public void putMissing(Collection<String> itemIds) {
        if (itemIds == null) {
            return;
        }
        for (String itemId : itemIds) {
            if (itemId != null && !itemId.isBlank() && items.getIfPresent(itemId) == null) {
                missingItems.put(itemId, Boolean.TRUE);
            }
        }
    }
}
