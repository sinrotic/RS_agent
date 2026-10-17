package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.preference.ItemPreference;
import com.sinrotic.rs.recommend.domain.preference.OnlinePreferenceSnapshot;
import com.sinrotic.rs.recommend.domain.preference.PreferenceRankedCandidate;
import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import org.springframework.stereotype.Component;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import java.time.Clock;
import java.time.Duration;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.HashMap;
import java.util.HashSet;

@Component
public class PreferenceAwareFinalReranker {

    private static final double MAX_ADJUSTMENT = 0.25;
    private static final double EXPLORATION_RATIO = 0.20;
    private static final int FIRST_SCREEN_SIZE = 8;
    private static final int FIRST_SCREEN_CATEGORY_CAP = 4;
    private final Clock clock;
    private final double profileHalfLifeDays;

    public PreferenceAwareFinalReranker() { this(Clock.systemUTC(),30.0); }

    @Autowired
    public PreferenceAwareFinalReranker(
            @Value("${rs.recommend.preference.profile-half-life-days:${RS_RECOMMEND_PROFILE_HALF_LIFE_DAYS:30}}") double profileHalfLifeDays) {
        this(Clock.systemUTC(),profileHalfLifeDays);
    }

    public PreferenceAwareFinalReranker(Clock clock, double profileHalfLifeDays) {
        if (!Double.isFinite(profileHalfLifeDays) || profileHalfLifeDays <= 0)
            throw new IllegalArgumentException("画像偏好衰减半衰期必须为正数");
        this.clock = clock;
        this.profileHalfLifeDays = profileHalfLifeDays;
    }

    public List<PreferenceRankedCandidate> rerank(
            List<ItemEmbeddingText> candidates,
            OnlinePreferenceSnapshot snapshot,
            int limit
    ) {
        return rerank(candidates, snapshot, limit, Map.of());
    }

    public List<PreferenceRankedCandidate> rerank(List<ItemEmbeddingText> candidates,
            OnlinePreferenceSnapshot snapshot, int limit, Map<String, Double> modelScores) {
        List<PreferenceRankedCandidate> ranked = new ArrayList<>();
        for (int index = 0; index < candidates.size(); index++) {
            ItemEmbeddingText candidate = candidates.get(index);
            if (isExplicitlyDisliked(candidate.itemId(), snapshot.itemPreferences())) {
                continue;
            }
            double baseScore = modelScores.getOrDefault(candidate.itemId(), 1.0 - (index * 0.01));
            Adjustment adjustment = adjustment(candidate, snapshot.itemPreferences());
            double bounded = Math.max(-MAX_ADJUSTMENT, Math.min(MAX_ADJUSTMENT, adjustment.value()));
            ranked.add(new PreferenceRankedCandidate(
                    candidate, baseScore, bounded, baseScore + bounded, List.copyOf(adjustment.tags())));
        }
        List<PreferenceRankedCandidate> sorted = ranked.stream()
                .sorted(Comparator.comparingDouble(PreferenceRankedCandidate::finalScore).reversed()
                        .thenComparing(candidate -> candidate.item().itemId()))
                .toList();
        return protectDiversity(reserveExploration(sorted, limit), limit);
    }

    private List<PreferenceRankedCandidate> reserveExploration(
            List<PreferenceRankedCandidate> sorted,
            int limit
    ) {
        int boundedLimit = Math.max(0, Math.min(limit, sorted.size()));
        int explorationSlots = (int) Math.ceil(boundedLimit * EXPLORATION_RATIO);
        int preferenceSlots = boundedLimit - explorationSlots;
        List<PreferenceRankedCandidate> selected = new ArrayList<>(sorted.size());
        var selectedIds = new HashSet<String>();
        sorted.stream()
                .filter(candidate -> candidate.preferenceAdjustment() > 0)
                .limit(preferenceSlots)
                .forEach(candidate -> add(selected, selectedIds, candidate));
        sorted.stream()
                .filter(candidate -> candidate.preferenceAdjustment() <= 0)
                .limit(explorationSlots)
                .forEach(candidate -> add(selected, selectedIds, candidate));
        sorted.stream().forEach(candidate -> {
            if (selected.size() < boundedLimit) {
                add(selected, selectedIds, candidate);
            }
        });
        // Keep the unselected tail available to the diversity pass. The final
        // limit is applied only after the first-screen category cap is enforced.
        sorted.forEach(candidate -> add(selected, selectedIds, candidate));
        return selected;
    }

    private List<PreferenceRankedCandidate> protectDiversity(
            List<PreferenceRankedCandidate> candidates,
            int limit
    ) {
        List<PreferenceRankedCandidate> firstScreen = new ArrayList<>();
        List<PreferenceRankedCandidate> deferred = new ArrayList<>();
        Map<String, Integer> categoryCounts = new HashMap<>();
        Map<String, Integer> brandCounts = new HashMap<>();
        for (PreferenceRankedCandidate candidate : candidates) {
            String category = candidate.item().category() == null ? "" : candidate.item().category();
            String brand = candidate.item().brand() == null ? "" : candidate.item().brand().trim().toLowerCase(java.util.Locale.ROOT);
            if (firstScreen.size() < Math.min(FIRST_SCREEN_SIZE, limit)
                    && categoryCounts.getOrDefault(category, 0) < FIRST_SCREEN_CATEGORY_CAP
                    && (brand.isBlank() || brandCounts.getOrDefault(brand, 0) < 3)) {
                firstScreen.add(candidate);
                categoryCounts.merge(category, 1, Integer::sum);
                if (!brand.isBlank()) brandCounts.merge(brand, 1, Integer::sum);
            } else {
                deferred.add(candidate);
            }
        }
        List<PreferenceRankedCandidate> result = new ArrayList<>(firstScreen);
        result.addAll(deferred);
        return result.stream().limit(Math.max(0, limit)).toList();
    }

    private void add(
            List<PreferenceRankedCandidate> selected,
            HashSet<String> selectedIds,
            PreferenceRankedCandidate candidate
    ) {
        if (selectedIds.add(candidate.item().itemId())) {
            selected.add(candidate);
        }
    }

    private boolean isExplicitlyDisliked(String itemId, Map<String, ItemPreference> preferences) {
        ItemPreference preference = preferences.get(itemId);
        return preference != null
                && "dislike".equals(preference.eventType())
                && "session".equals(preference.scope());
    }

    private Adjustment adjustment(ItemEmbeddingText candidate, Map<String, ItemPreference> preferences) {
        double value = 0.0;
        List<String> tags = new ArrayList<>();
        for (ItemPreference preference : preferences.values()) {
            boolean liked = "like".equals(preference.eventType());
            boolean disliked = "dislike".equals(preference.eventType());
            if (!liked && !disliked) {
                continue;
            }
            double scopeWeight = 1.0;
            if ("profile".equals(preference.scope())) {
                if (preference.updatedAt() == null) continue;
                double ageDays = Math.max(0,Duration.between(preference.updatedAt(),clock.instant()).toMillis()/86400000.0);
                if (ageDays >= 180) continue;
                scopeWeight = 0.35 * Math.pow(0.5,ageDays/profileHalfLifeDays);
            }
            if (same(preference.brand(), candidate.brand())) {
                value += (liked ? 0.12 : -0.06) * scopeWeight;
                tags.add(liked ? "preference_like_brand" : "preference_dislike_brand");
            }
            if (same(preference.category(), candidate.category())) {
                value += (liked ? 0.10 : -0.05) * scopeWeight;
                tags.add(liked ? "preference_like_category" : "preference_dislike_category");
            }
            if (hasSharedAttribute(preference.attributes(), candidate.attributes())) {
                value += (liked ? 0.03 : -0.02) * scopeWeight;
                tags.add(liked ? "preference_like_attribute" : "preference_dislike_attribute");
            }
        }
        return new Adjustment(value, tags);
    }

    private boolean same(String left, String right) {
        return left != null && right != null && !left.isBlank() && left.equalsIgnoreCase(right);
    }

    private boolean hasSharedAttribute(Map<String, String> left, Map<String, String> right) {
        if (left == null || right == null || left.isEmpty() || right.isEmpty()) {
            return false;
        }
        return left.entrySet().stream().filter(entry -> {
            String key = entry.getKey().toLowerCase(java.util.Locale.ROOT);
            return !key.contains("discontinued") && !key.contains("date") && !key.contains("dimensions")
                    && !key.contains("weight") && !key.contains("model number") && !key.contains("asin")
                    && !key.contains("rank") && !key.contains("customer review");
        }).anyMatch(entry -> entry.getValue() != null && !entry.getValue().isBlank()
                && entry.getValue().equals(right.get(entry.getKey())));
    }

    private record Adjustment(double value, List<String> tags) {
    }
}
