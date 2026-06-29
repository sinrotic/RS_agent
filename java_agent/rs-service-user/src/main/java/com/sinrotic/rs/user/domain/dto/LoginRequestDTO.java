package com.sinrotic.rs.user.domain.dto;

/**
 * Request body for username-password login.
 */
public record LoginRequestDTO(
        String username,
        String password
) {
}
