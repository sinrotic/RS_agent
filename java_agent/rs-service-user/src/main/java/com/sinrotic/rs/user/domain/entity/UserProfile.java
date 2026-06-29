package com.sinrotic.rs.user.domain.entity;

import java.time.LocalDateTime;

/**
 * Database entity for rs_user_profile.
 */
public class UserProfile {
    private String profileUserId;
    private String topCategoriesJson;
    private String topStoresJson;
    private String recentItemIdsJson;
    private String positiveItemIdsJson;
    private String negativeItemIdsJson;
    private String preferredPriceRangeJson;
    private String profileSummary;
    private String sourceVersion;
    private LocalDateTime updatedAt;
}
