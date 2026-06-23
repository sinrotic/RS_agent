-- RS_agent local/trial PostgreSQL schema.
-- This schema initializes an empty database only; it does not import full or 2y datasets.

CREATE TABLE IF NOT EXISTS products (
    parent_asin TEXT PRIMARY KEY,
    title TEXT,
    main_category TEXT,
    categories JSONB NOT NULL DEFAULT '[]'::jsonb,
    brand TEXT,
    price NUMERIC,
    rating NUMERIC,
    description TEXT,
    features JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS interactions (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    parent_asin TEXT NOT NULL,
    event_type TEXT,
    event_time TIMESTAMPTZ,
    rating NUMERIC,
    label_binary INTEGER,
    split TEXT,
    source TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_interactions_user_time ON interactions (user_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_interactions_item_time ON interactions (parent_asin, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_interactions_split ON interactions (split);
CREATE INDEX IF NOT EXISTS idx_interactions_event_time ON interactions (event_time DESC);

CREATE TABLE IF NOT EXISTS user_sequences (
    user_id TEXT NOT NULL,
    window_name TEXT NOT NULL DEFAULT 'train_2y',
    recent_item_sequence JSONB NOT NULL DEFAULT '[]'::jsonb,
    recent_positive_item_sequence JSONB NOT NULL DEFAULT '[]'::jsonb,
    recent_strong_positive_item_sequence JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, window_name)
);

CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    state JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_user_updated ON agent_sessions (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS feedback_events (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT,
    turn_index INTEGER,
    user_id TEXT,
    parent_asin TEXT,
    feedback_type TEXT NOT NULL,
    feedback_text TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feedback_events_session_turn ON feedback_events (session_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_feedback_events_user_time ON feedback_events (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS recommendation_logs (
    request_id TEXT PRIMARY KEY,
    session_id TEXT,
    user_id TEXT,
    candidate_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    ranked_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    display_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    policy_version TEXT,
    diagnostics JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_recommendation_logs_session_time ON recommendation_logs (session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_recommendation_logs_user_time ON recommendation_logs (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS artifact_registry (
    artifact_id TEXT PRIMARY KEY,
    artifact_type TEXT NOT NULL,
    path TEXT NOT NULL,
    version TEXT,
    sha256 TEXT,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_artifact_registry_type_time ON artifact_registry (artifact_type, created_at DESC);

CREATE TABLE IF NOT EXISTS eval_runs (
    run_id TEXT PRIMARY KEY,
    split TEXT,
    method TEXT,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    artifact_path TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_eval_runs_method_time ON eval_runs (method, created_at DESC);

CREATE TABLE IF NOT EXISTS item_neighbors (
    source TEXT NOT NULL,
    src_item_id TEXT NOT NULL,
    dst_item_id TEXT NOT NULL,
    score NUMERIC NOT NULL DEFAULT 0,
    rank INTEGER,
    category TEXT,
    artifact_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, src_item_id, dst_item_id)
);

CREATE INDEX IF NOT EXISTS idx_item_neighbors_src_rank ON item_neighbors (source, src_item_id, rank, score DESC);
CREATE INDEX IF NOT EXISTS idx_item_neighbors_dst ON item_neighbors (dst_item_id);

CREATE TABLE IF NOT EXISTS usercf_candidates (
    source TEXT NOT NULL,
    user_id TEXT NOT NULL,
    parent_asin TEXT NOT NULL,
    score NUMERIC NOT NULL DEFAULT 0,
    rank INTEGER,
    category TEXT,
    artifact_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, user_id, parent_asin)
);

CREATE INDEX IF NOT EXISTS idx_usercf_candidates_user_rank ON usercf_candidates (source, user_id, rank, score DESC);

CREATE TABLE IF NOT EXISTS popular_candidates (
    scope TEXT NOT NULL DEFAULT 'global',
    bucket TEXT NOT NULL DEFAULT '',
    parent_asin TEXT NOT NULL,
    score NUMERIC NOT NULL DEFAULT 0,
    rank INTEGER,
    category TEXT,
    artifact_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, bucket, parent_asin)
);

CREATE INDEX IF NOT EXISTS idx_popular_candidates_scope_rank ON popular_candidates (scope, bucket, rank, score DESC);

CREATE TABLE IF NOT EXISTS category_candidates (
    bucket TEXT NOT NULL,
    parent_asin TEXT NOT NULL,
    score NUMERIC NOT NULL DEFAULT 0,
    rank INTEGER,
    category TEXT,
    artifact_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (bucket, parent_asin)
);

CREATE INDEX IF NOT EXISTS idx_category_candidates_bucket_rank ON category_candidates (bucket, rank, score DESC);

CREATE TABLE IF NOT EXISTS user_category_profiles (
    user_id TEXT NOT NULL,
    bucket TEXT NOT NULL,
    score NUMERIC NOT NULL DEFAULT 0,
    rank INTEGER,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, bucket)
);

CREATE INDEX IF NOT EXISTS idx_user_category_profiles_user_rank ON user_category_profiles (user_id, rank, score DESC);

CREATE TABLE IF NOT EXISTS candidate_store_manifests (
    manifest_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    artifact_path TEXT,
    row_count BIGINT,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_candidate_store_manifests_source_time ON candidate_store_manifests (source, created_at DESC);
