package com.sinrotic.rs.recommend.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationDelivery;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationDeliveryItem;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.domain.feedback.FeedbackAppendCommand;
import com.sinrotic.rs.recommend.domain.feedback.FeedbackAppendResult;
import com.sinrotic.rs.recommend.domain.feedback.FeedbackEventType;
import com.sinrotic.rs.recommend.domain.feedback.RecommendationFeedbackEvent;
import com.sinrotic.rs.recommend.service.RecommendationDeliveryStore;
import com.sinrotic.rs.recommend.service.RecommendationFeedbackEventStore;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.support.TransactionTemplate;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

@Repository
@ConditionalOnProperty(name = "rs.recommend.feedback.persistence", havingValue = "jdbc")
public class JdbcRecommendationPersistenceStore
        implements RecommendationDeliveryStore, RecommendationFeedbackEventStore {

    private static final TypeReference<Map<String, String>> STRING_MAP = new TypeReference<>() { };
    private static final String PROFILE_VERSION_SCOPE = "__profile__";

    private final JdbcTemplate jdbc;
    private final TransactionTemplate transaction;
    private final ObjectMapper objectMapper;

    public JdbcRecommendationPersistenceStore(
            JdbcTemplate recommendationJdbcTemplate,
            TransactionTemplate recommendationTransactionTemplate,
            ObjectMapper objectMapper
    ) {
        this.jdbc = recommendationJdbcTemplate;
        this.transaction = recommendationTransactionTemplate;
        this.objectMapper = objectMapper;
    }

    @Override
    public RecommendationDelivery save(RecommendationDelivery delivery) {
        transaction.executeWithoutResult(status -> {
            jdbc.update("""
                    INSERT INTO rs_recommendation_delivery
                      (request_id, account_id, profile_user_id, session_id, scene, preference_version, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, delivery.requestId(), delivery.identity().accountId(), delivery.identity().profileUserId(),
                    delivery.identity().sessionId(), delivery.scene(), delivery.preferenceVersion(),
                    Timestamp.from(delivery.createdAt()), Timestamp.from(delivery.expiresAt()));
            if (!delivery.items().isEmpty()) {
                var args = new java.util.ArrayList<Object>(delivery.items().size() * 7);
                for (RecommendationDeliveryItem item : delivery.items()) {
                    args.add(delivery.requestId());
                    args.add(item.itemId());
                    args.add(item.rank());
                    args.add(item.baseScore());
                    args.add(item.category());
                    args.add(item.brand());
                    args.add(json(item.attributes()));
                }
                String placeholders = String.join(", ", java.util.Collections.nCopies(delivery.items().size(), "(?, ?, ?, ?, ?, ?, ?)"));
                jdbc.update("""
                        INSERT INTO rs_recommendation_delivery_item
                          (request_id, item_id, rank_no, base_score, category, brand, attributes_json)
                        VALUES
                        """ + placeholders, args.toArray());
            }
        });
        return delivery;
    }

    @Override
    public Optional<RecommendationDelivery> findByRequestId(String requestId) {
        List<RecommendationDelivery> deliveries = jdbc.query("""
                SELECT request_id, account_id, profile_user_id, session_id, scene, preference_version, created_at, expires_at
                FROM rs_recommendation_delivery WHERE request_id = ?
                """, (rs, rowNum) -> new RecommendationDelivery(
                rs.getString("request_id"),
                new RecommendationIdentity(rs.getString("account_id"), rs.getString("profile_user_id"), rs.getString("session_id")),
                rs.getString("scene"), rs.getLong("preference_version"), loadDeliveryItems(requestId),
                rs.getTimestamp("created_at").toInstant(), rs.getTimestamp("expires_at").toInstant()), requestId);
        return deliveries.stream().findFirst();
    }

    @Override
    public FeedbackAppendResult append(FeedbackAppendCommand command) {
        RecommendationFeedbackEvent existing = findByIdempotencyKey(command.idempotencyKey()).orElse(null);
        if (existing != null) {
            return new FeedbackAppendResult(existing, true);
        }
        try {
            RecommendationFeedbackEvent event = transaction.execute(status -> appendInTransaction(command));
            return new FeedbackAppendResult(event, false);
        } catch (DuplicateKeyException duplicate) {
            return new FeedbackAppendResult(findByIdempotencyKey(command.idempotencyKey()).orElseThrow(), true);
        }
    }

    @Override
    public List<FeedbackAppendResult> appendBatch(List<FeedbackAppendCommand> commands) {
        var batch = List.copyOf(commands);
        if (batch.isEmpty()) return List.of();
        for (int attempt = 0; ; attempt++) {
            try {
                return transaction.execute(status -> batch.stream().map(command -> {
                    var existing = findByIdempotencyKey(command.idempotencyKey()).orElse(null);
                    return existing == null ? new FeedbackAppendResult(appendInTransaction(command), false)
                            : new FeedbackAppendResult(existing, true);
                }).toList());
            } catch (DuplicateKeyException collision) {
                // 并发批次先提交时，整批回滚后重新读取幂等结果，不能在回滚事务内继续写入。
                if (attempt >= 2) throw collision;
            }
        }
    }

    @Override
    public Optional<RecommendationFeedbackEvent> findReversalOf(String eventId) {
        return jdbc.query("SELECT * FROM rs_recommend_feedback_event WHERE reverses_event_id = ? AND event_type = 'reversal' LIMIT 1",
                this::mapEvent, eventId).stream().findFirst();
    }

    @Override
    public java.util.Set<String> recentItemIds(String profileUserId, Instant since, int limit) {
        int bounded = Math.max(1, Math.min(2000, limit));
        var items = new java.util.HashSet<>(jdbc.queryForList("""
                SELECT i.item_id FROM rs_recommendation_delivery d
                JOIN rs_recommendation_delivery_item i ON i.request_id = d.request_id
                WHERE d.profile_user_id = ? AND d.created_at >= ?
                ORDER BY d.created_at DESC, i.rank_no LIMIT ?
                """, String.class, profileUserId, Timestamp.from(since), bounded));
        items.addAll(jdbc.queryForList("""
                SELECT item_id FROM rs_recommend_feedback_event
                WHERE profile_user_id = ? AND received_at >= ? AND event_type = 'exposure'
                ORDER BY received_at DESC LIMIT ?
                """, String.class, profileUserId, Timestamp.from(since), bounded));
        return java.util.Set.copyOf(items);
    }

    @Override
    public List<RecommendationFeedbackEvent> pendingProjectionEvents(int limit) {
        return jdbc.query("""
                SELECT e.* FROM rs_recommend_feedback_event e
                JOIN rs_recommend_feedback_outbox o ON o.event_id = e.event_id
                WHERE o.status = 'PENDING' AND o.next_attempt_at <= CURRENT_TIMESTAMP(3)
                ORDER BY o.created_at LIMIT ?
                """, this::mapEvent, Math.max(1, limit));
    }

    @Override
    public void markProjectionApplied(String eventId) {
        jdbc.update("""
                UPDATE rs_recommend_feedback_outbox
                SET status = 'APPLIED', applied_at = CURRENT_TIMESTAMP(3), last_error = NULL
                WHERE event_id = ?
                """, eventId);
    }

    @Override
    public void markProjectionFailed(String eventId, String error) {
        jdbc.update("""
                UPDATE rs_recommend_feedback_outbox
                SET status = 'PENDING', applied_at = NULL,
                    attempt_count = attempt_count + 1,
                    next_attempt_at = TIMESTAMPADD(SECOND, LEAST(300, POW(2, attempt_count)), CURRENT_TIMESTAMP(3)),
                    last_error = ?
                WHERE event_id = ?
                """, error == null ? "projection failed" : error.substring(0, Math.min(error.length(), 1000)), eventId);
    }

    @Override
    public List<RecommendationFeedbackEvent> rebuildablePreferenceEvents(int limit) {
        return rebuildablePreferenceEvents("", "", limit);
    }

    @Override
    public List<RecommendationFeedbackEvent> rebuildablePreferenceEvents(
            String afterProfileUserId, String afterItemId, int limit) {
        return jdbc.query("""
                SELECT e.* FROM rs_profile_item_preference_projection p
                JOIN rs_recommend_feedback_event e ON e.event_id = p.latest_event_id
                WHERE p.expires_at > CURRENT_TIMESTAMP(3)
                  AND (p.profile_user_id > ? OR (p.profile_user_id = ? AND p.item_id > ?))
                ORDER BY p.profile_user_id, p.item_id LIMIT ?
                """, this::mapEvent, afterProfileUserId, afterProfileUserId, afterItemId, Math.max(1, limit));
    }

    @Override
    public Optional<RecommendationFeedbackEvent> findByEventId(String eventId) {
        return jdbc.query("SELECT * FROM rs_recommend_feedback_event WHERE event_id = ?",
                this::mapEvent, eventId).stream().findFirst();
    }

    @Override
    public List<RecommendationFeedbackEvent> currentProfileEvents(String profileUserId, String afterItemId, int limit) {
        return jdbc.query("""
                SELECT e.* FROM rs_profile_item_preference_projection p
                JOIN rs_recommend_feedback_event e ON e.event_id = p.latest_event_id
                WHERE p.profile_user_id = ? AND p.item_id > ? AND p.expires_at > CURRENT_TIMESTAMP(3)
                ORDER BY p.item_id LIMIT ?
                """, this::mapEvent, profileUserId, afterItemId, Math.max(1, Math.min(1000, limit)));
    }

    @Override
    public Optional<RecommendationFeedbackEvent> currentProfileItemEvent(String profileUserId, String itemId) {
        return jdbc.query("""
                SELECT e.* FROM rs_profile_item_preference_projection p
                JOIN rs_recommend_feedback_event e ON e.event_id = p.latest_event_id
                WHERE p.profile_user_id = ? AND p.item_id = ? AND p.expires_at > CURRENT_TIMESTAMP(3)
                """, this::mapEvent, profileUserId, itemId).stream().findFirst();
    }

    @Override
    public List<RecommendationFeedbackEvent> currentSessionEvents(
            RecommendationIdentity identity, String afterItemId, int limit) {
        return jdbc.query("""
                SELECT e.* FROM rs_recommend_feedback_event e
                WHERE e.account_id = ? AND e.profile_user_id = ? AND e.session_id = ?
                  AND e.item_id > ? AND e.preference_version > 0
                  AND NOT EXISTS (
                    SELECT 1 FROM rs_recommend_feedback_event newer
                    WHERE newer.profile_user_id = e.profile_user_id AND newer.session_id = e.session_id
                      AND newer.item_id = e.item_id AND newer.preference_version > e.preference_version)
                ORDER BY e.item_id LIMIT ?
                """, this::mapEvent, identity.accountId(), identity.profileUserId(), identity.sessionId(),
                afterItemId, Math.max(1, Math.min(1000, limit)));
    }

    @Override
    public List<com.sinrotic.rs.recommend.domain.preference.SessionPreferenceProjection> rebuildableSessionPreferences(
            String afterProfileUserId, String afterSessionId, String afterItemId, Instant activeSince, int limit) {
        return jdbc.query("""
                SELECT e.*, activity.last_activity
                FROM rs_recommend_feedback_event e
                JOIN (
                  SELECT profile_user_id, session_id, MAX(received_at) AS last_activity
                  FROM rs_recommend_feedback_event WHERE preference_version > 0
                  GROUP BY profile_user_id, session_id HAVING MAX(received_at) > ?
                ) activity ON activity.profile_user_id = e.profile_user_id AND activity.session_id = e.session_id
                WHERE e.preference_version > 0
                  AND NOT EXISTS (
                    SELECT 1 FROM rs_recommend_feedback_event newer
                    WHERE newer.profile_user_id = e.profile_user_id AND newer.session_id = e.session_id
                      AND newer.item_id = e.item_id AND newer.preference_version > e.preference_version
                  )
                  AND (e.profile_user_id > ? OR (e.profile_user_id = ? AND
                    (e.session_id > ? OR (e.session_id = ? AND e.item_id > ?))))
                ORDER BY e.profile_user_id, e.session_id, e.item_id LIMIT ?
                """, (rs,row) -> new com.sinrotic.rs.recommend.domain.preference.SessionPreferenceProjection(
                    mapEvent(rs,row),rs.getTimestamp("last_activity").toInstant().plus(java.time.Duration.ofHours(24))),
                Timestamp.from(activeSince),afterProfileUserId,afterProfileUserId,
                afterSessionId,afterSessionId,afterItemId,Math.max(1,limit));
    }

    @Override
    public Optional<RecommendationFeedbackEvent> previousSessionExplicitEvent(RecommendationFeedbackEvent target) {
        return jdbc.query("""
                SELECT e.* FROM rs_recommend_feedback_event e
                WHERE e.profile_user_id = ? AND e.session_id = ? AND e.item_id = ?
                  AND e.event_type IN ('like', 'dislike') AND e.event_id <> ?
                  AND NOT EXISTS (SELECT 1 FROM rs_recommend_feedback_event reversal
                                  WHERE reversal.reverses_event_id = e.event_id)
                ORDER BY e.preference_version DESC LIMIT 1
                """,this::mapEvent,target.identity().profileUserId(),target.identity().sessionId(),
                target.item().itemId(),target.eventId()).stream().findFirst();
    }

    @Override
    public boolean isReversed(String eventId) {
        Integer count = jdbc.queryForObject(
                "SELECT COUNT(*) FROM rs_recommend_feedback_event WHERE reverses_event_id = ?",
                Integer.class, eventId);
        return count != null && count > 0;
    }

    @Override
    public Optional<RecommendationFeedbackEvent> previousExplicitEvent(RecommendationFeedbackEvent target) {
        return jdbc.query("""
                SELECT e.* FROM rs_recommend_feedback_event e
                WHERE e.profile_user_id = ? AND e.item_id = ?
                  AND e.event_type IN ('like', 'dislike')
                  AND e.event_id <> ?
                  AND NOT EXISTS (
                    SELECT 1 FROM rs_recommend_feedback_event reversal
                    WHERE reversal.reverses_event_id = e.event_id
                  )
                ORDER BY e.preference_version DESC LIMIT 1
                """, this::mapEvent, target.identity().profileUserId(), target.item().itemId(),
                target.eventId()).stream().findFirst();
    }

    @Override
    public String projectionStatus(String eventId) {
        RecommendationFeedbackEvent event = findByEventId(eventId).orElse(null);
        if (event == null) {
            return "UNKNOWN";
        }
        if (!event.eventType().preferenceChanging()) {
            return "NOT_APPLICABLE";
        }
        return jdbc.query("SELECT status FROM rs_recommend_feedback_outbox WHERE event_id = ?",
                (rs, rowNum) -> rs.getString("status"), eventId).stream().findFirst().orElse("PENDING");
    }

    private RecommendationFeedbackEvent appendInTransaction(FeedbackAppendCommand command) {
        long version = command.eventType().preferenceChanging() ? nextVersion(command.identity()) : 0L;
        String eventId = "fb_evt_" + UUID.randomUUID();
        jdbc.update("""
                INSERT INTO rs_recommend_feedback_event
                  (event_id, idempotency_key, request_id, item_id, account_id, profile_user_id, session_id,
                   event_type, reverses_event_id, position_no, visible_ratio, visible_duration_ms,
                   category, brand, attributes_json, occurred_at, received_at, preference_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, eventId, command.idempotencyKey(), command.requestId(), command.item().itemId(),
                command.identity().accountId(), command.identity().profileUserId(), command.identity().sessionId(),
                command.eventType().apiValue(), command.reversesEventId(), command.position(), command.visibleRatio(),
                command.visibleDurationMs(), command.item().category(), command.item().brand(),
                json(command.item().attributes()), Timestamp.from(command.occurredAt()),
                Timestamp.from(command.receivedAt()), version == 0 ? null : version);
        if (command.eventType().preferenceChanging()) {
            if (command.eventType() == FeedbackEventType.REVERSAL) {
                // Re-evaluate under the profile-version row lock, after the reversal is durable in this transaction.
                RecommendationFeedbackEvent restored = previousExplicitEvent(
                        findByEventId(command.reversesEventId()).orElseThrow()).orElse(null);
                if (restored == null) {
                    jdbc.update("""
                            INSERT INTO rs_profile_item_preference_projection
                              (profile_user_id, item_id, latest_event_id, effective_event_id, current_state,
                               category, brand, attributes_json, preference_version, updated_at, expires_at)
                            VALUES (?, ?, ?, ?, 'none', '', '', '{}', ?, ?, ?)
                            ON DUPLICATE KEY UPDATE latest_event_id = VALUES(latest_event_id),
                              effective_event_id = VALUES(effective_event_id), current_state = 'none',
                              preference_version = VALUES(preference_version), updated_at = VALUES(updated_at),
                              expires_at = VALUES(expires_at)
                            """, command.identity().profileUserId(), command.item().itemId(), eventId, eventId,
                            version, Timestamp.from(command.receivedAt()), profileExpiry(command));
                } else {
                    jdbc.update("""
                            INSERT INTO rs_profile_item_preference_projection
                              (profile_user_id, item_id, latest_event_id, effective_event_id, current_state, category, brand, attributes_json,
                               preference_version, updated_at, expires_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON DUPLICATE KEY UPDATE latest_event_id = VALUES(latest_event_id), effective_event_id = VALUES(effective_event_id), current_state = VALUES(current_state),
                              category = VALUES(category), brand = VALUES(brand), attributes_json = VALUES(attributes_json),
                              preference_version = VALUES(preference_version), updated_at = VALUES(updated_at), expires_at = VALUES(expires_at)
                            """, command.identity().profileUserId(), restored.item().itemId(), eventId, restored.eventId(),
                            restored.eventType().apiValue(), restored.item().category(), restored.item().brand(),
                            json(restored.item().attributes()), version, Timestamp.from(command.receivedAt()),
                            profileExpiry(command));
                }
            } else {
                jdbc.update("""
                    INSERT INTO rs_profile_item_preference_projection
                      (profile_user_id, item_id, latest_event_id, effective_event_id, current_state, category, brand, attributes_json,
                       preference_version, updated_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON DUPLICATE KEY UPDATE latest_event_id = VALUES(latest_event_id), effective_event_id = VALUES(effective_event_id), current_state = VALUES(current_state),
                      category = VALUES(category), brand = VALUES(brand), attributes_json = VALUES(attributes_json),
                      preference_version = VALUES(preference_version), updated_at = VALUES(updated_at), expires_at = VALUES(expires_at)
                    """, command.identity().profileUserId(), command.item().itemId(), eventId, eventId,
                    command.eventType().apiValue(), command.item().category(), command.item().brand(),
                    json(command.item().attributes()), version, Timestamp.from(command.receivedAt()),
                    profileExpiry(command));
            }
            jdbc.update("""
                    INSERT INTO rs_recommend_feedback_outbox
                      (event_id, status, attempt_count, next_attempt_at, created_at)
                    VALUES (?, 'PENDING', 0, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3))
                    """, eventId);
        }
        return new RecommendationFeedbackEvent(
                eventId, command.idempotencyKey(), command.requestId(), command.identity(), command.item(),
                command.eventType(), command.reversesEventId(), command.occurredAt(), command.receivedAt(),
                command.position(), command.visibleRatio(), command.visibleDurationMs(), version);
    }

    private long nextVersion(RecommendationIdentity identity) {
        jdbc.update("""
                INSERT IGNORE INTO rs_preference_version (profile_user_id, session_id, version_no)
                VALUES (?, ?, 0)
                """, identity.profileUserId(), PROFILE_VERSION_SCOPE);
        Long current = jdbc.queryForObject("""
                SELECT version_no FROM rs_preference_version
                WHERE profile_user_id = ? AND session_id = ? FOR UPDATE
                """, Long.class, identity.profileUserId(), PROFILE_VERSION_SCOPE);
        long next = (current == null ? 0 : current) + 1;
        jdbc.update("""
                UPDATE rs_preference_version SET version_no = ?, updated_at = CURRENT_TIMESTAMP(3)
                WHERE profile_user_id = ? AND session_id = ?
                """, next, identity.profileUserId(), PROFILE_VERSION_SCOPE);
        return next;
    }

    private Timestamp profileExpiry(FeedbackAppendCommand command) {
        return Timestamp.from(command.receivedAt().plus(PreferenceProjectionSupport.PROFILE_TTL));
    }

    private Optional<RecommendationFeedbackEvent> findByIdempotencyKey(String key) {
        return jdbc.query("SELECT * FROM rs_recommend_feedback_event WHERE idempotency_key = ?",
                this::mapEvent, key).stream().findFirst();
    }

    private RecommendationFeedbackEvent mapEvent(ResultSet rs, int rowNum) throws SQLException {
        Long version = rs.getObject("preference_version", Long.class);
        RecommendationIdentity identity = new RecommendationIdentity(
                rs.getString("account_id"), rs.getString("profile_user_id"), rs.getString("session_id"));
        RecommendationDeliveryItem item = new RecommendationDeliveryItem(
                rs.getString("item_id"), 1, 0.0, rs.getString("category"), rs.getString("brand"),
                map(rs.getString("attributes_json")));
        return new RecommendationFeedbackEvent(
                rs.getString("event_id"), rs.getString("idempotency_key"), rs.getString("request_id"), identity,
                item, FeedbackEventType.parse(rs.getString("event_type")), rs.getString("reverses_event_id"),
                rs.getTimestamp("occurred_at").toInstant(), rs.getTimestamp("received_at").toInstant(),
                rs.getObject("position_no", Integer.class), rs.getObject("visible_ratio", Double.class),
                rs.getObject("visible_duration_ms", Long.class), version == null ? 0L : version);
    }

    private List<RecommendationDeliveryItem> loadDeliveryItems(String requestId) {
        return jdbc.query("""
                SELECT item_id, rank_no, base_score, category, brand, attributes_json
                FROM rs_recommendation_delivery_item WHERE request_id = ? ORDER BY rank_no
                """, (rs, rowNum) -> new RecommendationDeliveryItem(
                rs.getString("item_id"), rs.getInt("rank_no"), rs.getDouble("base_score"),
                rs.getString("category"), rs.getString("brand"), map(rs.getString("attributes_json"))), requestId);
    }

    private String json(Map<String, String> value) {
        try {
            return objectMapper.writeValueAsString(value == null ? Map.of() : value);
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("cannot serialize recommendation attributes", exception);
        }
    }

    private Map<String, String> map(String value) {
        if (value == null || value.isBlank()) {
            return Map.of();
        }
        try {
            return objectMapper.readValue(value, STRING_MAP);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("cannot deserialize recommendation attributes", exception);
        }
    }
}
