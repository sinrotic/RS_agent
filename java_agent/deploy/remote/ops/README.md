# 运行保障第一版

本目录提供可选的指标采集与本地告警控制台，不替代真实业务验收。应用须发布含 `micrometer-registry-prometheus` 的 JAR，并启用 `/actuator/prometheus`；远程 app Compose 已设置该暴露项。指标及管理端口继续只允许回环或可信内部网络访问，公共 Gateway 不新增管理路由。

## 启动与验证

把本目录复制到服务器部署目录后运行：

```bash
docker compose -p rs-agent-java-ops config -q
docker compose -p rs-agent-java-ops run --rm --entrypoint promtool prometheus check config /etc/prometheus/prometheus.yml
docker compose -p rs-agent-java-ops run --rm --entrypoint amtool alertmanager check-config /etc/alertmanager/alertmanager.yml
docker compose -p rs-agent-java-ops up -d
```

Prometheus 入口为服务器 `127.0.0.1:19090`，Alertmanager 为 `127.0.0.1:19093`。默认规则覆盖指标入口不可达、HTTP 5xx 比例和反馈投影重试失败。采集不可达不能定位业务故障；启动期间和依赖停机时还需执行应用就绪检查。默认 receiver 仅保留本地控制台告警，未配置外部通知地址，也不会自动发送消息。

full-commerce 部署才设置 `RS_COMMERCE_PROMETHEUS_TARGETS=./commerce-targets.yml`，再更新 ops Compose；默认挂载空目标文件，避免对未部署的交易服务误报。交易规则包含服务不可达、待核对、20 分钟滞留、Kafka lag、死信和探测失败。Kafka 探测每 30 秒执行，失败不是零积压；DLT 指标包含保留的历史记录，须核对处理情况。运维任务工作台及认证配置见 [交易说明](../../../../docs/commerce-v1.md)。

两容器内存上限合计 640 MiB，指标保留 14 天、最多 2GB。部署前仍应按项目 12GB/14GB 本机资源限制估算全栈；本目录只适合隔离联调和第一版运行观察，不承诺基础设施高可用。

## 就绪及模型预算

```bash
python3 ../app/check_service_readiness.py --report readiness.json
# 只有 Agent 实际切换到本地 Qwen 时，才执行本地模型预算门禁：
python3 ../app/check_service_readiness.py --model-url http://127.0.0.1:18082/v1 --model qwen35-4b --report readiness-local-model.json
```

就绪检查失败退出码为 1，只确认 HTTP 健康和指定本地模型的上下文，不代表回答质量、画像推荐、数据库恢复和业务容量已通过。`/v1/models` 未公布容量或缺少选定模型时不能通过本地模型门禁。当前 Qwen 启动脚本默认 16K，并拒绝更小预算；不要把单独的 Qwen 配置误当作远端 GPT Agent 的实际配置。

## 备份与恢复演练

`../app/backup_application_state.sh` 使用容器内已有凭据生成 MySQL 应用权威表的一致性快照、gzip 校验及 SHA-256；输出目录权限为 700。它不备份全量目录、训练数据，也不备份 Scylla 的持久会话历史。执行前检查磁盘空间，备份不得公开或提交 Git。

```bash
bash ../app/backup_application_state.sh
```

完整恢复还必须单独取得 Scylla keyspace 快照、Schema、发布清单和密钥配置的安全备份。备份应复制到独立存储；本脚本没有替用户指定外部存储或凭据。演练应在独立数据库/网络中导入快照，验证账号、交付与反馈数量、偏好缓存重建和会话历史，然后销毁演练环境。不要向正在服务的数据库直接导入旧快照。

首次完成演练后再安装定时任务；建议每日备份并记录结果，每周抽查恢复。尚未执行真实备份、Scylla 快照或整机恢复的环境，不应声明已具备灾难恢复能力。

可以先在服务器执行隔离夹具检查，验证备份脚本和 MySQL 恢复命令。临时容器使用 `mysql:8.0`，内存上限 768 MiB，无网络和宿主端口；检查后删除临时容器及其数据卷，备份与结果留在新建的权限 700 目录中。

```bash
python3 verify_backup_restore.py --work-dir /home/luo/RS_agent_java/validation/backup-fixture-20261010
```

该检查只含 2 条测试账号、1 条 Session 和 2 条反馈，并确认可重建 Catalog 表不进入备份。通过不等于正式数据备份、Scylla 恢复、异地备份或完整灾备演练已经完成。

## Session 生命周期 SQL 检查

在仓库根目录运行以下命令，读取实际 User Schema 与 Mapper SQL，经 SSH 在隔离 MySQL 内验证活动刷新、24 小时边界、两种归属及结束后的原子拒绝。临时容器内存上限 768 MiB、CPU 上限 1，无网络和宿主端口；完成后删除临时容器及数据卷。该检查不访问正式数据库、不重启正式服务。

```bash
python java_agent/deploy/remote/ops/verify_session_lifecycle.py --host server --output outputs/service-completion-20261010/fixes-evidence/session-lifecycle-mysql.json
```
## 2026-10-19 交易通知与恢复入口

新增退款、交易事件和库存差异指标，交易服务的 5xx 与数据库连接池等待纳入告警。要启用实际接收器，将 `RS_ALERT_WEBHOOK_URL` 通过部署环境注入，执行 `python3 configure_alerts.py --output /私密部署目录/alertmanager-private.json`，再将 `RS_ALERTMANAGER_CONFIG` 指向该文件；配置不得放入 Git 仓库。先运行下文的 `amtool check-config`。默认配置不发送外部通知。

隔离的持续交易、三副本 Kafka 单点故障、MySQL/Redis 计划内提升、交易备份恢复及合成通知演练见 [补全说明](../../../../docs/commerce-completion-20261019.md)。这些演练不等于正式数据灾备或自动主从切换已上线。
