package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.preference.ItemPreference;
import com.sinrotic.rs.recommend.domain.preference.OnlinePreferenceSnapshot;
import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.service.impl.PreferenceAwareFinalReranker;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PreferenceAwareFinalRerankerTest {

    @Test
    void excludesDislikedItemAndPromotesCandidatesSimilarToLikedItem() {
        var snapshot = new OnlinePreferenceSnapshot(2L, Map.of(
                "bad", preference("evt-dislike", "dislike", "bad", "Shoes", "Other"),
                "liked", preference("evt-like", "like", "liked", "Bags", "Acme")
        ), List.of("evt-dislike", "evt-like"));
        var candidates = List.of(
                item("bad", "Shoes", "Other"),
                item("neutral", "Books", "Reader"),
                item("similar", "Bags", "Acme")
        );

        var ranked = new PreferenceAwareFinalReranker().rerank(candidates, snapshot, 20);

        assertFalse(ranked.stream().anyMatch(candidate -> candidate.item().itemId().equals("bad")));
        assertEquals("similar", ranked.getFirst().item().itemId());
        assertTrue(ranked.getFirst().preferenceAdjustment() > 0);
        assertTrue(ranked.getFirst().reasonTags().contains("preference_like_brand"));
    }

    @Test
    void profileDislikeDownweightsButDoesNotHardExcludeTheOriginalItem() {
        var profileDislike = new ItemPreference(
                "evt-profile", "dislike", "item-1", "Shoes", "Acme", Map.of(),
                1L, Instant.now(), "profile");
        var snapshot = new OnlinePreferenceSnapshot(
                1L, Map.of("item-1", profileDislike), List.of("evt-profile"));

        var ranked = new PreferenceAwareFinalReranker().rerank(
                List.of(item("item-1", "Shoes", "Acme")), snapshot, 20);

        assertEquals(1, ranked.size());
        assertTrue(ranked.getFirst().preferenceAdjustment() < 0);
    }

    @Test
    void reservesExplorationAndCapsOneCategoryOnTheFirstScreenWhenAlternativesExist() {
        var snapshot = new OnlinePreferenceSnapshot(1L, Map.of(
                "liked", preference("evt-like", "like", "liked", "Bags", "Acme")
        ), List.of("evt-like"));
        var candidates = List.of(
                item("bag-1", "Bags", "Acme"),
                item("bag-2", "Bags", "Acme"),
                item("bag-3", "Bags", "Acme"),
                item("bag-4", "Bags", "Acme"),
                item("bag-5", "Bags", "Acme"),
                item("bag-6", "Bags", "Acme"),
                item("bag-7", "Bags", "Acme"),
                item("bag-8", "Bags", "Acme"),
                item("book-1", "Books", "Reader"),
                item("shoe-1", "Shoes", "Runner"),
                item("watch-1", "Watches", "Chronos"),
                item("phone-1", "Phones", "Mobile"),
                item("camera-1", "Cameras", "Photo"),
                item("home-1", "Home", "Living")
        );

        var ranked = new PreferenceAwareFinalReranker().rerank(candidates, snapshot, 10);

        assertEquals(10, ranked.size());
        assertTrue(ranked.stream().filter(candidate -> candidate.preferenceAdjustment() <= 0).count() >= 2);
        assertTrue(ranked.stream().limit(8)
                .filter(candidate -> "Bags".equals(candidate.item().category()))
                .count() <= 4);
    }

    private ItemPreference preference(String eventId, String type, String itemId, String category, String brand) {
        return new ItemPreference(eventId, type, itemId, category, brand, Map.of(), 1L, Instant.now());
    }

    private ItemEmbeddingText item(String id, String category, String brand) {
        return new ItemEmbeddingText(id, id, id, category, category, brand, BigDecimal.TEN, Map.of());
    }
}
