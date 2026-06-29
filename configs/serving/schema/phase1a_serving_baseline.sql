-- Phase 1a SQL DDL baseline for future canonical serving facts.
-- This file is a schema contract only: no Alembic; MySQL-only structured store baseline in Phase 1a.

CREATE TABLE serving_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    last_request_id TEXT,
    operation_id TEXT NOT NULL
);

CREATE TABLE serving_turns (
    turn_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES serving_sessions(session_id),
    turn_index INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    user_message_public TEXT NOT NULL,
    assistant_message_public TEXT NOT NULL,
    display_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    operation_id TEXT NOT NULL,
    UNIQUE(session_id, turn_index)
);

CREATE TABLE serving_feedback_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES serving_sessions(session_id),
    turn_id TEXT REFERENCES serving_turns(turn_id),
    turn_index INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    item_id TEXT,
    comment_public TEXT,
    comment_truncated BOOLEAN NOT NULL DEFAULT FALSE,
    comment_redacted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    operation_id TEXT NOT NULL
);

CREATE TABLE serving_request_summaries (
    request_id TEXT PRIMARY KEY,
    endpoint TEXT NOT NULL,
    user_id TEXT,
    item_count INTEGER,
    candidate_count INTEGER,
    fallback_used BOOLEAN,
    public_summary_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    operation_id TEXT
);

CREATE TABLE outbox_events (
    event_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ
);

CREATE TABLE recommendation_requests (
    request_id TEXT PRIMARY KEY,
    user_id TEXT,
    endpoint TEXT NOT NULL,
    http_request_id TEXT,
    artifact_manifest_id TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    operation_id TEXT
);

CREATE TABLE recommendation_results (
    result_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES recommendation_requests(request_id),
    item_id TEXT NOT NULL,
    rank_index INTEGER NOT NULL,
    public_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE recall_traces (
    trace_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES recommendation_requests(request_id),
    recall_backend TEXT NOT NULL,
    candidate_count INTEGER NOT NULL,
    public_summary_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE artifact_registry (
    artifact_manifest_id TEXT PRIMARY KEY,
    artifact_type TEXT NOT NULL,
    artifact_uri TEXT NOT NULL,
    route_name TEXT,
    checksum TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE rag_evidence (
    evidence_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    public_evidence_json JSONB NOT NULL,
    artifact_manifest_id TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE task_runs (
    task_run_id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL,
    input_ref TEXT,
    output_ref TEXT,
    error_public TEXT,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ
);

CREATE INDEX idx_serving_turns_session_id ON serving_turns(session_id);
CREATE INDEX idx_serving_feedback_events_session_id ON serving_feedback_events(session_id);
CREATE INDEX idx_serving_request_summaries_endpoint_created_at ON serving_request_summaries(endpoint, created_at);
CREATE INDEX idx_outbox_events_published_at ON outbox_events(published_at);
CREATE INDEX idx_recommendation_results_request_rank ON recommendation_results(request_id, rank_index);
CREATE INDEX idx_recall_traces_request_id ON recall_traces(request_id);
CREATE INDEX idx_rag_evidence_request_item ON rag_evidence(request_id, item_id);
CREATE INDEX idx_task_runs_status_started_at ON task_runs(status, started_at);
