package com.sinrotic.rs.user.domain.vo;

import java.math.BigDecimal;

/**
 * Preferred price range in a dataset-user profile.
 */
public record PriceRangeVO(
        BigDecimal min,
        BigDecimal max
) {
}
