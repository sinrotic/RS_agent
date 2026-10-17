package com.sinrotic.rs.catalog.cache;

import com.sinrotic.rs.catalog.domain.entity.CatalogItem;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.Collection;

@Component
@ConditionalOnProperty(name = "rs.catalog.local-cache.enabled", havingValue = "false")
public class NoopCatalogLocalCache implements CatalogLocalCache {

    @Override
    public Lookup getAll(Collection<String> itemIds) {
        return Lookup.empty();
    }

    @Override
    public void putAll(Collection<CatalogItem> items) {
    }

    @Override
    public void putMissing(Collection<String> itemIds) {
    }
}
