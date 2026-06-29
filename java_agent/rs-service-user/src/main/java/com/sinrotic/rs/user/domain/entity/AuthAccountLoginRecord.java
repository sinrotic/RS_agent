package com.sinrotic.rs.user.domain.entity;

/**
 * Minimal account fields required by username-password login.
 */
public record AuthAccountLoginRecord(
        String accountId,
        String username,
        String passwordHash,
        String nickname,
        String status,
        Long tokenVersion
) {
}
