package com.sinrotic.rs.user.domain.dto;

/**
 * Request body for refresh token rotation.
 */
public record RefreshTokenRequestDTO(
        String refreshToken
) {
}
