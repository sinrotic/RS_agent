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

    public String getSessionId() {
        return sessionId;
    }

    public void setSessionId(String sessionId) {
        this.sessionId = sessionId;
    }

    public String getAccountId() {
        return accountId;
    }

    public void setAccountId(String accountId) {
        this.accountId = accountId;
    }

    public String getProfileUserId() {
        return profileUserId;
    }

    public void setProfileUserId(String profileUserId) {
        this.profileUserId = profileUserId;
    }

    public String getEntryScene() {
        return entryScene;
    }

    public void setEntryScene(String entryScene) {
        this.entryScene = entryScene;
    }

    public String getActivePreferencesJson() {
        return activePreferencesJson;
    }

    public void setActivePreferencesJson(String activePreferencesJson) {
        this.activePreferencesJson = activePreferencesJson;
    }

    public String getLastUserQuery() {
        return lastUserQuery;
    }

    public void setLastUserQuery(String lastUserQuery) {
        this.lastUserQuery = lastUserQuery;
    }

    public LocalDateTime getStartedAt() {
        return startedAt;
    }

    public void setStartedAt(LocalDateTime startedAt) {
        this.startedAt = startedAt;
    }

    public LocalDateTime getLastActiveAt() {
        return lastActiveAt;
    }

    public void setLastActiveAt(LocalDateTime lastActiveAt) {
        this.lastActiveAt = lastActiveAt;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }
}
