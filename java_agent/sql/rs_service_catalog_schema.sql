-- rs-service-catalog schema.
-- This is a stable product catalog projection for Java services.
-- Raw dataset tables such as metadata / amazon_items_base should be synchronized into this table.

CREATE TABLE IF NOT EXISTS rs_catalog_item (
    item_id VARCHAR(128) PRIMARY KEY,
    source_item_id VARCHAR(128) NOT NULL,
    title TEXT NOT NULL,
    category VARCHAR(255),
    category_path TEXT,
    brand VARCHAR(255),
    store_name VARCHAR(255),
    price DECIMAL(12, 2),
    image_url TEXT,
    summary TEXT,
    description TEXT,
    attributes_json JSON,
    raw_metadata_json JSON,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_rs_catalog_source_item (source_item_id),
    INDEX idx_rs_catalog_category (category),
    INDEX idx_rs_catalog_store_name (store_name),
    INDEX idx_rs_catalog_status_updated (status, updated_at DESC)
);

CREATE TABLE IF NOT EXISTS rs_catalog_projection_run (
    run_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    status VARCHAR(16) NOT NULL,
    last_source_item_id VARCHAR(128) NOT NULL DEFAULT '',
    processed_rows BIGINT NOT NULL DEFAULT 0,
    source_rows BIGINT NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    INDEX idx_rs_catalog_projection_status_updated (status, updated_at DESC)
);

-- Suggested first import strategy:
-- INSERT INTO rs_catalog_item (
--     item_id, source_item_id, title, category, category_path, brand, store_name,
--     price, image_url, summary, description, attributes_json, raw_metadata_json
-- )
-- SELECT
--     parent_asin,
--     parent_asin,
--     title,
--     main_category,
--     categories,
--     brand,
--     store,
--     price,
--     images,
--     title,
--     description,
--     details,
--     raw_json
-- FROM amazon_items_base
-- WHERE parent_asin IS NOT NULL AND parent_asin != ''
-- ON DUPLICATE KEY UPDATE
--     title = VALUES(title),
--     category = VALUES(category),
--     category_path = VALUES(category_path),
--     brand = VALUES(brand),
--     store_name = VALUES(store_name),
--     price = VALUES(price),
--     image_url = VALUES(image_url),
--     summary = VALUES(summary),
--     description = VALUES(description),
--     attributes_json = VALUES(attributes_json),
--     raw_metadata_json = VALUES(raw_metadata_json),
--     updated_at = CURRENT_TIMESTAMP;
