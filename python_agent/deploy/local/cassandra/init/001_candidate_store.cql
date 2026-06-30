CREATE KEYSPACE IF NOT EXISTS rs_agent
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

CREATE TABLE IF NOT EXISTS rs_agent.item_neighbors_by_seed (
    source text,
    store_version text,
    src_item_id text,
    rank int,
    dst_item_id text,
    score double,
    category text,
    artifact_id text,
    metadata text,
    updated_at timestamp,
    PRIMARY KEY ((source, store_version, src_item_id), rank, dst_item_id)
) WITH CLUSTERING ORDER BY (rank ASC, dst_item_id ASC);

CREATE TABLE IF NOT EXISTS rs_agent.user_candidates_by_user (
    source text,
    store_version text,
    user_id text,
    rank int,
    parent_asin text,
    score double,
    category text,
    artifact_id text,
    metadata text,
    updated_at timestamp,
    PRIMARY KEY ((source, store_version, user_id), rank, parent_asin)
) WITH CLUSTERING ORDER BY (rank ASC, parent_asin ASC);

CREATE TABLE IF NOT EXISTS rs_agent.popular_candidates_by_scope (
    source text,
    store_version text,
    scope text,
    bucket text,
    rank int,
    parent_asin text,
    score double,
    category text,
    artifact_id text,
    metadata text,
    updated_at timestamp,
    PRIMARY KEY ((source, store_version, scope, bucket), rank, parent_asin)
) WITH CLUSTERING ORDER BY (rank ASC, parent_asin ASC);

CREATE TABLE IF NOT EXISTS rs_agent.category_candidates_by_bucket (
    source text,
    store_version text,
    bucket text,
    rank int,
    parent_asin text,
    score double,
    category text,
    artifact_id text,
    metadata text,
    updated_at timestamp,
    PRIMARY KEY ((source, store_version, bucket), rank, parent_asin)
) WITH CLUSTERING ORDER BY (rank ASC, parent_asin ASC);

CREATE TABLE IF NOT EXISTS rs_agent.user_category_buckets_by_user (
    store_version text,
    user_id text,
    rank int,
    bucket text,
    score double,
    metadata text,
    updated_at timestamp,
    PRIMARY KEY ((store_version, user_id), rank, bucket)
) WITH CLUSTERING ORDER BY (rank ASC, bucket ASC);

CREATE TABLE IF NOT EXISTS rs_agent.pool_candidates_by_user (
    store_version text,
    user_id text,
    rank int,
    parent_asin text,
    source text,
    score double,
    category text,
    artifact_id text,
    metadata text,
    updated_at timestamp,
    PRIMARY KEY ((store_version, user_id), rank, parent_asin)
) WITH CLUSTERING ORDER BY (rank ASC, parent_asin ASC);

CREATE TABLE IF NOT EXISTS rs_agent.candidate_store_manifests (
    store_name text,
    store_version text,
    source text,
    artifact_path text,
    artifact_id text,
    row_count bigint,
    imported_at timestamp,
    status text,
    metrics text,
    metadata text,
    PRIMARY KEY ((store_name), store_version, source)
) WITH CLUSTERING ORDER BY (store_version DESC, source ASC);
