package com.sinrotic.rs.catalog.service;

import com.sinrotic.rs.catalog.domain.dto.BatchItemIdsRequestDTO;
import com.sinrotic.rs.catalog.domain.dto.CatalogItemEmbeddingPageRequestDTO;
import com.sinrotic.rs.catalog.domain.entity.CatalogItem;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemCardVO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemEmbeddingTextVO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemTextVO;
import com.sinrotic.rs.catalog.repository.CatalogItemRepository;
import com.sinrotic.rs.catalog.service.impl.DefaultCatalogService;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;

class DefaultCatalogServiceTest {

    @Test
    void listItemCardsKeepsRequestedOrderAndSkipsMissingIds() {
        DefaultCatalogService service = new DefaultCatalogService(new FakeCatalogItemRepository());

        List<CatalogItemCardVO> cards = service.listItemCards(new BatchItemIdsRequestDTO(
                List.of("B002", "", "B001", "UNKNOWN", "B002")
        ));

        assertEquals(3, cards.size());
        assertEquals("B002", cards.get(0).itemId());
        assertEquals("Desk Organizer", cards.get(0).title());
        assertEquals("B001", cards.get(1).itemId());
        assertEquals("Commuter Backpack", cards.get(1).title());
        assertEquals("B002", cards.get(2).itemId());
    }

    @Test
    void listItemTextsBuildsStableRagTextFromCatalogFields() {
        DefaultCatalogService service = new DefaultCatalogService(new FakeCatalogItemRepository());

        List<CatalogItemTextVO> texts = service.listItemTexts(new BatchItemIdsRequestDTO(List.of("B001")));

        assertEquals(1, texts.size());
        assertEquals("B001", texts.getFirst().itemId());
        assertEquals(
                "Title: Commuter Backpack\n"
                        + "Category: Backpacks > Travel\n"
                        + "Brand: Urban Carry\n"
                        + "Store: Urban Carry Store\n"
                        + "Summary: Lightweight backpack for daily commute\n"
                        + "Description: Waterproof nylon backpack with laptop sleeve\n"
                        + "Attributes: color=black, material=nylon",
                texts.getFirst().text()
        );
    }

    @Test
    void listItemEmbeddingTextsBuildsCompactStableTextForVectorIndexing() {
        DefaultCatalogService service = new DefaultCatalogService(new FakeCatalogItemRepository());

        List<CatalogItemEmbeddingTextVO> texts = service.listItemEmbeddingTexts(new BatchItemIdsRequestDTO(List.of("B003")));

        assertEquals(1, texts.size());
        assertEquals("B003", texts.getFirst().itemId());
        assertEquals(
                "Title: Travel Laptop Backpack\n"
                        + "Category: Backpacks > Business Travel\n"
                        + "Brand: RoadMate\n"
                        + "Attributes: capacity=20L, material=nylon, target_user=commuter\n"
                        + "Summary: Slim backpack for commuting and short business trips\n"
                        + "Description: Water-resistant laptop backpack with padded shoulder straps and organized compartments. This long text keeps going so the embedding builder should keep only the leading product semantics before droppi",
                texts.getFirst().embeddingText()
        );
        assertEquals("Backpacks > Business Travel", texts.getFirst().categoryPath());
        assertEquals("RoadMate", texts.getFirst().brand());
    }

    @Test
    void listActiveItemEmbeddingTextsUsesItemIdCursorForMysqlBatchIndexing() {
        FakeCatalogItemRepository repository = new FakeCatalogItemRepository();
        DefaultCatalogService service = new DefaultCatalogService(repository);

        List<CatalogItemEmbeddingTextVO> texts = service.listActiveItemEmbeddingTexts(
                new CatalogItemEmbeddingPageRequestDTO("B001", 2)
        );

        assertEquals(List.of("B002", "B003"), texts.stream().map(CatalogItemEmbeddingTextVO::itemId).toList());
        assertEquals("B001", repository.lastAfterItemId);
        assertEquals(2, repository.lastLimit);
    }

    private static final class FakeCatalogItemRepository implements CatalogItemRepository {

        private final Map<String, CatalogItem> items = Map.of(
                "B001", new CatalogItem(
                        "B001",
                        "B001",
                        "Commuter Backpack",
                        "Backpacks",
                        "Backpacks > Travel",
                        "Urban Carry",
                        "Urban Carry Store",
                        new BigDecimal("39.99"),
                        "https://example.com/backpack.jpg",
                        "Lightweight backpack for daily commute",
                        "Waterproof nylon backpack with laptop sleeve",
                        Map.of("color", "black", "material", "nylon"),
                        "{}",
                        "active"
                ),
                "B002", new CatalogItem(
                        "B002",
                        "B002",
                        "Desk Organizer",
                        "Workspace",
                        "Workspace > Storage",
                        "Home Box",
                        "Home Box Store",
                        new BigDecimal("18.50"),
                        "https://example.com/organizer.jpg",
                        "Compact organizer for office supplies",
                        "Multi-compartment desktop organizer",
                        Map.of("color", "white"),
                        "{}",
                        "active"
                ),
                "B003", new CatalogItem(
                        "B003",
                        "B003",
                        "Travel Laptop Backpack",
                        "Backpacks",
                        "Backpacks > Business Travel",
                        "RoadMate",
                        "RoadMate Store",
                        new BigDecimal("56.00"),
                        "https://example.com/travel-backpack.jpg",
                        "Slim backpack for commuting and short business trips",
                        "Water-resistant laptop backpack with padded shoulder straps and organized compartments. "
                                + "This long text keeps going so the embedding builder should keep only the leading "
                                + "product semantics before dropping repeated marketing copy. Extra discount message "
                                + "and unrelated campaign wording should not dominate vector generation.",
                        Map.of("target_user", "commuter", "material", "nylon", "capacity", "20L"),
                        "{}",
                        "active"
                )
        );

        private String lastAfterItemId;

        private int lastLimit;

        @Override
        public Optional<CatalogItem> findByItemId(String itemId) {
            return Optional.ofNullable(items.get(itemId));
        }

        @Override
        public List<CatalogItem> findByItemIds(List<String> itemIds) {
            return itemIds.stream()
                    .map(items::get)
                    .filter(item -> item != null)
                    .toList();
        }

        @Override
        public List<CatalogItem> findByCategory(String category, int limit) {
            return List.of();
        }

        @Override
        public List<CatalogItem> findByStoreName(String storeName, int limit) {
            return List.of();
        }

        @Override
        public List<CatalogItem> findActiveAfterItemId(String afterItemId, int limit) {
            lastAfterItemId = afterItemId;
            lastLimit = limit;
            return items.values().stream()
                    .sorted(java.util.Comparator.comparing(CatalogItem::itemId))
                    .filter(item -> afterItemId == null || item.itemId().compareTo(afterItemId) > 0)
                    .limit(limit)
                    .toList();
        }

        @Override
        public List<String> listCategories() {
            return List.of();
        }

        @Override
        public List<String> listStoreNames() {
            return List.of();
        }
    }
}
