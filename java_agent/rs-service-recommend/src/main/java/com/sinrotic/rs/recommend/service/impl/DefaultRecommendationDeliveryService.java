package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.delivery.RecommendationDelivery;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationDeliveryItem;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.service.RecommendationDeliveryService;
import com.sinrotic.rs.recommend.service.RecommendationDeliveryStore;
import com.sinrotic.rs.recommend.service.RecommendationFeedbackRejectedException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;

@Service
public class DefaultRecommendationDeliveryService implements RecommendationDeliveryService {

    private final RecommendationDeliveryStore store;
    private final Clock clock;
    private final Duration attributionWindow;

    @Autowired
    public DefaultRecommendationDeliveryService(
            RecommendationDeliveryStore store,
            @Value("${rs.recommend.feedback.attribution-window:24h}") Duration attributionWindow
    ) {
        this(store, Clock.systemUTC(), attributionWindow);
    }

    public DefaultRecommendationDeliveryService(
            RecommendationDeliveryStore store,
            Clock clock,
            Duration attributionWindow
    ) {
        this.store = store;
        this.clock = clock;
        this.attributionWindow = attributionWindow;
    }

    @Override
    public RecommendationDelivery record(
            String requestId,
            RecommendationIdentity identity,
            String scene,
            long preferenceVersion,
            List<RecommendationDeliveryItem> items
    ) {
        Instant now = clock.instant();
        return store.save(new RecommendationDelivery(
                requestId,
                identity,
                scene,
                preferenceVersion,
                items,
                now,
                now.plus(attributionWindow)
        ));
    }

    @Override
    public RecommendationDelivery requireFeedbackTarget(
            RecommendationIdentity identity,
            String requestId,
            String itemId
    ) {
        RecommendationDelivery delivery = store.findByRequestId(requestId)
                .orElseThrow(() -> rejected("DELIVERY_NOT_FOUND", "recommendation delivery does not exist"));
        if (!delivery.identity().equals(identity)) {
            throw rejected("DELIVERY_OWNERSHIP_MISMATCH", "recommendation delivery does not belong to this user");
        }
        if (!delivery.expiresAt().isAfter(clock.instant())) {
            throw rejected("DELIVERY_EXPIRED", "recommendation delivery has expired");
        }
        if (!delivery.containsItem(itemId)) {
            throw rejected("ITEM_NOT_DELIVERED", "item was not part of this recommendation delivery");
        }
        return delivery;
    }

    private RecommendationFeedbackRejectedException rejected(String code, String message) {
        return new RecommendationFeedbackRejectedException(code, message);
    }
}
