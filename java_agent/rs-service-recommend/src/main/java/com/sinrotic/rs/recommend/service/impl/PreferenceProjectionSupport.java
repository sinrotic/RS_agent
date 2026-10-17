package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.feedback.*;
import com.sinrotic.rs.recommend.domain.preference.*;
import java.time.*;
import java.util.*;

/** Redis 与内存投影共用的范围、期限和单商品版本规则。 */
final class PreferenceProjectionSupport {
    static final Duration SESSION_TTL = Duration.ofHours(24);
    static final Duration PROFILE_TTL = Duration.ofDays(180);
    private static final int RECENT_EVENTS = 256;

    static OnlinePreferenceSnapshot profile(OnlinePreferenceSnapshot current, Instant now) {
        var preferences = new HashMap<>(current.itemPreferences());
        preferences.values().removeIf(p -> p.updatedAt() == null || !p.updatedAt().plus(PROFILE_TTL).isAfter(now));
        return new OnlinePreferenceSnapshot(current.version(),preferences,current.appliedFeedbackEventIds(),current.itemVersions());
    }

    static OnlinePreferenceSnapshot session(OnlinePreferenceSnapshot current, Instant now) {
        Instant expiry = current.expiresAt();
        if (expiry == null) expiry = current.itemPreferences().values().stream()
                .map(ItemPreference::updatedAt).filter(Objects::nonNull).max(Comparator.naturalOrder())
                .map(at -> at.plus(SESSION_TTL)).orElse(null);
        // 旧格式的删除快照没有可推断的活动时间，仍须保留商品版本，防止迟到反馈越过删除标记。
        return new OnlinePreferenceSnapshot(current.version(),expiry == null || !expiry.isAfter(now)
                ? Map.of() : current.itemPreferences(),current.appliedFeedbackEventIds(),current.itemVersions(),expiry);
    }

    static OnlinePreferenceSnapshot change(OnlinePreferenceSnapshot current, RecommendationFeedbackEvent event,
            RecommendationFeedbackEvent restored, String scope, Instant expiresAt, Instant now) {
        boolean session = "session".equals(scope);
        if (session && (expiresAt == null || !expiresAt.isAfter(now))) return session(current,now);
        // 权威活动期限已续期时，先保留原有商品和版本，再处理重放；不能先丢弃商品而被同版本挡住恢复。
        var base = session ? current : profile(current,now);
        Instant expiry = session ? (base.expiresAt() != null && base.expiresAt().isAfter(expiresAt)
                ? base.expiresAt() : expiresAt) : null;
        if (base.itemVersions().getOrDefault(event.item().itemId(),0L) >= event.preferenceVersion())
            return new OnlinePreferenceSnapshot(base.version(),base.itemPreferences(),base.appliedFeedbackEventIds(),base.itemVersions(),expiry);
        var preferences = new HashMap<>(base.itemPreferences());
        var effective = event.eventType() == FeedbackEventType.REVERSAL ? restored : event;
        if (effective == null || (!session && !event.receivedAt().plus(PROFILE_TTL).isAfter(now))) {
            preferences.remove(event.item().itemId());
        } else {
            preferences.put(event.item().itemId(),new ItemPreference(effective.eventId(),effective.eventType().apiValue(),
                    effective.item().itemId(),effective.item().category(),effective.item().brand(),effective.item().attributes(),
                    event.preferenceVersion(),event.receivedAt(),scope));
        }
        var ids = new ArrayList<>(base.appliedFeedbackEventIds());
        ids.remove(event.eventId());ids.add(event.eventId());
        if (ids.size() > RECENT_EVENTS) ids = new ArrayList<>(ids.subList(ids.size()-RECENT_EVENTS,ids.size()));
        var versions = new HashMap<>(base.itemVersions());versions.put(event.item().itemId(),event.preferenceVersion());
        return new OnlinePreferenceSnapshot(Math.max(base.version(),event.preferenceVersion()),preferences,ids,versions,expiry);
    }

    static OnlinePreferenceSnapshot merge(OnlinePreferenceSnapshot profile, OnlinePreferenceSnapshot session) {
        var preferences = new HashMap<>(profile.itemPreferences());preferences.putAll(session.itemPreferences());
        var ids = new LinkedHashSet<>(profile.appliedFeedbackEventIds());ids.addAll(session.appliedFeedbackEventIds());
        var versions = new HashMap<>(profile.itemVersions());
        session.itemVersions().forEach((id,version) -> versions.merge(id,version,Math::max));
        return new OnlinePreferenceSnapshot(Math.max(profile.version(),session.version()),preferences,List.copyOf(ids),versions);
    }
}
