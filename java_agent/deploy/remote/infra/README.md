# RS Agent Java remote infra

This compose stack is for the remote `~/RS_agent_java` deployment.

It starts only the middleware needed by the Java services:

- Nacos
- MySQL
- Redis
- Elasticsearch
- MinIO
- ScyllaDB and Milvus
- Kafka when the `full-commerce` profile is enabled

All host ports are bound to `127.0.0.1` on the remote server. Use SSH tunnels for local development access, and expose only the Java gateway through Cloudflare Tunnel later.

## Start

```bash
cd ~/RS_agent_java/infra
cp .env.example .env
docker compose --env-file .env up -d
docker compose --env-file .env ps
```

Use `docker compose --env-file .env --profile full-commerce up -d` when deploying Order/Inventory/Payment/Seckill.

## MySQL 提交存储迁到 NVMe

`RS_MYSQL_DATA_DIR` 支持指定持久数据目录，未设置时沿用 `../db/mysql`。已有数据不能仅改挂载后启动；先停止业务写入及 MySQL，再冷备、复制并核验。同一物理副本使用同一 MySQL 镜像版本打开。

当前服务器的业务库约 23GB，已挂载的 NVMe 分区空间有限。`docker-compose.mysql-hybrid.yml` 将已有 `rs_agent` 库目录继续挂载在原盘；主数据目录中的 redo、binlog、doublewrite、undo、系统表及新增数据库使用 NVMe。既有库的表数据仍在原盘，事务落盘保障保持不变。新增数据库会占用 NVMe，需持续监测空间；脚本要求迁移后至少保留 8GiB 余量。

```bash
# 必须先停止业务服务及 MySQL；默认仅检查，不做迁移。
python3 migrate_mysql_to_nvme.py --infra-dir "$PWD"
# 完整冷备并核验所有文件 SHA-256，然后切换、核验业务行数和两次启动。
python3 migrate_mysql_to_nvme.py --infra-dir "$PWD" --apply
```

脚本只重新创建 MySQL 容器，保留 `innodb_flush_log_at_trx_commit=1`、`sync_binlog=1`、binlog 与 doublewrite。结束恢复原来的 MySQL 停机状态。已有 `.env` 设置 `COMPOSE_FILE` 时脚本拒绝猜测合并；配置组合需先核对。

迁移后 `.env` 的 `COMPOSE_FILE=docker-compose.yml:docker-compose.mysql-hybrid.yml` 保证普通 `docker compose` 启动仍包含旧库挂载。若手动使用 `-f`，必须同时传入这两个文件。重建前可用 `docker compose config --format json` 核对 MySQL 挂载；该命令包含展开后的凭证，不要将完整输出贴到公开日志。

迁移记录 `mysql-migration-时间/` 包含私有原配置和核验结果；`db/mysql-cold-backup-时间/` 是整个实例的一致冷备。启动 NVMe 实例后，原 `db/mysql/rs_agent` 会继续变化，**原主目录已不再是可直接启动的一致备份**。验收阶段失败会停机并用完整冷备恢复整个旧实例；业务重新产生写入后，应先冷备当前 NVMe 主目录加原盘业务库或做完整逻辑备份，再迁回。不能仅切换主挂载或拼接新旧 redo、系统文件和表文件，直接恢复迁移前冷备会丢失迁移后的写入。

full-commerce 新增 `commerce-kafka-init`，创建并检查秒杀业务与 DLT topic，默认 3 分区、1 副本。只启动 Kafka 时，还需执行 `docker compose --env-file .env --profile full-commerce run --rm commerce-kafka-init`，成功后再启动交易服务。既有 topic 参数不一致会报错，需人工核对；不会修改既有 topic。单 broker 配置用于开发联调，实际高可用需独立验收。

## Local SSH tunnels

```bash
ssh -N \
  -L 18848:127.0.0.1:18848 \
  -L 18080:127.0.0.1:18080 \
  -L 13306:127.0.0.1:13306 \
  -L 16379:127.0.0.1:16379 \
  -L 19200:127.0.0.1:19200 \
  -L 19000:127.0.0.1:19000 \
  -L 19001:127.0.0.1:19001 \
  server
```

Local Java development can then use:

- `NACOS_SERVER_ADDR=127.0.0.1:18848`
- Nacos console: `http://127.0.0.1:18080`
- `SPRING_DATASOURCE_URL=jdbc:mysql://127.0.0.1:13306/rs_agent`
- `SPRING_REDIS_HOST=127.0.0.1`
- `SPRING_REDIS_PORT=16379`
- `RS_ELASTICSEARCH_URI=http://127.0.0.1:19200`
- `RS_MINIO_ENDPOINT=http://127.0.0.1:19000`
