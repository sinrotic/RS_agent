package com.sinrotic.rs.user.domain.vo;

/**
 * Response object returned after register, login, or token refresh operations.
 */
public record AuthTokenVO(
        String accountId,
        String username,
        String nickname,
        String profileUserId,
        String profileSummary,
        String accessToken,
        String refreshToken,
        long expiresIn
) {
}
