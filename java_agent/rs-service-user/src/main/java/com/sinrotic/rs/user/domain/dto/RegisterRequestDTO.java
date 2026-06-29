package com.sinrotic.rs.user.domain.dto;

/**
 * Request body for registering a real account and binding it to a profile user.
 */
public record RegisterRequestDTO(
        String username,
        String password,
        String nickname,
        String bindStrategy,
        String segment,
        String profileUserId
) {
}
