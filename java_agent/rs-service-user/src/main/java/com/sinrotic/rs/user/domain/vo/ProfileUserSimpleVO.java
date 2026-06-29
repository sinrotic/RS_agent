package com.sinrotic.rs.user.domain.vo;

/**
 * Compact profile-user view for frontend display.
 */
public record ProfileUserSimpleVO(
        String profileUserId,
        String displayName,
        String avatarUrl,
        String segment,
        int historyCount,
        String profileSummary
) {
}
