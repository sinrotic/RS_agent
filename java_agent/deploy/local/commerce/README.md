# 隔离交易联调

先在仓库根目录构建当前交易模块，再运行真实 MySQL、Redis、Kafka 联调：

```powershell
$env:MAVEN_OPTS='-Xmx768m'
mvn -f java_agent/pom.xml -pl rs-service-order,rs-service-seckill,rs-service-inventory,rs-service-payment -am package
python java_agent/deploy/local/commerce/run.py --faults --output outputs/commerce-allocation-integration
```

要求 Docker 守护进程、JDK 21、Python 3.11+、Node 20+；宿主端口 24291/24391/24292/24294/24394/24295 必须空闲。每次随机生成 project 和凭证，使用新数据库，fixture 只写入该数据库。不启动生产 Compose，不复用现有数据库/库存/账号。固定 JAR 快照避免其他构建改变运行中的产物。

容器内存上限约 4.3GB，Java 单实例堆 192MB，订单和秒杀各两个实例。包含 MySQL 初始化、Kafka topic 初始化和服务就绪检查，通常需数分钟；执行前核算机器其他进程，遵循仓库 12GB/14GB 资源限制。退出清理本次容器、网络和数据卷，保留脱敏日志、报告和固定产物。

报告区分实际中间件与外部支付 Mock：

- `report.json`：普通订单耗尽未划拨库存后，40 个测试 Account 各提交两次，20 个唯一秒杀订单；10 单模拟支付、10 单取消，活动结束后归还余量。记录 P95/P99、单批请求 QPS，断言库存守恒。
- `fault-report.json`：仅 `--faults` 时生成；停止消费者后受理、重启服务继续生成原订单，Kafka 停机时保留待发布事件和额度，恢复后结清及监测恢复。
- `verification.json`：真实联合验收、故障验收、清理状态、各 JAR 的 SHA-256；任何未确认或断言失败返回非零。

请求直连隔离服务，Account 头用于测试，未覆盖正式 Gateway 登录；模拟支付不产生真实付款，也不覆盖真实支付渠道或退款。单批吞吐和单 broker 停机恢复不能当作持续容量或高可用证明。
