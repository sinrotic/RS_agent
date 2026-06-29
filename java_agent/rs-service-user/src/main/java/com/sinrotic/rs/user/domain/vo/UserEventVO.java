package com.sinrotic.rs.user.domain.vo;

import java.time.LocalDateTime;

/**
 * Single user behavior event for display and explanation.
 */
public record UserEventVO(
        String itemId,
        String eventType,
        LocalDateTime eventTime,
        String category,
        String store
) {
}
