package com.sinrotic.rs.recommend.domain.preference;

import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import java.time.Instant;

public record ActiveRecommendationSession(RecommendationIdentity identity, Instant expiresAt) { }
