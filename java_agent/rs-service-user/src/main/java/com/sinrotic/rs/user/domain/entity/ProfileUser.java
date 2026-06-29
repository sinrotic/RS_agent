package com.sinrotic.rs.user.domain.entity;

import java.time.LocalDateTime;

/**
 * Database entity for rs_profile_user.
 */
public class ProfileUser {
    private String profileUserId;
    private String displayName;
    private String avatarUrl;
    private String segment;
    private Integer historyCount;
    private LocalDateTime firstEventTime;
    private LocalDateTime lastEventTime;
    private String status;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
