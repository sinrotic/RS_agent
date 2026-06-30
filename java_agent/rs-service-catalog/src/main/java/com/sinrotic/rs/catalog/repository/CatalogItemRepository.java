package com.sinrotic.rs.catalog.repository;

import com.sinrotic.rs.catalog.domain.entity.CatalogItem;

import java.util.List;
import java.util.Optional;

public interface CatalogItemRepository {

    Optional<CatalogItem> findByItemId(String itemId);

    List<CatalogItem> findByItemIds(List<String> itemIds);

    List<CatalogItem> findByCategory(String category, int limit);

    List<CatalogItem> findByStoreName(String storeName, int limit);

    List<CatalogItem> findActiveAfterItemId(String afterItemId, int limit);

    List<String> listCategories();

    List<String> listStoreNames();
}
