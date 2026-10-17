package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.feedback.FeedbackAppendCommand;
import com.sinrotic.rs.recommend.domain.feedback.FeedbackAppendResult;
import com.sinrotic.rs.recommend.domain.feedback.RecommendationFeedbackEvent;

import java.util.List;
import java.util.Optional;

public interface RecommendationFeedbackEventStore {
    /** 包含删除标记；按商品游标读取 MySQL 当前画像投影，不以 Redis 判定是否完成。 */
    List<RecommendationFeedbackEvent> currentProfileEvents(String profileUserId, String afterItemId, int limit);

    Optional<RecommendationFeedbackEvent> currentProfileItemEvent(String profileUserId, String itemId);

    /** 会话期限由 User 判定，此查询不以最后一次反馈时间排除仍活跃的会话。 */
    List<RecommendationFeedbackEvent> currentSessionEvents(
            com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity identity, String afterItemId, int limit);
    FeedbackAppendResult append(FeedbackAppendCommand command);

    /** 批次必须原子提交；未实现批量事务的适配器仅支持单项。 */
    default List<FeedbackAppendResult> appendBatch(List<FeedbackAppendCommand> commands) {
        if (commands.isEmpty()) return List.of();
        if (commands.size() != 1) throw new UnsupportedOperationException("反馈仓库未实现原子批量写入");
        return List.of(append(commands.getFirst()));
    }

    default Optional<RecommendationFeedbackEvent> findReversalOf(String eventId) { return Optional.empty(); }

    default List<RecommendationFeedbackEvent> pendingProjectionEvents(int limit) {
        return List.of();
    }

    default void markProjectionApplied(String eventId) {
    }

    default void markProjectionFailed(String eventId, String error) {
    }

    default List<RecommendationFeedbackEvent> rebuildablePreferenceEvents(int limit) {
        return List.of();
    }

    default List<RecommendationFeedbackEvent> rebuildablePreferenceEvents(
            String afterProfileUserId, String afterItemId, int limit) {
        return rebuildablePreferenceEvents(limit);
    }

    default Optional<RecommendationFeedbackEvent> findByEventId(String eventId) {
        return Optional.empty();
    }

    default boolean isReversed(String eventId) {
        return false;
    }

    default Optional<RecommendationFeedbackEvent> previousExplicitEvent(RecommendationFeedbackEvent target) {
        return Optional.empty();
    }

    default Optional<RecommendationFeedbackEvent> previousSessionExplicitEvent(RecommendationFeedbackEvent target) {
        return previousExplicitEvent(target).filter(event ->
                event.identity().sessionId().equals(target.identity().sessionId()));
    }

    default List<com.sinrotic.rs.recommend.domain.preference.SessionPreferenceProjection> rebuildableSessionPreferences(
            String afterProfileUserId, String afterSessionId, String afterItemId,
            java.time.Instant activeSince, int limit) {
        return List.of();
    }

    default String projectionStatus(String eventId) {
        return findByEventId(eventId)
                .map(event -> event.eventType().preferenceChanging() ? "APPLIED" : "NOT_APPLICABLE")
                .orElse("UNKNOWN");
    }
}
