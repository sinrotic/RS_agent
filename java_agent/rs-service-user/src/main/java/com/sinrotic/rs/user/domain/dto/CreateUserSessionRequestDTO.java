package com.sinrotic.rs.user.domain.dto;

/**
 * Request body for creating a user session from the current authenticated account.
 */
public record CreateUserSessionRequestDTO(
        String entryScene
) {
}
