package com.sinrotic.rs.recommend.domain.delivery;

public record RecommendationIdentity(
        String accountId,
        String profileUserId,
        String sessionId
) {

    public RecommendationIdentity {
        if (isBlank(accountId) || isBlank(profileUserId) || isBlank(sessionId)) {
            throw new IllegalArgumentException("accountId, profileUserId and sessionId are required");
        }
    }

    private static boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
