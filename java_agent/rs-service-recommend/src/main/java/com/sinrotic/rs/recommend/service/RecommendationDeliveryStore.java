package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.delivery.RecommendationDelivery;

import java.util.Optional;

public interface RecommendationDeliveryStore {

    RecommendationDelivery save(RecommendationDelivery delivery);

    Optional<RecommendationDelivery> findByRequestId(String requestId);

    default java.util.Set<String> recentItemIds(String profileUserId, java.time.Instant since, int limit) {
        return java.util.Set.of();
    }
}
