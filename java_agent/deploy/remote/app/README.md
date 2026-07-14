# RS Agent Java remote app services

This compose stack runs the executable Spring Boot jars built under `~/RS_agent_java/services`.

It joins the middleware network created by `~/RS_agent_java/infra/docker-compose.yml`.

## Catalog bootstrap

Apply the catalog schema before starting `rs-service-catalog`:

```bash
docker cp \
  ~/RS_agent_java/scripts/rs_service_catalog_schema.sql \
  rs-agent-java-mysql:/tmp/rs_service_catalog_schema.sql
docker exec rs-agent-java-mysql sh -lc \
  'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u"$MYSQL_USER" "$MYSQL_DATABASE" < /tmp/rs_service_catalog_schema.sql'
```

Project the canonical product rows from `amazon_items_base`. Each batch commits
the catalog upsert and its cursor in the same transaction:

```bash
python3 ~/RS_agent_java/scripts/project_catalog_to_mysql.py \
  --container rs-agent-java-mysql \
  --batch-size 5000 \
  --progress-every 10
```

If the command stops, use the `run_id` printed by the script and resume it:

```bash
python3 ~/RS_agent_java/scripts/project_catalog_to_mysql.py \
  --container rs-agent-java-mysql \
  --resume-run-id RUN_ID \
  --batch-size 5000 \
  --progress-every 10
```

Do not start Catalog acceptance checks until the latest run is `COMPLETED` and
the projected and source counts match:

```bash
docker exec rs-agent-java-mysql sh -lc \
  'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u"$MYSQL_USER" "$MYSQL_DATABASE" -e \
  "SELECT run_id,status,processed_rows,source_rows FROM rs_catalog_projection_run ORDER BY run_id DESC LIMIT 1; \
   SELECT COUNT(*) AS catalog_rows,COUNT(DISTINCT item_id) AS distinct_items FROM rs_catalog_item;"'
```

## Start order

```bash
cd ~/RS_agent_java/app_deploy
cp .env.example .env

docker compose --env-file .env up -d rs-service-model rs-service-recommend rs-service-agent rs-service-platform-trace
docker compose --env-file .env up -d rs-service-user rs-service-catalog
docker compose --env-file .env up -d rs-api-gateway
docker compose --env-file .env ps
```

Gateway is bound to remote `127.0.0.1:18088`. Use this for SSH tunnel or Cloudflare Tunnel.
Platform trace is bound to remote `127.0.0.1:18108` for direct observation calls during demos.

Catalog exact-ID reads use Redis as a cache and `rs_catalog_item` in MySQL as
the source of truth. The cache is enabled by default with a 24-hour TTL:

```bash
RS_CATALOG_CACHE_ENABLED=true
RS_CATALOG_CACHE_ITEM_TTL_SECONDS=86400
```

The first detail or batch request fills keys under
`rs:catalog:item:v1:*`; subsequent requests read those records from Redis.

Platform trace can also be reached through the gateway at `/api/platform/**`. In the remote compose stack it pulls
Agent, Recommend, and User traces over the internal Docker network when `RS_PLATFORM_TRACE_CLIENTS_ENABLED=true`.
