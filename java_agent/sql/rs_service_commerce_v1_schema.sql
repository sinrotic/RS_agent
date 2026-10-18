-- 金额统一为 USD 的最小单位（美分）；DATETIME 字段使用 UTC。
-- 只新增表，可重复执行；不改变已有订单和库存数据。
CREATE TABLE IF NOT EXISTS checkout_payment_fact (
    order_id BIGINT PRIMARY KEY, provider VARCHAR(32) NOT NULL, transaction_id VARCHAR(128) NOT NULL,
    amount BIGINT NOT NULL, mock BOOLEAN NOT NULL, created_at DATETIME(6) NOT NULL,
    UNIQUE KEY uk_checkout_payment_transaction(provider,transaction_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS checkout_refund (
    refund_id VARCHAR(36) PRIMARY KEY, order_id BIGINT NOT NULL UNIQUE, account_id VARCHAR(64) NOT NULL,
    amount BIGINT NOT NULL, reason VARCHAR(255) NOT NULL, scenario VARCHAR(32) NOT NULL,
    status VARCHAR(24) NOT NULL, phase VARCHAR(24) NOT NULL, attempts INT NOT NULL DEFAULT 0,
    next_attempt_at DATETIME(6) NOT NULL, last_error VARCHAR(255), created_at DATETIME(6) NOT NULL,
    KEY idx_refund_due(status,next_attempt_at), KEY idx_refund_account(account_id,order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS checkout_refund_request (
    account_id VARCHAR(64) NOT NULL, request_id VARCHAR(64) NOT NULL, order_id BIGINT NOT NULL,
    refund_id VARCHAR(36) NOT NULL, PRIMARY KEY(account_id,request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS payment_refund (
    refund_id VARCHAR(36) PRIMARY KEY, order_id BIGINT NOT NULL UNIQUE, amount BIGINT NOT NULL,
    provider VARCHAR(32) NOT NULL, transaction_id VARCHAR(128) NOT NULL, status VARCHAR(24) NOT NULL,
    scenario VARCHAR(32) NOT NULL, attempts INT NOT NULL DEFAULT 0, created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS payment_refund_guard (order_id BIGINT PRIMARY KEY)
ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS payment_refund_callback (
    refund_id VARCHAR(36) NOT NULL, transaction_id VARCHAR(128) NOT NULL, status VARCHAR(24) NOT NULL,
    amount BIGINT NOT NULL, created_at DATETIME(6) NOT NULL, PRIMARY KEY(refund_id,transaction_id,status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS commerce_order_event (
    event_id VARCHAR(64) PRIMARY KEY, order_id BIGINT NOT NULL, event_type VARCHAR(24) NOT NULL,
    payload TEXT NOT NULL, created_at DATETIME(6) NOT NULL, UNIQUE KEY uk_trade_order_event(order_id,event_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS commerce_event_delivery (
    event_id VARCHAR(64) NOT NULL, target VARCHAR(24) NOT NULL, status VARCHAR(24) NOT NULL DEFAULT 'PENDING',
    attempts INT NOT NULL DEFAULT 0, next_attempt_at DATETIME(6) NOT NULL, last_error VARCHAR(255),
    PRIMARY KEY(event_id,target), KEY idx_trade_delivery(status,next_attempt_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS recommendation_trade_event (
    event_id VARCHAR(64) PRIMARY KEY, order_id BIGINT NOT NULL, event_version INT NOT NULL,
    fingerprint VARCHAR(64) NOT NULL, mock BOOLEAN NOT NULL, created_at DATETIME(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS recommendation_purchase_signal (
    order_id BIGINT PRIMARY KEY, account_id VARCHAR(64) NOT NULL, profile_user_id VARCHAR(64),
    item_id VARCHAR(64) NOT NULL, quantity INT NOT NULL, amount BIGINT NOT NULL, provider VARCHAR(32) NOT NULL,
    mock BOOLEAN NOT NULL, event_version INT NOT NULL, active BOOLEAN NOT NULL, created_at DATETIME(6) NOT NULL,
    KEY idx_purchase_profile(profile_user_id,item_id,active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS inventory_stock_baseline (
    sku_id VARCHAR(64) PRIMARY KEY, opening_total BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS inventory_adjustment (
    request_id VARCHAR(64) PRIMARY KEY, sku_id VARCHAR(64) NOT NULL, movement_type VARCHAR(24) NOT NULL,
    input_quantity INT NOT NULL, expected_version BIGINT, delta_quantity INT NOT NULL,
    operator_id VARCHAR(64) NOT NULL, reason VARCHAR(255) NOT NULL, created_at DATETIME(6) NOT NULL,
    KEY idx_adjustment_sku(sku_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS inventory_reconciliation (
    case_id VARCHAR(36) PRIMARY KEY, sku_id VARCHAR(64) NOT NULL, status VARCHAR(24) NOT NULL,
    expected_total BIGINT, actual_total BIGINT NOT NULL, expected_locked BIGINT NOT NULL, actual_locked BIGINT NOT NULL,
    expected_sold BIGINT NOT NULL, actual_sold BIGINT NOT NULL, reason VARCHAR(255) NOT NULL,
    operator_id VARCHAR(64), disposition VARCHAR(255), created_at DATETIME(6) NOT NULL,
    KEY idx_reconciliation_sku(sku_id,status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS inventory_reconciliation_cursor (
    id INT PRIMARY KEY, after_sku_id VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS promotion_campaign (
    campaign_id VARCHAR(64) PRIMARY KEY,
    title VARCHAR(160) NOT NULL,
    item_id VARCHAR(64) NULL,
    total_quantity INT NOT NULL,
    remaining_quantity INT NOT NULL,
    minimum_amount BIGINT NOT NULL,
    discount_amount BIGINT NOT NULL,
    starts_at DATETIME(6) NOT NULL,
    ends_at DATETIME(6) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    CHECK (remaining_quantity >= 0 AND remaining_quantity <= total_quantity),
    CHECK (discount_amount > 0 AND minimum_amount > discount_amount),
    CHECK (starts_at < ends_at AND ends_at <= expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS promotion_coupon (
    coupon_id VARCHAR(36) PRIMARY KEY,
    campaign_id VARCHAR(64) NOT NULL,
    account_id VARCHAR(64) NOT NULL,
    request_id VARCHAR(64) NOT NULL,
    status VARCHAR(24) NOT NULL,
    locked_order_id BIGINT NULL,
    created_at DATETIME(6) NOT NULL,
    UNIQUE KEY uk_coupon_account_campaign (account_id, campaign_id),
    UNIQUE KEY uk_coupon_account_request (account_id, request_id),
    KEY idx_coupon_account (account_id, created_at),
    FOREIGN KEY (campaign_id) REFERENCES promotion_campaign(campaign_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS promotion_reservation (
    order_id BIGINT PRIMARY KEY,
    coupon_id VARCHAR(36) NOT NULL,
    account_id VARCHAR(64) NOT NULL,
    item_id VARCHAR(64) NOT NULL,
    original_amount BIGINT NOT NULL,
    discount_amount BIGINT NOT NULL,
    status VARCHAR(24) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    FOREIGN KEY (coupon_id) REFERENCES promotion_coupon(coupon_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS promotion_claim_request (
    account_id VARCHAR(64) NOT NULL,
    request_id VARCHAR(64) NOT NULL,
    coupon_id VARCHAR(36) NOT NULL,
    PRIMARY KEY (account_id,request_id),
    FOREIGN KEY (coupon_id) REFERENCES promotion_coupon(coupon_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS checkout_offer (
    sku_id VARCHAR(64) PRIMARY KEY,
    item_id VARCHAR(64) NOT NULL,
    item_title VARCHAR(255) NOT NULL,
    unit_price BIGINT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (unit_price > 0),
    KEY idx_checkout_offer_item (item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS checkout_id (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    marker INT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 AUTO_INCREMENT=1000000000000;

CREATE TABLE IF NOT EXISTS checkout_workflow (
    order_id BIGINT PRIMARY KEY,
    account_id VARCHAR(64) NOT NULL,
    client_request_id VARCHAR(64) NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    coupon_id VARCHAR(36) NULL,
    original_amount BIGINT NOT NULL,
    discount_amount BIGINT NOT NULL DEFAULT 0,
    phase VARCHAR(32) NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    next_attempt_at DATETIME(6) NOT NULL,
    last_error VARCHAR(255) NULL,
    created_at DATETIME(6) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    UNIQUE KEY uk_checkout_account_request (account_id, client_request_id),
    KEY idx_checkout_due (phase, next_attempt_at),
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS seckill_activity_v1 (
    activity_id VARCHAR(64) PRIMARY KEY,
    item_id VARCHAR(64) NOT NULL,
    sku_id VARCHAR(64) NOT NULL,
    item_title VARCHAR(255) NOT NULL,
    unit_price BIGINT NOT NULL,
    total_quantity INT NOT NULL,
    remaining_quantity INT NOT NULL,
    starts_at DATETIME(6) NOT NULL,
    ends_at DATETIME(6) NOT NULL,
    CHECK (remaining_quantity >= 0 AND remaining_quantity <= total_quantity),
    CHECK (unit_price > 0 AND starts_at < ends_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS seckill_request_v1 (
    event_id VARCHAR(36) PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL,
    account_id VARCHAR(64) NOT NULL,
    activity_id VARCHAR(64) NOT NULL,
    item_id VARCHAR(64) NOT NULL,
    sku_id VARCHAR(64) NOT NULL,
    payload TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    order_id BIGINT NULL,
    dispatched BOOLEAN NOT NULL DEFAULT FALSE,
    published_at DATETIME(6) NULL,
    quota_released BOOLEAN NOT NULL DEFAULT FALSE,
    attempts INT NOT NULL DEFAULT 0,
    next_attempt_at DATETIME(6) NOT NULL,
    last_error VARCHAR(255) NULL,
    created_at DATETIME(6) NOT NULL,
    UNIQUE KEY uk_seckill_account_request (account_id,request_id),
    UNIQUE KEY uk_seckill_activity_account (activity_id,account_id),
    KEY idx_seckill_send (dispatched,next_attempt_at),
    KEY idx_seckill_result (status,next_attempt_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- 运维恢复和模拟退款的操作记录；仅从可信内部网络调用。
-- 按任务种类分别认领；时间以数据库为准，租约失效后旧实例不能提交本地进度。
CREATE TABLE IF NOT EXISTS commerce_worker_lease (
    worker_type VARCHAR(32) NOT NULL,
    resource_id VARCHAR(64) NOT NULL,
    claim_token VARCHAR(36) NULL,
    lease_until DATETIME(6) NULL,
    PRIMARY KEY (worker_type,resource_id),
    KEY idx_commerce_lease_expiry (lease_until)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- 划拨库存计入 sku_stock.locked_stock；订单预留只在池内转移，不再次扣普通库存。
CREATE TABLE IF NOT EXISTS inventory_activity_pool (
    activity_id VARCHAR(64) PRIMARY KEY,
    sku_id VARCHAR(64) NOT NULL,
    total_quantity INT NOT NULL,
    available_quantity INT NOT NULL,
    reserved_quantity INT NOT NULL DEFAULT 0,
    sold_quantity INT NOT NULL DEFAULT 0,
    returned_quantity INT NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'OPEN',
    CHECK (available_quantity >= 0 AND reserved_quantity >= 0 AND sold_quantity >= 0 AND returned_quantity >= 0),
    CHECK (total_quantity = available_quantity + reserved_quantity + sold_quantity + returned_quantity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS inventory_activity_reservation (
    order_id BIGINT PRIMARY KEY,
    activity_id VARCHAR(64) NOT NULL,
    sku_id VARCHAR(64) NOT NULL,
    quantity INT NOT NULL,
    status VARCHAR(16) NOT NULL,
    FOREIGN KEY (activity_id) REFERENCES inventory_activity_pool(activity_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- 独立扩展表保留历史活动/订单；无此记录的历史数据继续走原库存路径。
CREATE TABLE IF NOT EXISTS seckill_activity_allocation (
    activity_id VARCHAR(64) PRIMARY KEY,
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    next_attempt_at DATETIME(6) NOT NULL,
    phase_started_at DATETIME(6) NOT NULL,
    last_error VARCHAR(255) NULL,
    FOREIGN KEY (activity_id) REFERENCES seckill_activity_v1(activity_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS checkout_stock_scope (
    order_id BIGINT PRIMARY KEY,
    activity_id VARCHAR(64) NOT NULL,
    FOREIGN KEY (order_id) REFERENCES checkout_workflow(order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

INSERT INTO rs_schema_version(component, version)
VALUES ('rs-service-commerce-allocation', 'commerce_allocation_v1')
ON DUPLICATE KEY UPDATE version = VALUES(version), applied_at = CURRENT_TIMESTAMP(6);

CREATE TABLE IF NOT EXISTS commerce_operation_audit (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    component VARCHAR(32) NOT NULL,
    resource_id VARCHAR(64) NOT NULL,
    operator_id VARCHAR(64) NOT NULL,
    action VARCHAR(32) NOT NULL,
    reason VARCHAR(255) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    KEY idx_commerce_audit_resource (component,resource_id,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

INSERT INTO rs_schema_version(component, version)
VALUES ('rs-service-commerce-operations', 'commerce_operations_v1')
ON DUPLICATE KEY UPDATE version = VALUES(version), applied_at = CURRENT_TIMESTAMP(6);

INSERT INTO rs_schema_version(component, version)
VALUES ('rs-service-commerce', 'commerce_v1')
ON DUPLICATE KEY UPDATE version = VALUES(version), applied_at = CURRENT_TIMESTAMP(6);

-- 迁移时只登记一次期初总量；后续变更必须通过幂等入库/盘点账本。
INSERT INTO inventory_stock_baseline(sku_id,opening_total)
SELECT sku_id,CAST(available_stock AS SIGNED)+locked_stock+sold_stock FROM sku_stock
ON DUPLICATE KEY UPDATE sku_id=inventory_stock_baseline.sku_id;
INSERT INTO rs_schema_version(component,version) VALUES ('rs-service-commerce-completion','commerce_completion_v2')
ON DUPLICATE KEY UPDATE version=VALUES(version),applied_at=CURRENT_TIMESTAMP(6);
