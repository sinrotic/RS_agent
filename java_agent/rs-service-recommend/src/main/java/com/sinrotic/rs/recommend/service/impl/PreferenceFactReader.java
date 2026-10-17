package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.feedback.FeedbackEventType;
import com.sinrotic.rs.recommend.domain.feedback.RecommendationFeedbackEvent;
import com.sinrotic.rs.recommend.domain.preference.OnlinePreferenceSnapshot;
import com.sinrotic.rs.recommend.service.RecommendationFeedbackEventStore;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.Clock;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/** 管理接口使用持久事实，包含删除标记和待同步回执，缓存丢失不改变删除结果。 */
@Service
public class PreferenceFactReader {
    private final RecommendationFeedbackEventStore events;
    private final Clock clock;

    @Autowired
    public PreferenceFactReader(RecommendationFeedbackEventStore events) { this(events,Clock.systemUTC()); }

    public PreferenceFactReader(RecommendationFeedbackEventStore events, Clock clock) {
        this.events = events;
        this.clock = clock;
    }

    public List<RecommendationFeedbackEvent> profileEvents(String profileUserId) {
        var result = new ArrayList<RecommendationFeedbackEvent>();
        String cursor = "";
        while (true) {
            var page = events.currentProfileEvents(profileUserId,cursor,1000);
            result.addAll(page);
            if (page.size() < 1000) return List.copyOf(result);
            cursor = page.getLast().item().itemId();
        }
    }

    public Optional<RecommendationFeedbackEvent> itemEvent(String profileUserId, String itemId) {
        return events.currentProfileItemEvent(profileUserId,itemId);
    }

    public RecommendationFeedbackEvent effective(RecommendationFeedbackEvent event) {
        return event.eventType() == FeedbackEventType.REVERSAL
                ? events.previousExplicitEvent(events.findByEventId(event.reversesEventId()).orElseThrow()).orElse(null)
                : event;
    }

    public String status(RecommendationFeedbackEvent event) { return events.projectionStatus(event.eventId()); }

    public OnlinePreferenceSnapshot loadProfile(String profileUserId) {
        var snapshot = new OnlinePreferenceSnapshot(0,Map.of(),List.of());
        for (var event : profileEvents(profileUserId)) {
            snapshot = PreferenceProjectionSupport.change(snapshot,event,effective(event),"profile",null,clock.instant());
        }
        return snapshot;
    }
}
