package com.sinrotic.rs.user.domain.vo;

import com.fasterxml.jackson.annotation.JsonIgnore;

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
        @JsonIgnore String refreshToken,
        long expiresIn
) {
}
