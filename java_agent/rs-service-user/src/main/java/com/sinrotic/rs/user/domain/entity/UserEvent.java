package com.sinrotic.rs.user.domain.entity;

import java.time.LocalDateTime;

/**
 * Database entity for rs_user_event.
 */
public class UserEvent {
    private String eventId;
    private String profileUserId;
    private String itemId;
    private String eventType;
    private LocalDateTime eventTime;
    private String category;
    private String store;
    private String source;
}
