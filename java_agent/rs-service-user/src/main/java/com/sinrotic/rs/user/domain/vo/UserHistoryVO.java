package com.sinrotic.rs.user.domain.vo;

import java.util.List;

/**
 * User behavior history response.
 */
public record UserHistoryVO(
        String profileUserId,
        List<UserEventVO> events
) {
}
