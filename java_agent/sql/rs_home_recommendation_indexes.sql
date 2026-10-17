-- 首页探索仅扫描覆盖索引中的 ID，避免读取数十万行商品 JSON。
SET @home_catalog_index_sql = IF(
  EXISTS(SELECT 1 FROM information_schema.statistics
         WHERE table_schema = DATABASE() AND table_name = 'rs_catalog_item' AND index_name = 'idx_catalog_discovery'),
  'SELECT 1',
  'ALTER TABLE rs_catalog_item ADD INDEX idx_catalog_discovery (status, category), ALGORITHM=INPLACE, LOCK=NONE'
);
PREPARE home_catalog_index_statement FROM @home_catalog_index_sql;
EXECUTE home_catalog_index_statement;
DEALLOCATE PREPARE home_catalog_index_statement;

SET @home_delivery_index_sql = IF(
  EXISTS(SELECT 1 FROM information_schema.statistics
         WHERE table_schema = DATABASE() AND table_name = 'rs_recommendation_delivery' AND index_name = 'idx_delivery_profile_time'),
  'SELECT 1',
  'ALTER TABLE rs_recommendation_delivery ADD INDEX idx_delivery_profile_time (profile_user_id, created_at), ALGORITHM=INPLACE, LOCK=NONE'
);
PREPARE home_delivery_index_statement FROM @home_delivery_index_sql;
EXECUTE home_delivery_index_statement;
DEALLOCATE PREPARE home_delivery_index_statement;
