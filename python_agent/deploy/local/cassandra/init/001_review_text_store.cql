CREATE KEYSPACE IF NOT EXISTS rs_agent_review_text
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

CREATE TABLE IF NOT EXISTS rs_agent_review_text.review_text_by_key (
    review_key text PRIMARY KEY,
    category text,
    user_id text,
    parent_asin text,
    asin text,
    timestamp_ms bigint,
    event_time timestamp,
    rating double,
    review_title text,
    review_text text,
    text_len int,
    verified_purchase boolean,
    helpful_vote int,
    source_file text,
    source_line int,
    imported_at timestamp
);

CREATE TABLE IF NOT EXISTS rs_agent_review_text.review_text_by_item (
    category text,
    parent_asin text,
    event_time timestamp,
    review_key text,
    user_id text,
    asin text,
    rating double,
    text_len int,
    verified_purchase boolean,
    helpful_vote int,
    PRIMARY KEY ((category, parent_asin), event_time, review_key)
) WITH CLUSTERING ORDER BY (event_time DESC, review_key ASC);

CREATE TABLE IF NOT EXISTS rs_agent_review_text.review_text_by_user (
    user_id text,
    event_time timestamp,
    review_key text,
    category text,
    parent_asin text,
    asin text,
    rating double,
    text_len int,
    verified_purchase boolean,
    helpful_vote int,
    PRIMARY KEY ((user_id), event_time, review_key)
) WITH CLUSTERING ORDER BY (event_time DESC, review_key ASC);

CREATE TABLE IF NOT EXISTS rs_agent_review_text.review_text_import_manifests (
    import_id text PRIMARY KEY,
    input_paths text,
    row_count bigint,
    imported_at timestamp,
    status text,
    metrics text
);
