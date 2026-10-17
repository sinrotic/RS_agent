CREATE TABLE IF NOT EXISTS rs_recommendation_delivery (
  request_id VARCHAR(80) PRIMARY KEY,
  account_id VARCHAR(80) NOT NULL,
  profile_user_id VARCHAR(80) NOT NULL,
  session_id VARCHAR(120) NOT NULL,
  scene VARCHAR(40) NOT NULL,
  preference_version BIGINT NOT NULL DEFAULT 0,
  created_at DATETIME(3) NOT NULL,
  expires_at DATETIME(3) NOT NULL,
  KEY idx_delivery_owner (profile_user_id, session_id, created_at),
  KEY idx_delivery_expiry (expires_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS rs_recommendation_delivery_item (
  request_id VARCHAR(80) NOT NULL,
  item_id VARCHAR(120) NOT NULL,
  rank_no INT NOT NULL,
  base_score DOUBLE NOT NULL,
  category VARCHAR(255) NOT NULL DEFAULT '',
  brand VARCHAR(255) NOT NULL DEFAULT '',
  attributes_json JSON NOT NULL,
  PRIMARY KEY (request_id, item_id),
  UNIQUE KEY uk_delivery_rank (request_id, rank_no),
  CONSTRAINT fk_delivery_item_delivery FOREIGN KEY (request_id)
    REFERENCES rs_recommendation_delivery(request_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS rs_preference_version (
  profile_user_id VARCHAR(80) NOT NULL,
  session_id VARCHAR(120) NOT NULL,
  version_no BIGINT NOT NULL DEFAULT 0,
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (profile_user_id, session_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS rs_recommend_feedback_event (
  event_id VARCHAR(80) PRIMARY KEY,
  idempotency_key VARCHAR(512) NOT NULL,
  request_id VARCHAR(80) NOT NULL,
  item_id VARCHAR(120) NOT NULL,
  account_id VARCHAR(80) NOT NULL,
  profile_user_id VARCHAR(80) NOT NULL,
  session_id VARCHAR(120) NOT NULL,
  event_type VARCHAR(24) NOT NULL,
  reverses_event_id VARCHAR(80) NULL,
  position_no INT NULL,
  visible_ratio DECIMAL(5,4) NULL,
  visible_duration_ms BIGINT NULL,
  category VARCHAR(255) NOT NULL DEFAULT '',
  brand VARCHAR(255) NOT NULL DEFAULT '',
  attributes_json JSON NOT NULL,
  occurred_at DATETIME(3) NOT NULL,
  received_at DATETIME(3) NOT NULL,
  preference_version BIGINT NULL,
  UNIQUE KEY uk_feedback_idempotency (idempotency_key),
  KEY idx_feedback_owner_time (profile_user_id, received_at),
  KEY idx_feedback_delivery_item (request_id, item_id),
  KEY idx_feedback_reversal (reverses_event_id),
  CONSTRAINT fk_feedback_delivery_item FOREIGN KEY (request_id, item_id)
    REFERENCES rs_recommendation_delivery_item(request_id, item_id),
  CONSTRAINT fk_feedback_reversal FOREIGN KEY (reverses_event_id)
    REFERENCES rs_recommend_feedback_event(event_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS rs_profile_item_preference_projection (
  profile_user_id VARCHAR(80) NOT NULL,
  item_id VARCHAR(120) NOT NULL,
  latest_event_id VARCHAR(80) NOT NULL,
  effective_event_id VARCHAR(80) NOT NULL,
  current_state VARCHAR(24) NOT NULL,
  category VARCHAR(255) NOT NULL DEFAULT '',
  brand VARCHAR(255) NOT NULL DEFAULT '',
  attributes_json JSON NOT NULL,
  preference_version BIGINT NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  expires_at DATETIME(3) NOT NULL,
  PRIMARY KEY (profile_user_id, item_id),
  KEY idx_profile_preference_expiry (expires_at),
  CONSTRAINT fk_profile_preference_event FOREIGN KEY (latest_event_id)
    REFERENCES rs_recommend_feedback_event(event_id),
  CONSTRAINT fk_profile_preference_effective_event FOREIGN KEY (effective_event_id)
    REFERENCES rs_recommend_feedback_event(event_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS rs_recommend_feedback_outbox (
  event_id VARCHAR(80) PRIMARY KEY,
  status VARCHAR(24) NOT NULL,
  attempt_count INT NOT NULL DEFAULT 0,
  next_attempt_at DATETIME(3) NOT NULL,
  last_error VARCHAR(1000) NULL,
  created_at DATETIME(3) NOT NULL,
  applied_at DATETIME(3) NULL,
  KEY idx_outbox_pending (status, next_attempt_at),
  CONSTRAINT fk_outbox_event FOREIGN KEY (event_id)
    REFERENCES rs_recommend_feedback_event(event_id)
) ENGINE=InnoDB;

INSERT INTO rs_schema_version (component, version)
VALUES ('rs-service-recommend-feedback', 'recommend_feedback_schema_v1')
ON DUPLICATE KEY UPDATE version = VALUES(version), applied_at = CURRENT_TIMESTAMP(6);
