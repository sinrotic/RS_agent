-- 兼容旧版仅有 session_id/user_id/state 的投影表。保留旧 state 和全部数据。
SET @agent_upgrade_sql = IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='agent_sessions' AND column_name='last_request_id'), 'SELECT 1', 'ALTER TABLE agent_sessions ADD COLUMN last_request_id VARCHAR(128) NOT NULL DEFAULT ''''');
PREPARE agent_upgrade_stmt FROM @agent_upgrade_sql;
EXECUTE agent_upgrade_stmt;
DEALLOCATE PREPARE agent_upgrade_stmt;

SET @agent_upgrade_sql = IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='agent_sessions' AND column_name='last_seq'), 'SELECT 1', 'ALTER TABLE agent_sessions ADD COLUMN last_seq BIGINT NULL');
PREPARE agent_upgrade_stmt FROM @agent_upgrade_sql;
EXECUTE agent_upgrade_stmt;
DEALLOCATE PREPARE agent_upgrade_stmt;

SET @agent_upgrade_sql = IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='agent_sessions' AND column_name='last_entry_type'), 'SELECT 1', 'ALTER TABLE agent_sessions ADD COLUMN last_entry_type VARCHAR(64) NOT NULL DEFAULT ''''');
PREPARE agent_upgrade_stmt FROM @agent_upgrade_sql;
EXECUTE agent_upgrade_stmt;
DEALLOCATE PREPARE agent_upgrade_stmt;

SET @agent_upgrade_sql = IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='agent_sessions' AND column_name='last_entry_at'), 'SELECT 1', 'ALTER TABLE agent_sessions ADD COLUMN last_entry_at DATETIME(6) NULL');
PREPARE agent_upgrade_stmt FROM @agent_upgrade_sql;
EXECUTE agent_upgrade_stmt;
DEALLOCATE PREPARE agent_upgrade_stmt;

SET @agent_upgrade_sql = IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='agent_sessions' AND column_name='last_event_type'), 'SELECT 1', 'ALTER TABLE agent_sessions ADD COLUMN last_event_type VARCHAR(64) NOT NULL DEFAULT ''''');
PREPARE agent_upgrade_stmt FROM @agent_upgrade_sql;
EXECUTE agent_upgrade_stmt;
DEALLOCATE PREPARE agent_upgrade_stmt;

SET @agent_upgrade_sql = IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='agent_sessions' AND column_name='last_loop_index'), 'SELECT 1', 'ALTER TABLE agent_sessions ADD COLUMN last_loop_index INT NOT NULL DEFAULT 0');
PREPARE agent_upgrade_stmt FROM @agent_upgrade_sql;
EXECUTE agent_upgrade_stmt;
DEALLOCATE PREPARE agent_upgrade_stmt;

SET @agent_upgrade_sql = IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='agent_sessions' AND column_name='last_event_at'), 'SELECT 1', 'ALTER TABLE agent_sessions ADD COLUMN last_event_at DATETIME(6) NULL');
PREPARE agent_upgrade_stmt FROM @agent_upgrade_sql;
EXECUTE agent_upgrade_stmt;
DEALLOCATE PREPARE agent_upgrade_stmt;

SET @agent_upgrade_sql = IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='agent_sessions' AND column_name='latest_checkpoint_id'), 'SELECT 1', 'ALTER TABLE agent_sessions ADD COLUMN latest_checkpoint_id VARCHAR(128) NOT NULL DEFAULT ''''');
PREPARE agent_upgrade_stmt FROM @agent_upgrade_sql;
EXECUTE agent_upgrade_stmt;
DEALLOCATE PREPARE agent_upgrade_stmt;

SET @agent_upgrade_sql = IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='agent_sessions' AND column_name='checkpoint_seq'), 'SELECT 1', 'ALTER TABLE agent_sessions ADD COLUMN checkpoint_seq BIGINT NULL');
PREPARE agent_upgrade_stmt FROM @agent_upgrade_sql;
EXECUTE agent_upgrade_stmt;
DEALLOCATE PREPARE agent_upgrade_stmt;

ALTER TABLE agent_sessions ALTER COLUMN user_id SET DEFAULT '';
-- 权威会话记录仍使用 v1；本次只升级可重建的 MySQL 投影，单独登记版本。
INSERT INTO agent_schema_version(component,version) VALUES ('agent-session','agent_session_v1') ON DUPLICATE KEY UPDATE version=VALUES(version), applied_at=CURRENT_TIMESTAMP(6);
INSERT INTO agent_schema_version(component,version) VALUES ('agent-session-projection','agent_session_projection_v2') ON DUPLICATE KEY UPDATE version=VALUES(version), applied_at=CURRENT_TIMESTAMP(6);
