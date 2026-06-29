-- rs-service-user schema.
-- profile_user_id stores the dataset/review user_id selected from imported 2y review data.

CREATE TABLE IF NOT EXISTS rs_auth_account (
    account_id VARCHAR(64) PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    nickname VARCHAR(100),
    avatar_url TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    token_version BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_rs_auth_account_username (username),
    INDEX idx_rs_auth_account_status (status)
);

CREATE TABLE IF NOT EXISTS rs_account_profile_binding (
    binding_id VARCHAR(64) PRIMARY KEY,
    account_id VARCHAR(64) NOT NULL,
    profile_user_id VARCHAR(128) NOT NULL,
    binding_strategy VARCHAR(32) NOT NULL DEFAULT 'random',
    segment VARCHAR(64),
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_rs_account_profile_active (account_id, status),
    INDEX idx_rs_account_profile_user (profile_user_id),
    CONSTRAINT fk_rs_account_profile_account
        FOREIGN KEY (account_id) REFERENCES rs_auth_account(account_id)
);

CREATE TABLE IF NOT EXISTS rs_auth_session (
    session_id VARCHAR(64) PRIMARY KEY,
    account_id VARCHAR(64) NOT NULL,
    profile_user_id VARCHAR(128) NOT NULL,
    access_token_hash CHAR(64) NOT NULL,
    refresh_token_hash CHAR(64) NOT NULL,
    access_expires_at TIMESTAMP NOT NULL,
    refresh_expires_at TIMESTAMP NOT NULL,
    revoked_at TIMESTAMP NULL,
    user_agent TEXT,
    ip VARCHAR(64),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_rs_auth_session_access_token (access_token_hash),
    UNIQUE KEY uk_rs_auth_session_refresh_token (refresh_token_hash),
    INDEX idx_rs_auth_session_account_updated (account_id, updated_at DESC),
    INDEX idx_rs_auth_session_refresh_expires (refresh_expires_at),
    CONSTRAINT fk_rs_auth_session_account
        FOREIGN KEY (account_id) REFERENCES rs_auth_account(account_id)
);
