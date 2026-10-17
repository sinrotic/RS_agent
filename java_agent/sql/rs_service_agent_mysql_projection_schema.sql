CREATE TABLE IF NOT EXISTS agent_schema_version (
    component VARCHAR(128) NOT NULL,
    version VARCHAR(128) NOT NULL,
    applied_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (component)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL DEFAULT '',
    last_request_id VARCHAR(128) NOT NULL DEFAULT '',
    last_seq BIGINT NULL,
    last_entry_type VARCHAR(64) NOT NULL DEFAULT '',
    last_entry_at DATETIME(6) NULL,
    last_event_type VARCHAR(64) NOT NULL DEFAULT '',
    last_loop_index INT NOT NULL DEFAULT 0,
    last_event_at DATETIME(6) NULL,
    latest_checkpoint_id VARCHAR(128) NOT NULL DEFAULT '',
    checkpoint_seq BIGINT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (session_id),
    KEY idx_agent_sessions_user_updated (user_id, updated_at),
    KEY idx_agent_sessions_checkpoint_seq (checkpoint_seq)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS agent_turns (
    session_id VARCHAR(128) NOT NULL,
    turn_no BIGINT NOT NULL,
    first_seq BIGINT NOT NULL,
    last_seq BIGINT NOT NULL,
    request_id VARCHAR(128) NOT NULL DEFAULT '',
    last_entry_type VARCHAR(64) NOT NULL DEFAULT '',
    last_role VARCHAR(32) NOT NULL DEFAULT '',
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (session_id, turn_no),
    KEY idx_agent_turns_request (request_id),
    KEY idx_agent_turns_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS agent_tool_calls (
    session_id VARCHAR(128) NOT NULL,
    tool_call_id VARCHAR(128) NOT NULL,
    request_id VARCHAR(128) NOT NULL DEFAULT '',
    tool_name VARCHAR(128) NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT '',
    error_code VARCHAR(128) NOT NULL DEFAULT '',
    last_event_type VARCHAR(64) NOT NULL DEFAULT '',
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (session_id, tool_call_id),
    KEY idx_agent_tool_calls_tool_status (tool_name, status, updated_at),
    KEY idx_agent_tool_calls_request (request_id),
    KEY idx_agent_tool_calls_error (error_code, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS agent_checkpoints (
    session_id VARCHAR(128) NOT NULL,
    checkpoint_id VARCHAR(128) NOT NULL,
    checkpoint_seq BIGINT NOT NULL,
    summary_messages_json JSON NOT NULL,
    preserved_entries_json JSON NOT NULL,
    source_entry_count INT NOT NULL,
    source_token_count INT NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (session_id, checkpoint_id),
    KEY idx_agent_checkpoints_session_seq (session_id, checkpoint_seq)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS agent_memory_indexes (
    tenant_id VARCHAR(128) NOT NULL,
    profile_user_id VARCHAR(128) NOT NULL,
    index_content TEXT NOT NULL,
    version BIGINT NOT NULL DEFAULT 0,
    memory_count INT NOT NULL DEFAULT 0,
    content_hash VARCHAR(128) NOT NULL DEFAULT '',
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (tenant_id, profile_user_id),
    KEY idx_agent_memory_indexes_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO agent_schema_version (component, version)
VALUES ('agent-session', 'agent_session_v1')
ON DUPLICATE KEY UPDATE version = VALUES(version), applied_at = CURRENT_TIMESTAMP(6);
