package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.delivery.RecommendationDelivery;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationDeliveryItem;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;

import java.util.List;

public interface RecommendationDeliveryService {

    RecommendationDelivery record(
            String requestId,
            RecommendationIdentity identity,
            String scene,
            long preferenceVersion,
            List<RecommendationDeliveryItem> items
    );

    RecommendationDelivery requireFeedbackTarget(
            RecommendationIdentity identity,
            String requestId,
            String itemId
    );
}
