package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.preference.PreferenceRankedCandidate;
import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import java.text.Normalizer;
import java.util.*;

/** Content diversity belongs to the home feed; finding similar items keeps its own intent. */
final class HomeFeedDiversity {
    private static final Set<String> STOP_WORDS = Set.of("a", "an", "the", "and", "or", "for", "with", "to", "of", "in", "on",
            "by", "up", "men", "women", "inch", "inches", "black", "white", "grey", "gray", "blue", "red", "pink", "green");

    List<PreferenceRankedCandidate> select(List<PreferenceRankedCandidate> ranked, Set<String> explorationIds,
            List<ItemEmbeddingText> previous, int limit, boolean showDifferent, boolean findSimilar) {
        var features = new FeatureCache();
        var available = new ArrayList<>(ranked.stream().filter(candidate -> previous.stream()
                .noneMatch(item -> sameFamily(candidate.item(), item, features))).toList());
        var selected = new ArrayList<PreferenceRankedCandidate>();
        int explorationSlots = findSimilar ? 0 : (int) Math.ceil(limit * (showDifferent ? .5 : .25));
        // A low preference adjustment is not exploration: only the actual Catalog source qualifies.
        for (int i = 0; i < explorationSlots; i++) {
            var candidate = best(available.stream().filter(c -> explorationIds.contains(c.item().itemId())).toList(), selected, previous, showDifferent, features);
            if (candidate == null) break;
            selected.add(candidate);
            available.remove(candidate);
        }
        while (selected.size() < limit) {
            var candidate = best(available, selected, previous, showDifferent, features);
            if (candidate == null) break;
            selected.add(candidate);
            available.remove(candidate);
        }
        // Present the strongest match first without discarding the reserved exploration items.
        selected.sort(Comparator.comparingDouble(PreferenceRankedCandidate::finalScore).reversed()
                .thenComparing(c -> c.item().itemId()));
        var firstScreen = new ArrayList<PreferenceRankedCandidate>();
        var deferred = new ArrayList<PreferenceRankedCandidate>();
        for (var candidate : selected) {
            if (firstScreen.size() < 8 && withinCaps(candidate, firstScreen, features)) firstScreen.add(candidate);
            else deferred.add(candidate);
        }
        firstScreen.addAll(deferred);
        return List.copyOf(firstScreen);
    }

    private PreferenceRankedCandidate best(List<PreferenceRankedCandidate> candidates, List<PreferenceRankedCandidate> selected,
            List<ItemEmbeddingText> previous, boolean showDifferent, FeatureCache features) {
        var candidate = best(candidates, selected, previous, showDifferent, false, features);
        return candidate != null ? candidate : best(candidates, selected, previous, showDifferent, true, features);
    }

    private PreferenceRankedCandidate best(List<PreferenceRankedCandidate> candidates, List<PreferenceRankedCandidate> selected,
            List<ItemEmbeddingText> previous, boolean showDifferent, boolean relaxCategoryAndBrand, FeatureCache features) {
        PreferenceRankedCandidate best = null;
        double bestUtility = -Double.MAX_VALUE;
        for (var candidate : candidates) {
            if (selected.stream().anyMatch(c -> sameFamily(candidate.item(), c.item(), features))) continue;
            if (!relaxCategoryAndBrand && selected.size() < 8 && !withinCaps(candidate, selected, features)) continue;
            var candidateTokens = features.get(candidate.item()).tokens();
            double currentSimilarity = selected.stream().mapToDouble(c -> similarity(candidateTokens, features.get(c.item()).tokens())).max().orElse(0);
            double previousSimilarity = showDifferent ? previous.stream()
                    .mapToDouble(c -> similarity(candidateTokens, features.get(c).tokens())).max().orElse(0) : 0;
            double utility = candidate.finalScore() - .45 * currentSimilarity - .8 * previousSimilarity;
            if (utility > bestUtility || (utility == bestUtility && best != null && candidate.item().itemId().compareTo(best.item().itemId()) < 0)) {
                best = candidate;
                bestUtility = utility;
            }
        }
        return best;
    }

    private boolean withinCaps(PreferenceRankedCandidate candidate, List<PreferenceRankedCandidate> selected, FeatureCache features) {
        long categoryCount = selected.stream().filter(c -> Objects.equals(c.item().category(), candidate.item().category())).count();
        String candidateBrand = features.get(candidate.item()).brand();
        long brandCount = candidateBrand.isBlank() ? 0 : selected.stream().filter(c -> candidateBrand.equals(features.get(c.item()).brand())).count();
        return categoryCount < 4 && brandCount < 3;
    }

    private boolean sameFamily(ItemEmbeddingText left, ItemEmbeddingText right, FeatureCache features) {
        if (left.itemId().equals(right.itemId())) return true;
        var leftFeatures = features.get(left);
        var rightFeatures = features.get(right);
        String leftModel = leftFeatures.model();
        String rightModel = rightFeatures.model();
        String leftBrand = leftFeatures.brand(), rightBrand = rightFeatures.brand();
        if (!leftModel.isBlank() && leftModel.equals(rightModel) && !leftBrand.isBlank() && leftBrand.equals(rightBrand)) return true;
        // Short generic titles (e.g. "Headphones") cannot establish that two items are the same product.
        var leftTokens = leftFeatures.tokens();
        var rightTokens = rightFeatures.tokens();
        return Math.min(leftTokens.size(), rightTokens.size()) >= 5 && similarity(leftTokens, rightTokens) >= .90;
    }

    private record ItemFeatures(Set<String> tokens, String brand, String model) {}

    /** 每次选择独享；同 ID 的不同商品快照不能复用特征。 */
    private final class FeatureCache {
        private final Map<ItemEmbeddingText, ItemFeatures> values = new IdentityHashMap<>();

        ItemFeatures get(ItemEmbeddingText item) {
            return values.computeIfAbsent(item, value -> new ItemFeatures(tokens(value.title()),
                    brand(value), attribute(value, "Item model number")));
        }
    }

    private String brand(ItemEmbeddingText item) {
        return item.brand() == null || item.brand().isBlank() ? attribute(item, "Brand") : item.brand().trim().toLowerCase(Locale.ROOT);
    }

    private String attribute(ItemEmbeddingText item, String name) {
        if (item.attributes() == null) return "";
        return item.attributes().entrySet().stream().filter(e -> name.equalsIgnoreCase(e.getKey()))
                .map(e -> Objects.toString(e.getValue(), "").trim().toLowerCase(Locale.ROOT))
                .filter(v -> !Set.of("", "n/a", "na", "none", "unknown").contains(v)).findFirst().orElse("");
    }

    static double similarity(String left, String right) { return similarity(tokens(left), tokens(right)); }

    private static double similarity(Set<String> left, Set<String> right) {
        if (left.isEmpty() || right.isEmpty()) return 0;
        long common = left.stream().filter(right::contains).count();
        return common / Math.sqrt((double) left.size() * right.size());
    }

    private static Set<String> tokens(String title) {
        var result = new HashSet<String>();
        String normalized = Normalizer.normalize(Objects.toString(title, ""), Normalizer.Form.NFKC).toLowerCase(Locale.ROOT);
        for (String token : normalized.split("[^\\p{L}\\p{N}]+")) {
            if (token.length() < 2 || token.chars().allMatch(Character::isDigit) || STOP_WORDS.contains(token)) continue;
            result.add(token);
        }
        return result;
    }
}
