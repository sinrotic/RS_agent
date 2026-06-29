-- RS_agent local/trial MySQL schema.
-- This schema initializes an empty database only; it does not import full or 2y datasets.
-- Merchant / inventory service-domain tables are intentionally deferred to later migrations.

CREATE TABLE IF NOT EXISTS products (
    parent_asin VARCHAR(64) PRIMARY KEY,
    title TEXT,
    main_category VARCHAR(255),
    categories JSON NOT NULL DEFAULT (JSON_ARRAY()),
    brand VARCHAR(255),
    price DECIMAL(18, 4),
    rating DECIMAL(6, 3),
    description TEXT,
    features JSON NOT NULL DEFAULT (JSON_ARRAY()),
    metadata JSON NOT NULL DEFAULT (JSON_OBJECT()),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS interactions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    parent_asin VARCHAR(64) NOT NULL,
    event_type VARCHAR(64),
    event_time TIMESTAMP NULL,
    rating DECIMAL(6, 3),
    label_binary INT,
    split VARCHAR(32),
    source VARCHAR(128),
    metadata JSON NOT NULL DEFAULT (JSON_OBJECT()),
    INDEX idx_interactions_user_time (user_id, event_time DESC),
    INDEX idx_interactions_item_time (parent_asin, event_time DESC),
    INDEX idx_interactions_split (split),
    INDEX idx_interactions_event_time (event_time DESC)
);

CREATE TABLE IF NOT EXISTS user_sequences (
    user_id VARCHAR(128) NOT NULL,
    window_name VARCHAR(64) NOT NULL DEFAULT 'train_2y',
    recent_item_sequence JSON NOT NULL DEFAULT (JSON_ARRAY()),
    recent_positive_item_sequence JSON NOT NULL DEFAULT (JSON_ARRAY()),
    recent_strong_positive_item_sequence JSON NOT NULL DEFAULT (JSON_ARRAY()),
    metadata JSON NOT NULL DEFAULT (JSON_OBJECT()),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, window_name)
);

CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id VARCHAR(128) PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    state JSON NOT NULL DEFAULT (JSON_OBJECT()),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_agent_sessions_user_updated (user_id, updated_at DESC)
);

CREATE TABLE IF NOT EXISTS feedback_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(128),
    turn_index INT,
    user_id VARCHAR(128),
    parent_asin VARCHAR(64),
    feedback_type VARCHAR(64) NOT NULL,
    feedback_text TEXT,
    payload JSON NOT NULL DEFAULT (JSON_OBJECT()),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_feedback_events_session_turn (session_id, turn_index),
    INDEX idx_feedback_events_user_time (user_id, created_at DESC)
);

CREATE TABLE IF NOT EXISTS recommendation_logs (
    request_id VARCHAR(128) PRIMARY KEY,
    session_id VARCHAR(128),
    user_id VARCHAR(128),
    candidate_items JSON NOT NULL DEFAULT (JSON_ARRAY()),
    ranked_items JSON NOT NULL DEFAULT (JSON_ARRAY()),
    display_items JSON NOT NULL DEFAULT (JSON_ARRAY()),
    policy_version VARCHAR(128),
    diagnostics JSON NOT NULL DEFAULT (JSON_OBJECT()),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_recommendation_logs_session_time (session_id, created_at DESC),
    INDEX idx_recommendation_logs_user_time (user_id, created_at DESC)
);

CREATE TABLE IF NOT EXISTS artifact_registry (
    artifact_id VARCHAR(255) PRIMARY KEY,
    artifact_type VARCHAR(128) NOT NULL,
    path TEXT NOT NULL,
    version VARCHAR(128),
    sha256 VARCHAR(128),
    metrics JSON NOT NULL DEFAULT (JSON_OBJECT()),
    metadata JSON NOT NULL DEFAULT (JSON_OBJECT()),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_artifact_registry_type_time (artifact_type, created_at DESC)
);

CREATE TABLE IF NOT EXISTS eval_runs (
    run_id VARCHAR(128) PRIMARY KEY,
    split VARCHAR(32),
    method VARCHAR(128),
    metrics JSON NOT NULL DEFAULT (JSON_OBJECT()),
    artifact_path TEXT,
    metadata JSON NOT NULL DEFAULT (JSON_OBJECT()),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_eval_runs_method_time (method, created_at DESC)
);

CREATE TABLE IF NOT EXISTS item_neighbors (
    source VARCHAR(128) NOT NULL,
    src_item_id VARCHAR(64) NOT NULL,
    dst_item_id VARCHAR(64) NOT NULL,
    score DOUBLE NOT NULL DEFAULT 0,
    `rank` INT,
    category VARCHAR(255),
    artifact_id VARCHAR(255),
    metadata JSON NOT NULL DEFAULT (JSON_OBJECT()),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (source, src_item_id, dst_item_id),
    INDEX idx_item_neighbors_src_rank (source, src_item_id, `rank`, score DESC),
    INDEX idx_item_neighbors_dst (dst_item_id)
);

CREATE TABLE IF NOT EXISTS usercf_candidates (
    source VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    parent_asin VARCHAR(64) NOT NULL,
    score DOUBLE NOT NULL DEFAULT 0,
    `rank` INT,
    category VARCHAR(255),
    artifact_id VARCHAR(255),
    metadata JSON NOT NULL DEFAULT (JSON_OBJECT()),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (source, user_id, parent_asin),
    INDEX idx_usercf_candidates_user_rank (source, user_id, `rank`, score DESC)
);

CREATE TABLE IF NOT EXISTS popular_candidates (
    scope VARCHAR(128) NOT NULL DEFAULT 'global',
    bucket VARCHAR(255) NOT NULL DEFAULT '',
    parent_asin VARCHAR(64) NOT NULL,
    score DOUBLE NOT NULL DEFAULT 0,
    `rank` INT,
    category VARCHAR(255),
    artifact_id VARCHAR(255),
    metadata JSON NOT NULL DEFAULT (JSON_OBJECT()),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (scope, bucket, parent_asin),
    INDEX idx_popular_candidates_scope_rank (scope, bucket, `rank`, score DESC)
);

CREATE TABLE IF NOT EXISTS category_candidates (
    bucket VARCHAR(255) NOT NULL,
    parent_asin VARCHAR(64) NOT NULL,
    score DOUBLE NOT NULL DEFAULT 0,
    `rank` INT,
    category VARCHAR(255),
    artifact_id VARCHAR(255),
    metadata JSON NOT NULL DEFAULT (JSON_OBJECT()),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (bucket, parent_asin),
    INDEX idx_category_candidates_bucket_rank (bucket, `rank`, score DESC)
);

CREATE TABLE IF NOT EXISTS user_category_profiles (
    user_id VARCHAR(128) NOT NULL,
    bucket VARCHAR(255) NOT NULL,
    score DOUBLE NOT NULL DEFAULT 0,
    `rank` INT,
    metadata JSON NOT NULL DEFAULT (JSON_OBJECT()),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, bucket),
    INDEX idx_user_category_profiles_user_rank (user_id, `rank`, score DESC)
);

CREATE TABLE IF NOT EXISTS pool_candidates (
    user_id VARCHAR(128) NOT NULL,
    source VARCHAR(128) NOT NULL,
    parent_asin VARCHAR(64) NOT NULL,
    score DOUBLE NOT NULL DEFAULT 0,
    `rank` INT,
    category VARCHAR(255),
    artifact_id VARCHAR(255),
    metadata JSON NOT NULL DEFAULT (JSON_OBJECT()),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, source, parent_asin),
    INDEX idx_pool_candidates_user_rank (user_id, `rank`, score DESC)
);

CREATE TABLE IF NOT EXISTS candidate_store_manifests (
    manifest_id VARCHAR(255) PRIMARY KEY,
    source VARCHAR(128) NOT NULL,
    artifact_path TEXT,
    row_count BIGINT,
    metrics JSON NOT NULL DEFAULT (JSON_OBJECT()),
    metadata JSON NOT NULL DEFAULT (JSON_OBJECT()),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_candidate_store_manifests_source_time (source, created_at DESC)
);

CREATE TABLE IF NOT EXISTS users (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    role VARCHAR(50) DEFAULT 'user',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_users_username (username)
);
