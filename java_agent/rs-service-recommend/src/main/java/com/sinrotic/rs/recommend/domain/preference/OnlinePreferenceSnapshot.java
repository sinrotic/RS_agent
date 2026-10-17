package com.sinrotic.rs.recommend.domain.preference;

import java.util.List;
import java.util.Map;

public record OnlinePreferenceSnapshot(
        long version,
        Map<String, ItemPreference> itemPreferences,
        List<String> appliedFeedbackEventIds,
        Map<String, Long> itemVersions,
        java.time.Instant expiresAt
) {
    public OnlinePreferenceSnapshot(long version, Map<String, ItemPreference> itemPreferences,
                                    List<String> appliedFeedbackEventIds, Map<String, Long> itemVersions) {
        this(version, itemPreferences, appliedFeedbackEventIds, itemVersions, null);
    }
    public OnlinePreferenceSnapshot(long version, Map<String, ItemPreference> itemPreferences,
                                    List<String> appliedFeedbackEventIds) {
        this(version, itemPreferences, appliedFeedbackEventIds, Map.of());
    }
    public static OnlinePreferenceSnapshot empty() {
        return new OnlinePreferenceSnapshot(0L, Map.of(), List.of());
    }

    public OnlinePreferenceSnapshot {
        itemPreferences = itemPreferences == null ? Map.of() : Map.copyOf(itemPreferences);
        appliedFeedbackEventIds = appliedFeedbackEventIds == null ? List.of() : List.copyOf(appliedFeedbackEventIds);
        var versions = new java.util.HashMap<String, Long>();
        if (itemVersions != null) versions.putAll(itemVersions);
        itemPreferences.forEach((id, preference) -> versions.merge(id, preference.version(), Math::max));
        itemVersions = Map.copyOf(versions);
    }
}
