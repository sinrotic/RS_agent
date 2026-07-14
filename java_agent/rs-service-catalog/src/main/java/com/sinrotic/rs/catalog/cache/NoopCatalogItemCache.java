package com.sinrotic.rs.catalog.cache;

import com.sinrotic.rs.catalog.domain.entity.CatalogItem;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.Collection;
import java.util.List;
import java.util.Map;

@Component
@ConditionalOnProperty(name = "rs.catalog.cache.enabled", havingValue = "false", matchIfMissing = true)
public class NoopCatalogItemCache implements CatalogItemCache {

    @Override
    public Map<String, CatalogItem> getAll(List<String> itemIds) {
        return Map.of();
    }

    @Override
    public void putAll(Collection<CatalogItem> items) {
    }
}
