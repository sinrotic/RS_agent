package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.preference.PreferenceRankedCandidate;
import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Objects;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HomeFeedDiversityTest {
    private final HomeFeedDiversity policy = new HomeFeedDiversity();

    @Test
    void replaysExactOrderingCapturedBeforeFeatureReuse() throws Exception {
        try (var reader = new BufferedReader(new InputStreamReader(Objects.requireNonNull(
                getClass().getResourceAsStream("/home-diversity-before-20261010.csv")), StandardCharsets.US_ASCII))) {
            var expected = reader.lines().toList();
            var cases = DiversityReplayCases.cases();
            assertEquals(cases.size(), expected.size());
            for (int i = 0; i < cases.size(); i++) {
                var test = cases.get(i);
                var result = policy.select(test.ranked(), test.exploration(), test.previous(),
                        test.limit(), test.different(), test.similar());
                assertEquals(expected.get(i), result.stream().map(c -> c.item().itemId())
                        .collect(Collectors.joining(",")), "优化前后排序必须一致，样本 " + i);
            }
        }
    }

    @Test
    void firstScreenKeepsBrandAndCategoryCapsWhenAlternativesAreAvailable() {
        var candidates = new ArrayList<PreferenceRankedCandidate>();
        var titles = List.of("Alarm Clock", "Coffee Mug", "Wireless Headphones", "Book Shelf",
                "Yoga Mat", "Cooking Pan", "Desk Lamp", "Travel Pillow");
        for (int i = 0; i < titles.size(); i++) {
            candidates.add(candidate("dominant-" + i, titles.get(i), "Dominant", "Home", .99));
        }
        candidates.add(candidate("same-category", "Kitchen Scales", "Scales Brand", "Home", .8));
        for (int i = 0; i < titles.size(); i++) {
            candidates.add(candidate("alternative-" + i, "Alternative " + titles.get(i),
                    "Brand " + i, "Category " + i, .1));
        }

        var result = policy.select(candidates, Set.of(), List.of(), 8, false, false);

        assertEquals(8, result.size(), "备选充分时应保留完整首屏");
        var brandCounts = result.stream().collect(Collectors.groupingBy(c -> c.item().brand(), Collectors.counting()));
        var categoryCounts = result.stream().collect(Collectors.groupingBy(c -> c.item().category(), Collectors.counting()));
        assertTrue(brandCounts.values().stream().allMatch(count -> count <= 3), "高分品牌不应占满首屏");
        assertTrue(categoryCounts.values().stream().allMatch(count -> count <= 4), "高分类目不应占满首屏");
    }

    @Test
    void twentyItemRefreshKeepsStrongestMatchOnFirstScreenAlongsideExploration() {
        var candidates = new ArrayList<PreferenceRankedCandidate>();
        var explorationTitles = List.of("Coffee Mug", "Yoga Mat", "Book Shelf", "Travel Pillow", "Cooking Pan",
                "Garden Hose", "Alarm Clock", "Desk Fan", "Door Mat", "Wall Mirror");
        var matchingTitles = List.of("Wireless Headphones", "Gaming Keyboard", "Laptop Backpack", "Computer Mouse",
                "Printer Cartridge", "USB Microphone", "Camera Lens", "Portable Monitor", "Graphics Tablet", "Desktop Speakers");
        for (int i = 0; i < 10; i++) {
            candidates.add(candidate("explore-" + i, explorationTitles.get(i), "Explore Brand " + i, "Explore Category " + i, .01));
            candidates.add(candidate("match-" + i, matchingTitles.get(i), "Match Brand " + i, "Match Category " + i, .99 - i * .01));
        }
        var explorationIds = candidates.stream().map(c -> c.item().itemId()).filter(id -> id.startsWith("explore-")).collect(Collectors.toSet());

        var result = policy.select(candidates, explorationIds, List.of(), 20, true, false);

        assertEquals(20, result.size());
        assertEquals("match-0", result.getFirst().item().itemId(), "每页超过首屏容量时最相关商品仍应先展示");
        assertEquals(10, result.stream().filter(c -> explorationIds.contains(c.item().itemId())).count(),
                "修复展示顺序不能丢失已经保留的探索商品");
    }

    @Test
    void findingSimilarItemsDoesNotForceUnrelatedExplorationIntoResults() {
        var candidates = List.of(
                candidate("wireless", "Wireless Studio Headphones", "Audio One", "Headphones", .99),
                candidate("noise", "Noise Cancelling Headphones", "Audio Two", "Headphones", .98),
                candidate("wired", "Wired Monitor Headphones", "Audio Three", "Headphones", .97),
                candidate("mug", "Ceramic Coffee Mug", "Kitchen", "Drinkware", .01),
                candidate("mat", "Yoga Exercise Mat", "Fitness", "Exercise", .01));

        var result = policy.select(candidates, Set.of("mug", "mat"), List.of(), 3, false, true);

        assertEquals(Set.of("wireless", "noise", "wired"), result.stream().map(c -> c.item().itemId()).collect(Collectors.toSet()),
                "找相似应保留足够相关的候选，不套用换个方向的探索席位");
    }

    private static PreferenceRankedCandidate candidate(String id, String title, String brand, String category, double score) {
        var item = new ItemEmbeddingText(id, title, title, category, category, brand, null, Map.of());
        return new PreferenceRankedCandidate(item, score, 0, score, List.of());
    }
}
