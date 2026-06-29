package com.sinrotic.rs.user.domain.entity;

import java.time.LocalDateTime;

/**
 * Database entity for rs_user_session.
 */
public class UserSession {
    private String sessionId;
    private String accountId;
    private String profileUserId;
    private String entryScene;
    private String activePreferencesJson;
    private String lastUserQuery;
    private LocalDateTime startedAt;
    private LocalDateTime lastActiveAt;
    private String status;
}
