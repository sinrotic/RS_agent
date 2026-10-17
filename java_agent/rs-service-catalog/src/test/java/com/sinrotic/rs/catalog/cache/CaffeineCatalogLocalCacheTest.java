package com.sinrotic.rs.catalog.cache;

import com.sinrotic.rs.catalog.domain.entity.CatalogItem;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class CaffeineCatalogLocalCacheTest {

    @Test
    void storesPositiveAndNegativeEntriesSeparately() {
        CaffeineCatalogLocalCache cache = new CaffeineCatalogLocalCache(100, 300, 30);
        cache.putAll(List.of(item("A1")));
        cache.putMissing(List.of("A2", "A1"));

        CatalogLocalCache.Lookup lookup = cache.getAll(List.of("A1", "A2", "A3"));

        assertEquals("A1", lookup.hits().get("A1").itemId());
        assertEquals(java.util.Set.of("A2"), lookup.knownMissing());
    }

    @Test
    void laterPositiveValueClearsNegativeEntry() {
        CaffeineCatalogLocalCache cache = new CaffeineCatalogLocalCache(100, 300, 30);
        cache.putMissing(List.of("A1"));
        cache.putAll(List.of(item("A1")));

        CatalogLocalCache.Lookup lookup = cache.getAll(List.of("A1"));

        assertTrue(lookup.knownMissing().isEmpty());
        assertEquals("A1", lookup.hits().get("A1").itemId());
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
                null,
                null,
                null,
                Map.of(),
                "{}",
                "active"
        );
    }
}
