package com.sinrotic.rs.catalog.service;

import com.sinrotic.rs.catalog.domain.dto.BatchItemIdsRequestDTO;
import com.sinrotic.rs.catalog.domain.entity.CatalogItem;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemCardVO;
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
                )
        );

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
        public List<String> listCategories() {
            return List.of();
        }

        @Override
        public List<String> listStoreNames() {
            return List.of();
        }
    }
}
