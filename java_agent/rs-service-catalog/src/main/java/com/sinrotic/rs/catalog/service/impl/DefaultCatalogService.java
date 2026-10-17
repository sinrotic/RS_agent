package com.sinrotic.rs.catalog.service.impl;

import com.sinrotic.rs.catalog.cache.CatalogItemCache;
import com.sinrotic.rs.catalog.cache.CatalogLocalCache;
import com.sinrotic.rs.catalog.cache.NoopCatalogLocalCache;
import com.sinrotic.rs.catalog.domain.dto.BatchItemIdsRequestDTO;
import com.sinrotic.rs.catalog.domain.dto.CatalogItemEmbeddingPageRequestDTO;
import com.sinrotic.rs.catalog.domain.dto.CatalogItemPageRequestDTO;
import com.sinrotic.rs.catalog.domain.entity.CatalogItem;
import com.sinrotic.rs.catalog.domain.vo.CatalogCategoryVO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemCardVO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemDetailVO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemEmbeddingTextVO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemTextVO;
import com.sinrotic.rs.catalog.domain.vo.VirtualStoreVO;
import com.sinrotic.rs.catalog.repository.CatalogItemRepository;
import com.sinrotic.rs.catalog.service.CatalogService;
import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Autowired;

import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import java.util.concurrent.locks.ReentrantLock;

@Service
public class DefaultCatalogService implements CatalogService {

    private static final int EMBEDDING_DESCRIPTION_MAX_CHARS = 200;

    private final CatalogItemRepository catalogItemRepository;
    private final CatalogItemCache catalogItemCache;
    private final CatalogLocalCache catalogLocalCache;
    private final ReentrantLock[] loadLocks = createLoadLocks(256);
    private volatile List<String> discoveryCategories = List.of();
    private volatile long discoveryCategoriesExpireAt;

    @Override
    public List<CatalogItemEmbeddingTextVO> discoverEmbeddingTexts(String seed, int limit) {
        int boundedLimit = Math.max(1, Math.min(120, limit));
        List<String> categories = new java.util.ArrayList<>(cachedDiscoveryCategories());
        java.util.Random random = new java.util.Random((seed == null ? "" : seed).hashCode());
        java.util.Collections.shuffle(categories, random);
        int count = Math.min(8, categories.size());
        if (count == 0) return List.of();
        int perCategory = (boundedLimit + count - 1) / count;
        List<List<CatalogItem>> groups = new java.util.ArrayList<>();
        for (String category : categories.subList(0, count)) {
            var items = catalogItemRepository.findDiscoveryItems(category, random.nextInt(1024), perCategory);
            if (items.size() < perCategory) {
                var combined = new LinkedHashMap<String, CatalogItem>();
                items.forEach(item -> combined.put(item.itemId(), item));
                catalogItemRepository.findByCategory(category, perCategory).forEach(item -> combined.putIfAbsent(item.itemId(), item));
                items = combined.values().stream().limit(perCategory).toList();
            }
            groups.add(items);
        }
        var result = new LinkedHashMap<String, CatalogItemEmbeddingTextVO>();
        for (int position = 0; position < perCategory; position++) {
            for (var group : groups) if (position < group.size()) {
                var item = group.get(position);
                result.putIfAbsent(item.itemId(), toEmbeddingText(item));
            }
        }
        return result.values().stream().limit(boundedLimit).toList();
    }

    private synchronized List<String> cachedDiscoveryCategories() {
        if (System.currentTimeMillis() >= discoveryCategoriesExpireAt) {
            discoveryCategories = List.copyOf(catalogItemRepository.listCategories());
            discoveryCategoriesExpireAt = System.currentTimeMillis() + 3_600_000;
        }
        return discoveryCategories;
    }

    @Override
    public List<CatalogItemEmbeddingTextVO> categoryEmbeddingTexts(String category, String seed, int limit) {
        if (category == null || category.isBlank()) return List.of();
        int bounded = Math.max(1, Math.min(64, limit));
        var candidates = new LinkedHashMap<String, CatalogItem>();
        catalogItemRepository.findDiscoveryItems(category, Math.floorMod(java.util.Objects.hashCode(seed), 1024), bounded)
                .forEach(item -> candidates.put(item.itemId(), item));
        if (candidates.size() < bounded) catalogItemRepository.findByCategory(category, bounded)
                .forEach(item -> candidates.putIfAbsent(item.itemId(), item));
        return candidates.values().stream().limit(bounded).map(this::toEmbeddingText).toList();
    }


    @Autowired
    public DefaultCatalogService(
            CatalogItemRepository catalogItemRepository,
            CatalogItemCache catalogItemCache,
            CatalogLocalCache catalogLocalCache
    ) {
        this.catalogItemRepository = catalogItemRepository;
        this.catalogItemCache = catalogItemCache;
        this.catalogLocalCache = catalogLocalCache;
    }

    public DefaultCatalogService(CatalogItemRepository catalogItemRepository, CatalogItemCache catalogItemCache) {
        this(catalogItemRepository, catalogItemCache, new NoopCatalogLocalCache());
    }

    @Override
    public CatalogItemDetailVO getItemDetail(String itemId) {
        if (itemId == null || itemId.isBlank()) {
            return null;
        }
        return orderedItems(List.of(itemId.trim())).stream()
                .findFirst()
                .map(this::toDetail)
                .orElse(null);
    }

    @Override
    public List<CatalogItemCardVO> listItemCards(BatchItemIdsRequestDTO request) {
        return orderedItems(request.normalizedItemIds()).stream()
                .map(this::toCard)
                .toList();
    }

    @Override
    public List<CatalogItemDetailVO> listItemDetails(BatchItemIdsRequestDTO request) {
        return orderedItems(request.normalizedItemIds()).stream()
                .map(this::toDetail)
                .toList();
    }

    @Override
    public List<CatalogItemTextVO> listItemTexts(BatchItemIdsRequestDTO request) {
        return orderedItems(request.normalizedItemIds()).stream()
                .map(item -> new CatalogItemTextVO(item.itemId(), buildRagText(item)))
                .toList();
    }

    @Override
    public List<CatalogItemEmbeddingTextVO> listItemEmbeddingTexts(BatchItemIdsRequestDTO request) {
        return orderedItems(request.normalizedItemIds()).stream()
                .map(this::toEmbeddingText)
                .toList();
    }

    @Override
    public List<CatalogItemEmbeddingTextVO> listActiveItemEmbeddingTexts(CatalogItemEmbeddingPageRequestDTO request) {
        CatalogItemEmbeddingPageRequestDTO normalized = request.withDefaults();
        return catalogItemRepository.findActiveAfterItemId(normalized.afterItemId(), normalized.limit()).stream()
                .map(this::toEmbeddingText)
                .toList();
    }

    @Override
    public List<CatalogItemCardVO> listItemsByCategory(CatalogItemPageRequestDTO request) {
        return catalogItemRepository.findByCategory(request.normalizedKey(), request.normalizedLimit()).stream()
                .map(this::toCard)
                .toList();
    }

    @Override
    public List<CatalogItemCardVO> listItemsByStore(CatalogItemPageRequestDTO request) {
        return catalogItemRepository.findByStoreName(request.normalizedKey(), request.normalizedLimit()).stream()
                .map(this::toCard)
                .toList();
    }

    @Override
    public List<CatalogCategoryVO> listCategories() {
        return catalogItemRepository.listCategories().stream()
                .map(category -> new CatalogCategoryVO(category, category))
                .toList();
    }

    @Override
    public List<VirtualStoreVO> listStores() {
        return catalogItemRepository.listStoreNames().stream()
                .map(storeName -> new VirtualStoreVO(storeName, storeName))
                .toList();
    }

    private List<CatalogItem> orderedItems(List<String> itemIds) {
        if (itemIds.isEmpty()) {
            return List.of();
        }
        List<String> distinctItemIds = new LinkedHashSet<>(itemIds).stream().toList();
        Map<String, CatalogItem> itemById = new LinkedHashMap<>();
        CatalogLocalCache.Lookup localLookup = catalogLocalCache.getAll(distinctItemIds);
        addActiveItems(itemById, localLookup.hits());
        List<String> l2Candidates = distinctItemIds.stream()
                .filter(itemId -> !itemById.containsKey(itemId))
                .filter(itemId -> !localLookup.knownMissing().contains(itemId))
                .toList();
        Map<String, CatalogItem> l2Hits = safeCacheGet(l2Candidates);
        addActiveItems(itemById, l2Hits);
        catalogLocalCache.putAll(l2Hits.values());
        List<String> missingItemIds = l2Candidates.stream()
                .filter(itemId -> !itemById.containsKey(itemId))
                .toList();
        if (!missingItemIds.isEmpty()) {
            loadMissingItems(missingItemIds, itemById);
        }
        return itemIds.stream()
                .map(itemById::get)
                .filter(item -> item != null)
                .toList();
    }

    private void loadMissingItems(List<String> itemIds, Map<String, CatalogItem> itemById) {
        List<ReentrantLock> locks = itemIds.stream()
                .map(this::loadLockIndex)
                .distinct()
                .sorted()
                .map(index -> loadLocks[index])
                .toList();
        locks.forEach(ReentrantLock::lock);
        try {
            CatalogLocalCache.Lookup localLookup = catalogLocalCache.getAll(itemIds);
            addActiveItems(itemById, localLookup.hits());
            List<String> l2Candidates = itemIds.stream()
                    .filter(itemId -> !itemById.containsKey(itemId))
                    .filter(itemId -> !localLookup.knownMissing().contains(itemId))
                    .toList();
            Map<String, CatalogItem> l2Hits = safeCacheGet(l2Candidates);
            addActiveItems(itemById, l2Hits);
            catalogLocalCache.putAll(l2Hits.values());
            List<String> databaseCandidates = l2Candidates.stream()
                    .filter(itemId -> !itemById.containsKey(itemId))
                    .toList();
            if (databaseCandidates.isEmpty()) {
                return;
            }
            List<CatalogItem> loadedItems = catalogItemRepository.findByItemIds(databaseCandidates);
            loadedItems.forEach(item -> itemById.putIfAbsent(item.itemId(), item));
            safeCachePut(loadedItems);
            catalogLocalCache.putAll(loadedItems);
            Set<String> loadedIds = loadedItems.stream().map(CatalogItem::itemId).collect(Collectors.toSet());
            catalogLocalCache.putMissing(databaseCandidates.stream()
                    .filter(itemId -> !loadedIds.contains(itemId))
                    .toList());
        } finally {
            for (int index = locks.size() - 1; index >= 0; index--) {
                locks.get(index).unlock();
            }
        }
    }

    private void addActiveItems(Map<String, CatalogItem> destination, Map<String, CatalogItem> candidates) {
        candidates.forEach((itemId, item) -> {
            if (itemId != null && item != null && "active".equals(item.status())) {
                destination.put(itemId, item);
            }
        });
    }

    private int loadLockIndex(String itemId) {
        return Math.floorMod(itemId.hashCode(), loadLocks.length);
    }

    private static ReentrantLock[] createLoadLocks(int count) {
        ReentrantLock[] locks = new ReentrantLock[count];
        for (int index = 0; index < count; index++) {
            locks[index] = new ReentrantLock();
        }
        return locks;
    }

    private Map<String, CatalogItem> safeCacheGet(List<String> itemIds) {
        try {
            Map<String, CatalogItem> cachedItems = catalogItemCache.getAll(itemIds);
            return cachedItems == null ? Map.of() : cachedItems;
        } catch (RuntimeException ignored) {
            return Map.of();
        }
    }

    private void safeCachePut(List<CatalogItem> items) {
        try {
            catalogItemCache.putAll(items);
        } catch (RuntimeException ignored) {
        }
    }

    private CatalogItemCardVO toCard(CatalogItem item) {
        return new CatalogItemCardVO(
                item.itemId(),
                item.title(),
                item.category(),
                item.brand(),
                item.storeName(),
                item.price(),
                item.imageUrl(),
                item.summary()
        );
    }

    private CatalogItemDetailVO toDetail(CatalogItem item) {
        return new CatalogItemDetailVO(
                item.itemId(),
                item.sourceItemId(),
                item.title(),
                item.category(),
                item.categoryPath(),
                item.brand(),
                item.storeName(),
                item.price(),
                item.imageUrl(),
                item.summary(),
                item.description(),
                item.attributes()
        );
    }

    private CatalogItemEmbeddingTextVO toEmbeddingText(CatalogItem item) {
        return new CatalogItemEmbeddingTextVO(
                item.itemId(),
                buildEmbeddingText(item),
                item.title(),
                item.category(),
                firstNonBlank(item.categoryPath(), item.category()),
                item.brand(),
                item.price(),
                item.attributes()
        );
    }

    private String buildRagText(CatalogItem item) {
        StringBuilder text = new StringBuilder();
        appendLine(text, "Title", item.title());
        appendLine(text, "Category", firstNonBlank(item.categoryPath(), item.category()));
        appendLine(text, "Brand", item.brand());
        appendLine(text, "Store", item.storeName());
        appendLine(text, "Summary", item.summary());
        appendLine(text, "Description", item.description());
        String attributes = item.attributes().entrySet().stream()
                .sorted(Comparator.comparing(Map.Entry::getKey))
                .map(entry -> entry.getKey() + "=" + entry.getValue())
                .collect(Collectors.joining(", "));
        appendLine(text, "Attributes", attributes);
        return text.toString().stripTrailing();
    }

    private String buildEmbeddingText(CatalogItem item) {
        StringBuilder text = new StringBuilder();
        appendLine(text, "Title", item.title());
        appendLine(text, "Category", firstNonBlank(item.categoryPath(), item.category()));
        appendLine(text, "Brand", item.brand());
        appendLine(text, "Attributes", embeddingAttributes(item.attributes()));
        appendLine(text, "Summary", item.summary());
        appendLine(text, "Description", truncate(item.description(), EMBEDDING_DESCRIPTION_MAX_CHARS));
        return text.toString().stripTrailing();
    }

    private String embeddingAttributes(Map<String, String> attributes) {
        if (attributes == null || attributes.isEmpty()) {
            return "";
        }
        return attributes.entrySet().stream()
                .filter(entry -> entry.getKey() != null && !entry.getKey().isBlank())
                .filter(entry -> entry.getValue() != null && !entry.getValue().isBlank())
                .sorted(Comparator.comparing(Map.Entry::getKey))
                .map(entry -> entry.getKey().trim() + "=" + entry.getValue().trim())
                .collect(Collectors.joining(", "));
    }

    private String truncate(String value, int maxChars) {
        if (value == null || value.isBlank()) {
            return "";
        }
        String trimmed = value.trim();
        if (trimmed.length() <= maxChars) {
            return trimmed;
        }
        return trimmed.substring(0, maxChars).stripTrailing();
    }

    private void appendLine(StringBuilder text, String label, String value) {
        if (value == null || value.isBlank()) {
            return;
        }
        if (!text.isEmpty()) {
            text.append('\n');
        }
        text.append(label).append(": ").append(value.trim());
    }

    private String firstNonBlank(String primary, String fallback) {
        if (primary != null && !primary.isBlank()) {
            return primary;
        }
        return fallback;
    }
}
