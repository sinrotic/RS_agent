package com.sinrotic.rs.recommend.controller.app;

import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.domain.dto.RecommendFeedbackReversalRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.RecommendFeedbackAckVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendPreferenceItemVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendPreferencesVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendPreferenceClearVO;
import com.sinrotic.rs.recommend.service.impl.PreferenceFactReader;
import com.sinrotic.rs.recommend.service.RecommendFeedbackService;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/recommend/preferences")
public class RecommendPreferenceController {

    private static final int MAX_HISTORY_REVERSALS = 100;

    private final PreferenceFactReader preferenceStore;
    private final RecommendFeedbackService feedbackService;

    public RecommendPreferenceController(
            PreferenceFactReader preferenceStore,
            RecommendFeedbackService feedbackService
    ) {
        this.preferenceStore = preferenceStore;
        this.feedbackService = feedbackService;
    }

    @GetMapping
    public RecommendPreferencesVO preferences(
            @RequestHeader("X-Profile-User-Id") String profileUserId
    ) {
        var snapshot = preferenceStore.loadProfile(profileUserId);
        return new RecommendPreferencesVO(snapshot.version(), snapshot.itemPreferences().values().stream()
                .map(item -> new RecommendPreferenceItemVO(
                        item.itemId(), item.eventType(), item.category(), item.brand(), item.eventId(), item.version()))
                .sorted(java.util.Comparator.comparing(RecommendPreferenceItemVO::itemId))
                .toList());
    }

    @DeleteMapping("/items/{itemId}")
    public RecommendFeedbackAckVO deleteItem(
            @RequestHeader("X-Account-Id") String accountId,
            @RequestHeader("X-Profile-User-Id") String profileUserId,
            @PathVariable String itemId
    ) {
        return removeItemHistory(accountId, profileUserId, itemId, MAX_HISTORY_REVERSALS).ack();
    }

    @DeleteMapping
    public RecommendPreferenceClearVO clear(
            @RequestHeader("X-Account-Id") String accountId,
            @RequestHeader("X-Profile-User-Id") String profileUserId
    ) {
        var events = preferenceStore.profileEvents(profileUserId);
        var operations = new java.util.ArrayList<RecommendFeedbackAckVO>();
        int remaining = MAX_HISTORY_REVERSALS;
        for (var event : events) {
            if (remaining <= 0) break;
            if (preferenceStore.effective(event) == null && "APPLIED".equals(preferenceStore.status(event))) continue;
            String itemId = event.item().itemId();
            var result = removeItemHistory(accountId, profileUserId, itemId, remaining);
            remaining -= result.attempts();
            operations.add(result.ack());
            if (!result.ack().accepted() || !"APPLIED".equals(result.ack().applicationStatus())) break;
        }
        var current = preferences(profileUserId);
        boolean complete = current.items().isEmpty() && operations.stream().allMatch(RecommendFeedbackAckVO::operationComplete)
                && preferenceStore.profileEvents(profileUserId).stream().allMatch(event -> "APPLIED".equals(preferenceStore.status(event)));
        return new RecommendPreferenceClearVO(current.preferenceVersion(), current.items(), complete, java.util.List.copyOf(operations));
    }

    private RemovalResult removeItemHistory(
            String accountId,
            String profileUserId,
            String itemId,
            int limit
    ) {
        var actor = new RecommendationIdentity(accountId, profileUserId, "preference-management");
        RecommendFeedbackAckVO last = new RecommendFeedbackAckVO("", true, "reversal", 0, false, "APPLIED", 0);
        String previousEventId = null;
        for (int attempt = 0; attempt < limit; attempt++) {
            var event = preferenceStore.itemEvent(profileUserId,itemId).orElse(null);
            if (event == null) {
                return new RemovalResult(last.withOperationComplete(true),attempt);
            }
            // 回执丢失后，先返回既有 PENDING 删除回执；不能把恢复出的旧偏好误当作下一次删除目标。
            boolean pendingReversal = event.eventType() == com.sinrotic.rs.recommend.domain.feedback.FeedbackEventType.REVERSAL
                    && !"APPLIED".equals(preferenceStore.status(event));
            var item = preferenceStore.effective(event);
            if (!pendingReversal && item == null) return new RemovalResult(last.withOperationComplete(true),attempt);
            String targetEventId = pendingReversal ? event.reversesEventId() : item.eventId();
            if (targetEventId.equals(previousEventId)) {
                return new RemovalResult(last.withOperationComplete(false),attempt);
            }
            previousEventId = targetEventId;
            last = feedbackService.reverse(actor, new RecommendFeedbackReversalRequestDTO(targetEventId));
            if (!last.accepted() || !"APPLIED".equals(last.applicationStatus())) {
                return new RemovalResult(last.withOperationComplete(false),attempt + 1);
            }
        }
        return new RemovalResult(last.withOperationComplete(!preferenceStore.loadProfile(profileUserId).itemPreferences().containsKey(itemId)),limit);
    }

    private record RemovalResult(RecommendFeedbackAckVO ack, int attempts) { }
}
