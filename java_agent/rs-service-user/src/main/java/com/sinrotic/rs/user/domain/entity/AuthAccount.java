package com.sinrotic.rs.user.domain.entity;

import java.time.LocalDateTime;

/**
 * Database entity for rs_auth_account.
 */
public class AuthAccount {
    private String accountId;
    private String username;
    private String passwordHash;
    private String nickname;
    private String avatarUrl;
    private String status;
    private Integer tokenVersion;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
