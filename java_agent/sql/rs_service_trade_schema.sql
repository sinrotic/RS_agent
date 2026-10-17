CREATE TABLE IF NOT EXISTS rs_schema_version (
    component VARCHAR(128) PRIMARY KEY,
    version VARCHAR(128) NOT NULL,
    applied_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS orders (
    order_id BIGINT PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL,
    account_id VARCHAR(64) NOT NULL,
    profile_user_id VARCHAR(64) NULL,
    session_id VARCHAR(64) NULL,
    recommend_request_id VARCHAR(64) NULL,
    status VARCHAR(32) NOT NULL,
    total_amount BIGINT NOT NULL,
    paid_at DATETIME NULL,
    closed_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_orders_request_id (request_id),
    KEY idx_orders_account_created (account_id, created_at DESC),
    KEY idx_orders_status_created (status, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE orders MODIFY COLUMN account_id VARCHAR(64) NOT NULL;

CREATE TABLE IF NOT EXISTS order_items (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    order_id BIGINT NOT NULL,
    item_id VARCHAR(64) NOT NULL,
    sku_id VARCHAR(64) NOT NULL,
    item_title VARCHAR(255) NOT NULL,
    quantity INT NOT NULL,
    unit_price BIGINT NOT NULL,
    total_amount BIGINT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_order_item_sku (order_id, sku_id),
    KEY idx_order_items_sku (sku_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sku_stock (
    sku_id VARCHAR(64) PRIMARY KEY,
    item_id VARCHAR(64) NOT NULL,
    available_stock INT NOT NULL,
    locked_stock INT NOT NULL DEFAULT 0,
    sold_stock INT NOT NULL DEFAULT 0,
    version BIGINT NOT NULL DEFAULT 0,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_sku_stock_item (item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS stock_logs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    request_id VARCHAR(64) NOT NULL,
    order_id BIGINT NOT NULL,
    sku_id VARCHAR(64) NOT NULL,
    quantity INT NOT NULL,
    type VARCHAR(32) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Immutable audit/idempotency log: terminal lifecycle safety for CONFIRM vs RELEASE
    -- is enforced by order state transitions plus conditional stock updates, not by
    -- making this log table mutually exclusive across lifecycle types.
    UNIQUE KEY uk_stock_log_order_sku_type (order_id, sku_id, type),
    UNIQUE KEY uk_stock_log_request (request_id),
    KEY idx_stock_logs_sku_created (sku_id, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS payment_orders (
    payment_id BIGINT PRIMARY KEY,
    order_id BIGINT NOT NULL,
    provider VARCHAR(32) NOT NULL,
    -- Nullable for prepay rows; uk_provider_transaction applies to non-null paid/callback
    -- transaction IDs. Duplicate callback idempotency is enforced by payment_callbacks.
    provider_transaction_id VARCHAR(128) NULL,
    status VARCHAR(32) NOT NULL,
    amount BIGINT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    paid_at DATETIME NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_payment_order_id (order_id),
    UNIQUE KEY uk_provider_transaction (provider, provider_transaction_id),
    KEY idx_payment_status_created (status, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 支付编号由持久数据库序列分配；升级时避开旧进程已经使用的编号。
CREATE TABLE IF NOT EXISTS payment_id (
    payment_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    marker INT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO payment_id (payment_id, marker)
SELECT GREATEST(COALESCE(MAX(payment_id), 0), 1), 1 FROM payment_orders
ON DUPLICATE KEY UPDATE marker = VALUES(marker);

INSERT INTO rs_schema_version (component, version)
VALUES ('rs-service-payment-id', 'database_id_v1')
ON DUPLICATE KEY UPDATE version = VALUES(version), applied_at = CURRENT_TIMESTAMP(6);

CREATE TABLE IF NOT EXISTS payment_callbacks (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    provider VARCHAR(32) NOT NULL,
    provider_transaction_id VARCHAR(128) NOT NULL,
    order_id BIGINT NOT NULL,
    amount BIGINT NOT NULL,
    status VARCHAR(32) NOT NULL,
    payload_hash VARCHAR(128) NOT NULL,
    processed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_payment_callback_provider_tx (provider, provider_transaction_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS consumer_message_log (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    message_id VARCHAR(128) NOT NULL,
    consumer_name VARCHAR(64) NOT NULL,
    processed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_message_consumer (message_id, consumer_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO rs_schema_version (component, version)
VALUES ('rs-service-trade', 'trade_schema_v2_string_account_id')
ON DUPLICATE KEY UPDATE version = VALUES(version), applied_at = CURRENT_TIMESTAMP(6);

CREATE TABLE IF NOT EXISTS payment_order_notifications (
    order_id BIGINT PRIMARY KEY,
    provider VARCHAR(32) NOT NULL,
    provider_transaction_id VARCHAR(128) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    attempts INT NOT NULL DEFAULT 0,
    next_attempt_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    claim_token VARCHAR(64) NULL,
    lease_until DATETIME(6) NULL,
    last_error VARCHAR(255) NULL,
    notified_at DATETIME(6) NULL,
    UNIQUE KEY uk_payment_notify_transaction (provider, provider_transaction_id),
    KEY idx_payment_notify_due (status, next_attempt_at),
    KEY idx_payment_notify_lease (status, lease_until)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 既有已支付订单也补登记；重复迁移保留 DONE/REVIEW 以及当前重试状态。
INSERT INTO payment_order_notifications (order_id, provider, provider_transaction_id)
SELECT order_id, provider, provider_transaction_id FROM payment_orders
WHERE status = 'PAID' AND provider_transaction_id IS NOT NULL
ON DUPLICATE KEY UPDATE order_id = payment_order_notifications.order_id;

INSERT INTO rs_schema_version (component, version)
VALUES ('rs-service-payment-notification', 'payment_notification_v1')
ON DUPLICATE KEY UPDATE version = VALUES(version), applied_at = CURRENT_TIMESTAMP(6);
