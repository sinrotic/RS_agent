CREATE KEYSPACE IF NOT EXISTS rs_agent
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

CREATE TABLE IF NOT EXISTS rs_agent.agent_schema_version (
    component text PRIMARY KEY,
    version text,
    applied_at timestamp
);

CREATE TABLE IF NOT EXISTS rs_agent.agent_transcript_entries_by_session (
    session_id text,
    seq bigint,
    turn_no bigint,
    entry_index int,
    request_id text,
    entry_type text,
    role text,
    payload_json text,
    created_at timestamp,
    PRIMARY KEY ((session_id), seq)
) WITH CLUSTERING ORDER BY (seq ASC);

CREATE TABLE IF NOT EXISTS rs_agent.agent_transcript_checkpoints_by_session (
    session_id text,
    checkpoint_seq bigint,
    checkpoint_id text,
    summary_messages_json text,
    preserved_entries_json text,
    source_entry_count int,
    source_token_count int,
    created_at timestamp,
    PRIMARY KEY ((session_id), checkpoint_seq, checkpoint_id)
) WITH CLUSTERING ORDER BY (checkpoint_seq DESC, checkpoint_id ASC);

CREATE TABLE IF NOT EXISTS rs_agent.agent_session_events_by_session (
    session_id text,
    occurred_at timestamp,
    event_id text,
    request_id text,
    event_type text,
    loop_index int,
    tool_call_id text,
    payload_json text,
    payload_ref text,
    compaction_id text,
    PRIMARY KEY ((session_id), occurred_at, event_id)
) WITH CLUSTERING ORDER BY (occurred_at ASC, event_id ASC);

CREATE TABLE IF NOT EXISTS rs_agent.agent_session_snapshots_by_session (
    session_id text,
    snapshot_time timestamp,
    snapshot_id text,
    compaction_id text,
    compact_before_event_id text,
    source_event_count int,
    source_token_count int,
    summary_payload_json text,
    PRIMARY KEY ((session_id), snapshot_time, snapshot_id)
) WITH CLUSTERING ORDER BY (snapshot_time ASC, snapshot_id ASC);

CREATE TABLE IF NOT EXISTS rs_agent.agent_memory_items_by_user (
    tenant_id text,
    profile_user_id text,
    memory_id text,
    memory_type text,
    name text,
    summary text,
    confidence text,
    importance int,
    status text,
    content text,
    source_session_id text,
    metadata_json text,
    version int,
    content_hash text,
    updated_at timestamp,
    PRIMARY KEY ((tenant_id, profile_user_id), memory_id)
);

INSERT INTO rs_agent.agent_schema_version (component, version, applied_at)
VALUES ('agent-session', 'agent_session_v1', toTimestamp(now()));
