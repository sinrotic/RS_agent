#!/usr/bin/env bash
# 只备份应用权威小表，不包含可重建的全量商品/推荐训练数据。
set -euo pipefail
umask 077
ROOT="${RS_DEPLOY_ROOT:-/home/luo/RS_agent_java}"
DEST="${RS_BACKUP_DIR:-${ROOT}/backups/application-$(date -u +%Y%m%dT%H%M%SZ)}"
MYSQL_CONTAINER="${RS_MYSQL_CONTAINER:-rs-agent-java-mysql}"
mkdir -p "$DEST"
chmod 700 "$DEST"
TMP="$DEST/application.sql.gz.tmp"
test ! -e "$DEST/application.sql.gz"
trap 'rm -f -- "$TMP"' EXIT
docker exec "$MYSQL_CONTAINER" sh -ec '
  export MYSQL_PWD="$MYSQL_PASSWORD"
  tables=$(mysql -N -u "$MYSQL_USER" "$MYSQL_DATABASE" -e "SHOW TABLES" |
    grep -E "^(rs_schema_version$|rs_auth_|rs_account_profile_binding$|rs_user_session$|agent_|rs_recommendation_|rs_preference_version$|rs_recommend_feedback_|rs_profile_item_preference_projection$|recommendation_(trade_event|purchase_signal)$|inventory_|commerce_|checkout_|promotion_|seckill_|orders$|order_items$|sku_stock$|stock_logs$|payment_|consumer_message_log$)")
  test -n "$tables"
  exec mysqldump -u "$MYSQL_USER" --single-transaction --no-tablespaces --hex-blob "$MYSQL_DATABASE" $tables
' | gzip > "$TMP"
gzip -t "$TMP"
mv "$TMP" "$DEST/application.sql.gz"
gzip -t "$DEST/application.sql.gz"
sha256sum "$DEST/application.sql.gz" > "$DEST/SHA256SUMS"
printf '%s\n' 'scope=mysql_application_tables_only; Scylla transcript snapshot and off-host copies required separately' > "$DEST/SCOPE.txt"
echo "应用表备份已通过校验：$DEST"
