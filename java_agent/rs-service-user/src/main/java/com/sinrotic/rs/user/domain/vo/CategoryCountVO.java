package com.sinrotic.rs.user.domain.vo;

/**
 * Category count in a dataset-user profile.
 */
public record CategoryCountVO(
        String category,
        int count
) {
}
