package com.sinrotic.rs.catalog.cache;

import com.sinrotic.rs.catalog.domain.entity.CatalogItem;

import java.util.Collection;
import java.util.Map;
import java.util.Set;

public interface CatalogLocalCache {

    Lookup getAll(Collection<String> itemIds);

    void putAll(Collection<CatalogItem> items);

    void putMissing(Collection<String> itemIds);

    record Lookup(Map<String, CatalogItem> hits, Set<String> knownMissing) {
        public static Lookup empty() {
            return new Lookup(Map.of(), Set.of());
        }
    }
}
