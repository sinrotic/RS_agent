-- Amazon Reviews 2023 base raw tables for local/trial MySQL.
-- This schema stores the standardized JSONL facts from data/processed/amazon_2023_base.
-- It intentionally keeps raw/base tables separate from serving tables such as products/interactions.

CREATE TABLE IF NOT EXISTS amazon_items_base (
    dataset VARCHAR(128) NOT NULL,
    category VARCHAR(128) NOT NULL,
    parent_asin VARCHAR(64) NOT NULL,

    title TEXT,
    main_category VARCHAR(255),
    categories JSON NOT NULL DEFAULT (JSON_ARRAY()),
    description JSON NOT NULL DEFAULT (JSON_ARRAY()),
    features JSON NOT NULL DEFAULT (JSON_ARRAY()),
    images JSON NOT NULL DEFAULT (JSON_ARRAY()),

    price DECIMAL(18, 4),
    price_raw TEXT,
    average_rating DECIMAL(6, 3),
    rating_number BIGINT,

    store VARCHAR(255),
    details JSON,
    bought_together JSON,

    source_file TEXT,
    source_line BIGINT,
    imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (category, parent_asin),
    INDEX idx_amazon_items_parent_asin (parent_asin),
    INDEX idx_amazon_items_category (category),
    INDEX idx_amazon_items_store (store),
    INDEX idx_amazon_items_main_category (main_category),
    INDEX idx_amazon_items_rating_number (rating_number)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS amazon_reviews_base (
    review_key CHAR(64) PRIMARY KEY,

    dataset VARCHAR(128) NOT NULL,
    category VARCHAR(128) NOT NULL,

    user_id VARCHAR(128) NOT NULL,
    parent_asin VARCHAR(64) NOT NULL,
    asin VARCHAR(64),

    rating DECIMAL(6, 3),
    text_len INT,
    has_review_title BOOLEAN NOT NULL DEFAULT FALSE,
    has_review_text BOOLEAN NOT NULL DEFAULT FALSE,
    review_text_ref CHAR(64),

    timestamp_ms BIGINT,
    event_time DATETIME,

    verified_purchase BOOLEAN,
    helpful_vote INT,

    source_file TEXT,
    source_line BIGINT,
    imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_amazon_reviews_user_time (user_id, event_time DESC),
    INDEX idx_amazon_reviews_item_time (parent_asin, event_time DESC),
    INDEX idx_amazon_reviews_category_time (category, event_time DESC),
    INDEX idx_amazon_reviews_rating (rating),
    INDEX idx_amazon_reviews_verified (verified_purchase),
    INDEX idx_amazon_reviews_user_item (user_id, parent_asin),
    INDEX idx_amazon_reviews_source_line (category, source_line)
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
