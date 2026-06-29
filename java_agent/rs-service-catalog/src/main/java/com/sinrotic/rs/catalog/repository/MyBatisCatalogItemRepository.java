package com.sinrotic.rs.catalog.repository;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.catalog.domain.entity.CatalogItem;
import com.sinrotic.rs.catalog.mapper.CatalogItemMapper;
import com.sinrotic.rs.catalog.mapper.CatalogItemRow;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Map;
import java.util.Optional;

@Repository
public class MyBatisCatalogItemRepository implements CatalogItemRepository {

    private static final TypeReference<Map<String, String>> STRING_MAP_TYPE = new TypeReference<>() {
    };

    private final CatalogItemMapper catalogItemMapper;
    private final ObjectMapper objectMapper;

    public MyBatisCatalogItemRepository(CatalogItemMapper catalogItemMapper, ObjectMapper objectMapper) {
        this.catalogItemMapper = catalogItemMapper;
        this.objectMapper = objectMapper;
    }

    @Override
    public Optional<CatalogItem> findByItemId(String itemId) {
        return Optional.ofNullable(catalogItemMapper.selectByItemId(itemId))
                .map(this::toEntity);
    }

    @Override
    public List<CatalogItem> findByItemIds(List<String> itemIds) {
        if (itemIds.isEmpty()) {
            return List.of();
        }
        return catalogItemMapper.selectByItemIds(itemIds).stream()
                .map(this::toEntity)
                .toList();
    }

    @Override
    public List<CatalogItem> findByCategory(String category, int limit) {
        return catalogItemMapper.selectByCategory(category, limit).stream()
                .map(this::toEntity)
                .toList();
    }

    @Override
    public List<CatalogItem> findByStoreName(String storeName, int limit) {
        return catalogItemMapper.selectByStoreName(storeName, limit).stream()
                .map(this::toEntity)
                .toList();
    }

    @Override
    public List<String> listCategories() {
        return catalogItemMapper.selectCategories();
    }

    @Override
    public List<String> listStoreNames() {
        return catalogItemMapper.selectStoreNames();
    }

    private CatalogItem toEntity(CatalogItemRow row) {
        return new CatalogItem(
                row.itemId(),
                row.sourceItemId(),
                row.title(),
                row.category(),
                row.categoryPath(),
                row.brand(),
                row.storeName(),
                row.price(),
                row.imageUrl(),
                row.summary(),
                row.description(),
                parseAttributes(row.attributesJson()),
                row.rawMetadataJson(),
                row.status()
        );
    }

    private Map<String, String> parseAttributes(String attributesJson) {
        if (attributesJson == null || attributesJson.isBlank()) {
            return Map.of();
        }
        try {
            return objectMapper.readValue(attributesJson, STRING_MAP_TYPE);
        } catch (Exception ignored) {
            return Map.of();
        }
    }
}
