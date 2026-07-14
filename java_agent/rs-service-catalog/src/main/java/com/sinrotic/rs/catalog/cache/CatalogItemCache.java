package com.sinrotic.rs.catalog.cache;

import com.sinrotic.rs.catalog.domain.entity.CatalogItem;

import java.util.Collection;
import java.util.List;
import java.util.Map;

public interface CatalogItemCache {

    Map<String, CatalogItem> getAll(List<String> itemIds);

    void putAll(Collection<CatalogItem> items);
}
