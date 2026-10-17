package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.delivery.RecommendationDelivery;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationDeliveryItem;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.domain.dto.RecommendEventFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecommendExposureFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecommendExposureItemDTO;
import com.sinrotic.rs.recommend.domain.dto.RecommendFeedbackReversalRequestDTO;
import com.sinrotic.rs.recommend.domain.feedback.FeedbackAppendCommand;
import com.sinrotic.rs.recommend.domain.feedback.FeedbackAppendResult;
import com.sinrotic.rs.recommend.domain.feedback.FeedbackApplicationStatus;
import com.sinrotic.rs.recommend.domain.feedback.FeedbackEventType;
import com.sinrotic.rs.recommend.domain.vo.RecommendFeedbackAckVO;
import com.sinrotic.rs.recommend.service.OnlinePreferenceStore;
import com.sinrotic.rs.recommend.service.RecommendFeedbackService;
import com.sinrotic.rs.recommend.service.RecommendationDeliveryService;
import com.sinrotic.rs.recommend.service.RecommendationFeedbackEventStore;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.Clock;
import java.time.Instant;
import java.util.List;

@Service
public class DefaultRecommendFeedbackService implements RecommendFeedbackService {

    private final RecommendationDeliveryService deliveryService;
    private final RecommendationFeedbackEventStore eventStore;
    private final OnlinePreferenceStore preferenceStore;
    private final Clock clock;
    private final RecommendationFeedbackMetrics metrics;

    @Autowired
    public DefaultRecommendFeedbackService(
            RecommendationDeliveryService deliveryService,
            RecommendationFeedbackEventStore eventStore,
            OnlinePreferenceStore preferenceStore,
            RecommendationFeedbackMetrics metrics
    ) {
        this(deliveryService, eventStore, preferenceStore, Clock.systemUTC(), metrics);
    }

    public DefaultRecommendFeedbackService(
            RecommendationDeliveryService deliveryService,
            RecommendationFeedbackEventStore eventStore,
            OnlinePreferenceStore preferenceStore,
            Clock clock
    ) {
        this(deliveryService, eventStore, preferenceStore, clock, null);
    }

    private DefaultRecommendFeedbackService(
            RecommendationDeliveryService deliveryService,
            RecommendationFeedbackEventStore eventStore,
            OnlinePreferenceStore preferenceStore,
            Clock clock,
            RecommendationFeedbackMetrics metrics
    ) {
        this.deliveryService = deliveryService;
        this.eventStore = eventStore;
        this.preferenceStore = preferenceStore;
        this.clock = clock;
        this.metrics = metrics;
    }

    @Override
    public RecommendFeedbackAckVO recordExposure(RecommendExposureFeedbackRequestDTO request) {
        return rejected("exposure");
    }

    @Override
    public RecommendFeedbackAckVO recordEvent(RecommendEventFeedbackRequestDTO request) {
        return rejected(request.eventType());
    }

    @Override
    public RecommendFeedbackAckVO recordExposure(
            RecommendationIdentity identity,
            RecommendExposureFeedbackRequestDTO request
    ) {
        request = request.withDefaults();
        List<String> itemIds = request.itemIds().stream()
                .filter(itemId -> itemId != null && !itemId.isBlank())
                .distinct()
                .toList();
        if (itemIds.isEmpty() || !identity.sessionId().equals(request.sessionId())) {
            return rejected("exposure");
        }
        var commands = new java.util.ArrayList<FeedbackAppendCommand>(itemIds.size());
        // 整批归属和有效期校验完成后，才允许写入任何事件。
        for (String itemId : itemIds) {
            RecommendationDelivery delivery = deliveryService.requireFeedbackTarget(identity, request.requestId(), itemId);
            commands.add(command(delivery, item(delivery, itemId), FeedbackEventType.EXPOSURE, request.exposedAt(), exposureEvidence(request, itemId)));
        }
        var results = eventStore.appendBatch(commands);
        FeedbackAppendResult last = results.getLast();
        int acceptedCount = 0;
        boolean allDuplicates = true;
        for (var result : results) {
            if (!result.duplicate()) {
                acceptedCount++;
                allDuplicates = false;
            }
        }
        RecommendFeedbackAckVO ack = new RecommendFeedbackAckVO(
                last == null ? "" : last.event().eventId(), true, "exposure", acceptedCount,
                allDuplicates, FeedbackApplicationStatus.NOT_APPLICABLE.name(), 0L);
        accepted(ack);
        return ack;
    }

    @Override
    public RecommendFeedbackAckVO recordEvent(
            RecommendationIdentity identity,
            RecommendEventFeedbackRequestDTO request
    ) {
        request = request.withDefaults();
        if (!identity.sessionId().equals(request.sessionId())) {
            return rejected(request.eventType());
        }
        FeedbackEventType eventType;
        try {
            eventType = FeedbackEventType.parse(request.eventType());
        } catch (IllegalArgumentException exception) {
            return rejected(request.eventType());
        }
        if (eventType == FeedbackEventType.EXPOSURE || eventType == FeedbackEventType.REVERSAL) {
            return rejected(eventType.apiValue());
        }
        RecommendationDelivery delivery = deliveryService.requireFeedbackTarget(
                identity, request.requestId(), request.itemId());
        FeedbackAppendResult result = eventStore.append(command(
                delivery, item(delivery, request.itemId()), eventType, request.occurredAt(), null));
        FeedbackApplicationStatus status = FeedbackApplicationStatus.NOT_APPLICABLE;
        if (eventType.preferenceChanging()) {
            try {
                preferenceStore.apply(result.event());
                eventStore.markProjectionApplied(result.event().eventId());
                status = FeedbackApplicationStatus.APPLIED;
            } catch (RuntimeException projectionFailure) {
                eventStore.markProjectionFailed(result.event().eventId(), projectionFailure.getMessage());
                status = FeedbackApplicationStatus.PENDING;
            }
        }
        RecommendFeedbackAckVO ack = new RecommendFeedbackAckVO(
                result.event().eventId(), true, eventType.apiValue(), result.duplicate() ? 0 : 1,
                result.duplicate(), status.name(), result.event().preferenceVersion());
        accepted(ack);
        return ack;
    }

    @Override
    public RecommendFeedbackAckVO reverse(
            RecommendationIdentity actor,
            RecommendFeedbackReversalRequestDTO request
    ) {
        if (request == null || request.feedbackEventId() == null || request.feedbackEventId().isBlank()) {
            return rejected("reversal");
        }
        var target = eventStore.findByEventId(request.feedbackEventId()).orElse(null);
        if (target == null
                || !(target.eventType() == FeedbackEventType.LIKE || target.eventType() == FeedbackEventType.DISLIKE)
                || !target.identity().accountId().equals(actor.accountId())
                || !target.identity().profileUserId().equals(actor.profileUserId())) {
            return rejected("reversal");
        }
        if (eventStore.isReversed(target.eventId())) {
            var existing = eventStore.findReversalOf(target.eventId()).orElse(null);
            if (existing == null) return rejected("reversal");
            return new RecommendFeedbackAckVO(existing.eventId(), true, "reversal", 0, true,
                    eventStore.projectionStatus(existing.eventId()), existing.preferenceVersion());
        }
        var restored = eventStore.previousExplicitEvent(target).orElse(null);
        Instant now = clock.instant();
        FeedbackAppendResult result = eventStore.append(new FeedbackAppendCommand(
                target.requestId(), target.identity(), target.item(), FeedbackEventType.REVERSAL,
                target.eventId(), now, now, restored));
        restored = eventStore.previousExplicitEvent(target).orElse(null);
        FeedbackApplicationStatus status;
        try {
            preferenceStore.applyReversal(result.event(), restored,eventStore.previousSessionExplicitEvent(target).orElse(null));
            eventStore.markProjectionApplied(result.event().eventId());
            status = FeedbackApplicationStatus.APPLIED;
        } catch (RuntimeException projectionFailure) {
            eventStore.markProjectionFailed(result.event().eventId(), projectionFailure.getMessage());
            status = FeedbackApplicationStatus.PENDING;
        }
        RecommendFeedbackAckVO ack = new RecommendFeedbackAckVO(
                result.event().eventId(), true, "reversal", result.duplicate() ? 0 : 1,
                result.duplicate(), status.name(), result.event().preferenceVersion());
        accepted(ack);
        return ack;
    }

    private FeedbackAppendCommand command(
            RecommendationDelivery delivery,
            RecommendationDeliveryItem item,
            FeedbackEventType eventType,
            Long occurredAt,
            RecommendExposureItemDTO evidence
    ) {
        Instant receivedAt = clock.instant();
        Instant occurred = occurredAt == null ? receivedAt : Instant.ofEpochMilli(occurredAt);
        return new FeedbackAppendCommand(
                delivery.requestId(), delivery.identity(), item, eventType, null, occurred, receivedAt,
                evidence == null ? null : evidence.position(),
                evidence == null ? null : evidence.visibleRatio(),
                evidence == null ? null : evidence.visibleDurationMs(),
                null);
    }

    private RecommendExposureItemDTO exposureEvidence(
            RecommendExposureFeedbackRequestDTO request,
            String itemId
    ) {
        if (request.items() == null) {
            return null;
        }
        return request.items().stream()
                .filter(item -> item != null && itemId.equals(item.itemId()))
                .findFirst()
                .orElse(null);
    }

    private RecommendationDeliveryItem item(RecommendationDelivery delivery, String itemId) {
        return delivery.items().stream()
                .filter(item -> item.itemId().equals(itemId))
                .findFirst()
                .orElseThrow();
    }

    private RecommendFeedbackAckVO rejected(String type) {
        if (metrics != null) {
            metrics.rejected(type == null ? "invalid" : type);
        }
        return new RecommendFeedbackAckVO(
                "", false, type == null ? "invalid" : type, 0, false,
                FeedbackApplicationStatus.NOT_APPLICABLE.name(), 0L);
    }

    private void accepted(RecommendFeedbackAckVO ack) {
        if (metrics != null) {
            metrics.accepted(ack.feedbackType(), ack.applicationStatus(), ack.duplicate());
        }
    }
}
