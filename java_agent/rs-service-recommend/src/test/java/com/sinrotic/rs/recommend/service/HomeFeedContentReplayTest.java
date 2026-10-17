package com.sinrotic.rs.recommend.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.domain.delivery.*;
import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRequestDTO;
import com.sinrotic.rs.recommend.domain.preference.OnlinePreferenceSnapshot;
import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.service.impl.*;
import org.junit.jupiter.api.Test;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;
import static org.junit.jupiter.api.Assertions.*;

class HomeFeedContentReplayTest {
    @Test void actualBackpackVariantsDoNotCountAsANewBatch() throws Exception {
        var result = replay(false, new AtomicReference<>());
        assertEquals(6, result.items().size());
        var ids = result.items().stream().map(c -> c.item().itemId()).toList();
        assertFalse(ids.contains("B07GKYW9C3"), "CoolBELL 同型号换色不能作为换批新商品");
        assertFalse(ids.contains("B07TNNVCJL"), "LOKASS 同款换尺寸不能作为换批新商品");
        assertTrue(result.items().stream().filter(c -> c.reasonTags().contains("catalog_exploration")).count() >= 3);
    }

    @Test void nextBatchRanksAgainstOtherHistoricalInterest() throws Exception {
        var query = new AtomicReference<String>();
        replay(true, query);
        assertTrue(query.get().contains("Ink Cartridge"), "上一批全是背包，换批应使用画像中另一种真实兴趣");
    }

    private PersonalizedHomeCandidatePipeline.Selection replay(boolean secondInterest, AtomicReference<String> query) throws Exception {
        var mapper = new ObjectMapper();
        var fixture = mapper.readTree(getClass().getResourceAsStream("/fixtures/home-backpack-variants.json"));
        var previous = Arrays.asList(mapper.treeToValue(fixture.get("previous"), ItemEmbeddingText[].class));
        var candidates = Arrays.asList(mapper.treeToValue(fixture.get("candidates"), ItemEmbeddingText[].class));
        var titles = List.of("Printer Ink Cartridge Epson Compatible", "Ceramic Coffee Mug", "Digital Alarm Clock",
                "Wooden Book Shelf", "Yoga Exercise Mat", "Stainless Steel Cooking Pan");
        var exploration = java.util.stream.IntStream.range(0, titles.size()).mapToObj(i -> new ItemEmbeddingText("explore-" + i,
                titles.get(i), titles.get(i), "category-" + i, "category-" + i, "brand-" + i, BigDecimal.TEN, Map.of())).toList();
        var items = new HashMap<String, ItemEmbeddingText>();
        previous.forEach(item -> items.put(item.itemId(), item));
        candidates.forEach(item -> items.put(item.itemId(), item));
        exploration.forEach(item -> items.put(item.itemId(), item));
        var catalog = new CatalogEmbeddingTextClient() {
            public List<ItemEmbeddingText> fetchActiveItemEmbeddingTexts(String cursor, int limit) { return exploration; }
            public List<ItemEmbeddingText> fetchItemEmbeddingTexts(List<String> ids) { return ids.stream().map(items::get).filter(Objects::nonNull).toList(); }
        };
        var identity = new RecommendationIdentity("test", "test-profile", "test-session");
        var store = new InMemoryRecommendationDeliveryStore();
        store.save(new RecommendationDelivery("previous", identity, "home", 0, previous.stream().map(item ->
                new RecommendationDeliveryItem(item.itemId(), 1, .99, item.category(), item.brand(), item.attributes())).toList(),
                Instant.now().minusSeconds(30), Instant.now().plusSeconds(3600)));
        var pipeline = new PersonalizedHomeCandidatePipeline(catalog,
                (profile, limit) -> secondInterest ? List.of(previous.getFirst().itemId(), "explore-0") : List.of(previous.getFirst().itemId()),
                (id, text, limit) -> candidates, (id, text, ranked) -> {
                    query.set(text);
                    return ranked.stream().collect(java.util.stream.Collectors.toMap(ItemEmbeddingText::itemId,
                            item -> item.itemId().startsWith("explore-") ? .01 : .99));
                }, store, new PreferenceAwareFinalReranker());
        return pipeline.select("next", identity, new HomeRecommendRequestDTO("test-session", "home", 6, "feed:previous", false), OnlinePreferenceSnapshot.empty());
    }
}
