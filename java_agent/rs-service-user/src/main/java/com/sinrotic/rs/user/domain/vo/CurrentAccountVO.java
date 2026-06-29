package com.sinrotic.rs.user.domain.vo;

/**
 * Response object for the current authenticated account.
 */
public record CurrentAccountVO(
        String accountId,
        String username,
        String nickname,
        String profileUserId,
        UserProfileVO profile
) {
}
