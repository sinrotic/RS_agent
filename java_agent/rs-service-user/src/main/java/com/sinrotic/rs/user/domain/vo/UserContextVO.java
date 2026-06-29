package com.sinrotic.rs.user.domain.vo;

import java.util.List;

/**
 * Internal account context consumed by recommendation and Agent services.
 */
public record UserContextVO(
        String accountId,
        String profileUserId,
        String nickname,
        String segment,
        List<String> historyItemIds,
        List<String> recentItemIds,
        List<String> topCategories,
        List<String> topStores,
        PriceRangeVO preferredPriceRange,
        String profileSummary,
        String sourceVersion
) {
}
