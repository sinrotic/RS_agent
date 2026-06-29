package com.sinrotic.rs.user.domain.entity;

import java.time.LocalDateTime;

/**
 * Database entity for rs_account_profile_binding.
 */
public class AccountProfileBinding {
    private String bindingId;
    private String accountId;
    private String profileUserId;
    private String bindingStrategy;
    private String segment;
    private String status;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
