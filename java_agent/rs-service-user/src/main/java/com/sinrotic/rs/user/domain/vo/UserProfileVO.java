package com.sinrotic.rs.user.domain.vo;

import java.util.List;

/**
 * User profile used by frontend and internal context endpoints.
 */
public record UserProfileVO(
        String profileUserId,
        String segment,
        int historyCount,
        List<CategoryCountVO> topCategories,
        List<StoreCountVO> topStores,
        List<String> recentItemIds,
        List<String> positiveItemIds,
        List<String> negativeItemIds,
        PriceRangeVO preferredPriceRange,
        String profileSummary
) {
}
