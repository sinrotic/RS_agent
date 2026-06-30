package com.sinrotic.rs.catalog.service.impl;

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

import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

@Service
public class DefaultCatalogService implements CatalogService {

    private static final int EMBEDDING_DESCRIPTION_MAX_CHARS = 200;

    private final CatalogItemRepository catalogItemRepository;

    public DefaultCatalogService(CatalogItemRepository catalogItemRepository) {
        this.catalogItemRepository = catalogItemRepository;
    }

    @Override
    public CatalogItemDetailVO getItemDetail(String itemId) {
        return catalogItemRepository.findByItemId(itemId)
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
        Map<String, CatalogItem> itemById = catalogItemRepository.findByItemIds(itemIds).stream()
                .collect(Collectors.toMap(
                        CatalogItem::itemId,
                        Function.identity(),
                        (left, ignored) -> left,
                        LinkedHashMap::new
                ));
        return itemIds.stream()
                .map(itemById::get)
                .filter(item -> item != null)
                .toList();
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
