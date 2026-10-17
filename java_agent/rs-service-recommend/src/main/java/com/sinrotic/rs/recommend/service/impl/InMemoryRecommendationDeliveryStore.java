package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.delivery.RecommendationDelivery;
import com.sinrotic.rs.recommend.service.RecommendationDeliveryStore;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

@Component
@ConditionalOnProperty(name = "rs.recommend.feedback.persistence", havingValue = "memory", matchIfMissing = true)
public class InMemoryRecommendationDeliveryStore implements RecommendationDeliveryStore {

    private final ConcurrentMap<String, RecommendationDelivery> deliveries = new ConcurrentHashMap<>();

    @Override
    public RecommendationDelivery save(RecommendationDelivery delivery) {
        RecommendationDelivery existing = deliveries.putIfAbsent(delivery.requestId(), delivery);
        if (existing != null && !existing.equals(delivery)) {
            throw new IllegalStateException("recommendation delivery already exists: " + delivery.requestId());
        }
        return existing == null ? delivery : existing;
    }

    @Override
    public Optional<RecommendationDelivery> findByRequestId(String requestId) {
        return Optional.ofNullable(deliveries.get(requestId));
    }

    @Override
    public java.util.Set<String> recentItemIds(String profileUserId, java.time.Instant since, int limit) {
        return deliveries.values().stream().filter(delivery -> delivery.identity().profileUserId().equals(profileUserId)
                        && delivery.createdAt().isAfter(since))
                .sorted(java.util.Comparator.comparing(RecommendationDelivery::createdAt).reversed())
                .flatMap(delivery -> delivery.items().stream()).map(item -> item.itemId()).distinct().limit(limit)
                .collect(java.util.stream.Collectors.toSet());
    }
}
