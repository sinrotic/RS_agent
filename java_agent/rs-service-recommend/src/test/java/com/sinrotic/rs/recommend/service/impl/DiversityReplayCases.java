package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.preference.PreferenceRankedCandidate;
import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import java.util.*;

/** 固定输入用于重放优化前的排序，包含同 ID 异标题、型号与属性品牌。 */
final class DiversityReplayCases {
    record Case(List<PreferenceRankedCandidate> ranked, Set<String> exploration,
                List<ItemEmbeddingText> previous, int limit, boolean different, boolean similar) {}

    static List<Case> cases() {
        var random = new Random(20261010);
        String[] titles = {"Wireless Studio Headphones", "Noise Cancelling Studio Headphones",
                "Logitech Wireless Silent Office Mouse USB", "Ｌｏｇｉｔｅｃｈ wireless silent office mouse USB",
                "Ceramic Coffee Travel Mug", "Kitchen Cooking Steel Pan", "Book Shelf", null, "",
                "Bluetooth Gaming Keyboard Portable", "Travel Pillow", "Headphones", "Blue black 123 mouse"};
        var result = new ArrayList<Case>();
        for (int scenario = 0; scenario < 36; scenario++) {
            var ranked = new ArrayList<PreferenceRankedCandidate>();
            var exploration = new HashSet<String>();
            for (int i = 0; i < 36; i++) {
                String id = "item-" + (i == 35 ? 0 : i);
                String brand = i % 4 == 0 ? null : "Brand " + random.nextInt(5);
                Map<String, String> attributes = Map.of("bRaNd", "Attribute Brand " + i % 3,
                        "Item model number", i % 6 == 0 ? "same-model" : "n/a");
                var item = new ItemEmbeddingText(id, "", titles[random.nextInt(titles.length)],
                        i % 7 == 0 ? null : "Category " + random.nextInt(6), "", brand, null, attributes);
                double score = random.nextInt(8) / 8.0;
                ranked.add(new PreferenceRankedCandidate(item, score, 0, score, List.of()));
                if (i % 3 == 0) exploration.add(id);
            }
            Collections.shuffle(ranked, random);
            var previous = new ArrayList<ItemEmbeddingText>();
            if (scenario % 2 == 0) previous.add(ranked.get(0).item());
            if (scenario % 3 == 0) previous.add(new ItemEmbeddingText("seen", "", titles[2], "", "", "Brand 1", null, Map.of()));
            result.add(new Case(ranked, exploration, previous, scenario % 3 == 0 ? 20 : 8,
                    scenario % 2 == 0, scenario % 4 == 0));
        }
        return result;
    }

    public static void main(String[] args) {
        var policy = new HomeFeedDiversity();
        for (var test : cases()) {
            System.out.println(policy.select(test.ranked(), test.exploration(), test.previous(),
                    test.limit(), test.different(), test.similar()).stream()
                    .map(c -> c.item().itemId()).reduce((a, b) -> a + "," + b).orElse(""));
        }
    }
}
