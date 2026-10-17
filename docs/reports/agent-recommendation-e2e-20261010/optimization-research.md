# 完整推荐延迟：官方资料调研与下一轮优化边界

调研日期：2026-10-10。本文只依据官方文档、维护者源码和本目录已有验收证据；没有启动服务、修改应用实现或形成新的性能实测。资料中的 `stable`、`current` 和 GitHub `master` 会变化，实施时还要核对仓库实际依赖版本。

后续实施已完成连接池、短事务、商品批量写入、Redis 合并与同轮历史复用，最新预热完整接口约 775–802ms。本调研保留实施前核查，当前实现与完整验证见 [存储优化验收](../agent-persistence-optimization-20261010/README.md)。

下一轮应优先修复 JDBC 连接复用，再处理同轮重复读写和派生投影；冷查询的 GPU 排队另行优化。现有预热完整流程仍约 1.24–1.42 秒，不能将官方组件的性能描述换算成项目已经能达到 300ms。阶段日志也不能证明某次百毫秒延迟全部来自 fsync。

## 代码核查与实测依据

以下是本仓库当前实现的核查结果，区别于官方文档说明和待验证的收益推断。

| 核查点 | 当前实现 | 下一步 |
|---|---|---|
| Agent MySQL 数据源 | `AgentSessionPersistenceConfiguration:78` 构造普通 `MysqlDataSource`；`MysqlAgentSessionProjectionStore:237` 每条 SQL 单独获取并关闭连接 | 显式连接池，先不改变事件提交顺序 |
| Agent 投影写入 | `recordTranscriptEntry:83` 每条事件执行 Session、Turn 两次 UPSERT；实测快速路径保存 4 条事件 | 按当前非池化实现，一轮至少 8 次物理建连、8 次默认 autocommit；将同一事件的两次更新放入同一个短事务，再评估按轮合并投影 |
| Recommend MySQL 数据源 | `RecommendationPersistenceConfiguration:24` 构造 `DriverManagerDataSource` | 显式连接池；不能只加 Hikari 配置项 |
| 推荐交付保存 | `JdbcRecommendationPersistenceStore:54` 已将交付头和全部商品放在一个 `TransactionTemplate` 中；5 个商品仍逐条 INSERT | 保留已有事务，批量插入商品。此处不是 5 次独立建连或提交 |
| 恢复及历史读取 | `InMemoryAgentOrchestrationService:268/294/297/316` 分别处理请求重试、恢复上下文、首轮检查和既有轮次；Journal 的 `beginTurn:51` 又读取 latest | 在既有 Session 执行串行规则下，复用当轮已恢复的权威视图；不能凭客户端或空 Redis 判定首轮 |
| Redis 热事件 | `RedisAgentHotSessionStore:34/82` 追加事件与更新 TTL 是两次同步命令 | 合并成同键短 Lua；保持事件顺序、过期策略与恢复能力 |
| BGE 计算缓存 | `RecommendationInferenceCache:70` 的 key 包含完整、有序候选列表 | 改为精确 query/passage 对缓存，候选增减或换序时只算缺失项 |

源码位置：[Agent 数据源](../../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/config/AgentSessionPersistenceConfiguration.java)、[MySQL 投影](../../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/MysqlAgentSessionProjectionStore.java)、[Recommend 数据源](../../../java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/config/RecommendationPersistenceConfiguration.java)、[交付保存](../../../java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/service/impl/JdbcRecommendationPersistenceStore.java)、[Agent 编排](../../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentOrchestrationService.java)、[Journal](../../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/DefaultAgentSessionJournal.java)、[Redis 热状态](../../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/RedisAgentHotSessionStore.java)、[计算缓存](../../../java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/service/impl/RecommendationInferenceCache.java)。本地已构建的 Agent、Recommend JAR 中也未发现 HikariCP、DBCP 或 c3p0 依赖；这不是对未知生产部署的注入对象检查。

已有阶段证据：一个预热请求 Agent 总计 1209ms，恢复及路由 103ms、推荐 273ms、回答阶段 384ms、收尾 239ms。回答阶段包括保存语义事件，不能理解为 384ms 都在生成文字。匹配推荐日志的交付持久化约 171ms、缓存命中后的 BGE 约 0.37ms。阶段外尚有约 207ms，现有日志没有继续拆出建连、SQL、提交和 Redis 的独立耗时，不能全部归因于数据库。[完整实测报告](README.md)、[Agent 阶段日志](agent-fast-timings.log)、[Recommend 阶段日志](recommend-fast-timings.log)。

## 1. P0：显式建立数据库连接池，先避免逐 SQL 物理建连

源码核查发现：Recommend 自定义 `DriverManagerDataSource`，Agent 投影自定义 `MysqlDataSource`；后者每条 SQL 申请并关闭连接。实施时应再次检查实际注入对象与物理连接计数，不能因为项目使用 Spring Boot 就认定已经池化。

Spring 明确指出 `DriverManagerDataSource` 每次返回新的 Connection，不提供连接池，不适合多次连接请求的生产负载。[Spring：控制数据库连接](https://docs.spring.io/spring-framework/reference/data-access/jdbc/connections.html)

Spring Boot 的 SQL 文档说明，自定义 `DataSource` bean 会使相关自动配置退出。因此只补 `spring.datasource.hikari.*` 不足以证明自定义数据源变成 Hikari 池；需直接构造受生命周期管理的数据源或明确使用对应自动配置。[Spring Boot：SQL 数据库与连接池](https://docs.spring.io/spring-boot/reference/data/sql.html)

Connector/J 文档描述的池机制是在逻辑连接关闭后复用物理连接，由中间连接池管理生命周期；使用 JDBC `DataSource` 接口本身不是池化证明。[MySQL：Connector/J 连接池](https://dev.mysql.com/doc/connector-j/en/connector-j-usagenotes-j2ee-concepts-connection-pooling.html)

应用推断：把两个自定义非池化对象替换成显式、有界、可关闭的 HikariDataSource，保留原认证、SQL、事务和持久化顺序，应是比改变事实提交边界风险更低的第一步。池耗尽后 `getConnection` 仍会等待，池越大也不一定越快；需要监测 active、idle、pending、获取耗时和超时，并与数据库总连接预算匹配。[HikariCP：池大小与 connectionTimeout](https://github.com/brettwooldridge/HikariCP#configuration-knobs-baby)

验收采用只改变连接池的 A/B：预热单请求、不同画像 8 并发，分别记录获取连接、SQL 执行、commit、Scylla 和 Redis。对照 MySQL 的新连接数变化，并保留完整推荐、历史恢复和反馈去重测试。可预期减少连接建立成本；节省多少毫秒必须测量。

## 2. P1：减少提交次数，保留事务与权威事实

MySQL 默认 autocommit，每条成功 SQL 独立提交；显式短事务可把同一业务原子操作的多条 DML 合并为一次提交。事务也延长锁持有时间，不能随意把整轮模型调用包进数据库事务。[MySQL：autocommit、Commit 与 Rollback](https://dev.mysql.com/doc/refman/8.4/en/innodb-autocommit-commit-rollback.html)

Agent 当前执行器直接调用 `DataSource.getConnection()`。只在外层添加 `@Transactional` 不会自动使这段代码复用 Spring 事务连接；需使用 `JdbcTemplate` / `DataSourceUtils` 或显式管理同一个 Connection，覆盖 commit、rollback 和连接状态恢复。推荐交付现有 `JdbcTemplate` 已参与其短事务。[Spring：事务连接参与规则](https://docs.spring.io/spring-framework/reference/data-access/jdbc/connections.html)

`rewriteBatchedStatements=true` 的重写针对 `executeBatch()`，可将合适的 INSERT/REPLACE 合并成多值语句；对逐条 `executeUpdate()` 无法自动实现相同批处理。重写 UPSERT 时返回的批次更新计数可能是 `SUCCESS_NO_INFO`，不能再用逐条精确计数判断业务幂等结果；也要核验生成键和报文大小。[Connector/J：Performance Extensions](https://dev.mysql.com/doc/connector-j/en/connector-j-connp-props-performance-extensions.html)

不要以关闭可靠落盘作为本轮无退化优化。`innodb_flush_log_at_trx_commit=1` 每次提交写入并刷新日志；改为 0/2 会改变崩溃丢失窗口，刷新周期也不是精确的一秒保证。启用 binlog 时可靠配置还包括 `sync_binlog=1`。[MySQL：InnoDB 日志与落盘参数](https://dev.mysql.com/doc/refman/8.4/en/innodb-parameters.html#sysvar_innodb_flush_log_at_trx_commit)

Group commit 可以合并多个并行事务的日志同步，但人为增加 `binlog_group_commit_sync_delay` 会增加事务延迟。它是吞吐量与等待时间的取舍，不能作为“把单请求压到 300ms”的默认开关。[MySQL：binlog_group_commit_sync_delay](https://dev.mysql.com/doc/refman/8.0/en/replication-options-binary-log.html#sysvar_binlog_group_commit_sync_delay)

## 3. P1：Scylla prepared statements 与有边界的批量/异步

高频 CQL 应启动时 prepare 并复用绑定模板；Java Driver 缓存 prepared statement，绑定语句实现不可变，可用于并发请求。固定 query string 才便于复用，不能把 Session ID 等值拼进 CQL。已有 prepared 复用的代码无需重复优化。[Scylla Java Driver：Prepared statements](https://java-driver.docs.scylladb.com/stable/manual/core/statements/prepared/)

本仓库 `ScyllaAgentTranscriptEntryStore` 当前使用共享 CqlSession 加 `SimpleStatement`；共享 Session 已经存在，下一步是固定 CQL 的 prepare/bind，而非每请求创建新 Session。项目使用 DataStax Java Driver 4.17，实施需以该版本 API 核验；上述 Scylla Driver stable 文档用于解释同类语义，不能据此假设已升级驱动。

`executeAsync` 返回 CompletionStage，可以减少阻塞线程并组合独立操作，但不会消除数据库处理时间或让相互依赖的写入自动并行。驱动回调通常运行于 I/O 线程；不要在回调里调用同步 CQL/JDBC/HTTP 或执行重 CPU 工作，错误结果也必须一路传播到轮次完成处理。[Scylla Java Driver：Asynchronous programming](https://java-driver.docs.scylladb.com/stable/manual/core/async/)

Scylla BATCH 中同一分区的更新具备原子边界，单分区 LOGGED 会自动转为 UNLOGGED；跨分区 LOGGED 增加 batchlog 成本，跨分区 UNLOGGED 失败可能部分应用。BATCH 不是 SQL 事务，共用字符串 Session ID 也不等于多个表的同一个物理分区。相同时间戳的操作不保证按列表顺序胜出。只在核对表、完整 partition key、事件序号和恢复规则后合并小批次。[Scylla：BATCH 语义](https://docs.scylladb.com/manual/stable/cql/dml/batch.html)，[Java Driver：Batch statements](https://java-driver.docs.scylladb.com/stable/manual/core/statements/batch/)

“完成前等待 Scylla 成功”需解释为保留现有确认策略，不能等同于绝对掉电保证：`commitlog_sync=periodic` 可立即应答，batch 模式等待 fsync；LWT 另有落盘保证。优化不得悄悄降低一致性级别或改变已有 commitlog 策略。[Scylla：配置参数](https://docs.scylladb.com/manual/stable/reference/configuration-parameters.html)，[Scylla：LWT 与 Cassandra 的差异](https://docs.scylladb.com/manual/stable/kb/lwt-differences.html)

## 4. P2：让可重建投影退出关键路径，需要可靠重放机制

项目 ADR-0001 已定义 Scylla 为 Durable Session History 和 Context Checkpoint 的权威来源，MySQL Session Projection 与 Redis Hot Session State 可重建。减少每个 Session Event 对两个派生存储的同步刷新符合这个方向，但“提交后把任务丢进内存线程池”在进程崩溃时会丢刷新任务。

官方 transactional outbox 方案将业务变更和待发布事件写进同一数据库事务，再由后台消费者转发；必须处理重复、通知顺序、回滚和重试。不能把 Scylla 事实与 MySQL outbox 分别写入后称为同一事务；该项目应选择可直接重放的权威事件扫描，或与权威写入绑定的 CDC/待投影标记，并验证完整恢复路径。[AWS：Transactional outbox pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)

应用推断：按 Session/Event sequence 做幂等投影和持久水位；新 Turn 读取滞后投影时应补齐或回到权威历史。成功 `done` 仍须在最终事实按现有策略成功提交后发送。延后非权威投影不意味着允许后续请求看到旧上下文、旧 Session 状态或找不到新推荐交付。

Scylla CDC 与原表写入关联，读取可见性还受写/读 consistency level 与 RF 组合影响；不能用随意 CL 的一次 CDC 查询证明已消费所有完成事件。引入 CDC 是体系改动，不是立刻零成本提速。[Scylla：CDC 数据一致性](https://docs.scylladb.com/manual/stable/features/cdc/cdc-consistency.html)

反馈与会话的权威来源不同：ADR-0017 要求 Recommendation Feedback Event 在 MySQL 中权威提交，同事务分配 Preference Version、登记投影任务。不能为了加速把反馈也改成只写 Redis，或把“已持久化”直接冒充“在线偏好已生效”。

## 5. P1/P2：Redis 合并往返，区分 pipeline 与原子脚本

Pipeline 可一次发送多条命令、集中读取结果，减少 RTT 和 socket I/O；不提供这些命令相对于其他客户端的原子隔离，也不能直接解决依赖前一个读取结果的 read-compute-write。应限定每批大小并检查全部结果。[Redis：Pipelining](https://redis.io/docs/latest/develop/using-commands/pipelining/)

短 Lua 脚本可在服务器端完成读取、版本检查和更新，并在运行时阻止其他命令穿插；慢脚本会阻塞所有客户端。脚本缓存可能消失，需要处理 NOSCRIPT；Cluster 多键还有 key slot 限制。适合合并同 Session 事件追加、裁剪、TTL 与版本推进等小操作。[Redis：Scripting with Lua](https://redis.io/docs/latest/develop/programmability/eval-intro/)，[Redis：EVAL 与多键约束](https://redis.io/docs/latest/commands/eval/)

原子隔离不是 SQL 式错误回滚：Redis 事务不支持回滚；Lua 实现也不能凭“atomic”字样假定写入后异常会自动撤销。先校验类型、参数和前置条件，再进行有界写入；设计单调版本和可重建修复规则。[Redis：Transactions](https://redis.io/docs/latest/develop/using-commands/transactions/)

## 6. P2：BGE 从整批缓存转成精确 pair 缓存，再测试跨请求微批

BGE 官方示例用一个 query/passage 对计算一个分数，多对批量返回分数，`normalize=True` 是每个分数的 sigmoid。由此推断，纯 CrossEncoder 输出可以按精确 pair 复用，无需把整个候选列表的顺序作为缓存单位。但这只是针对原始模型分数，不代表个性化排序或最终推荐可跨画像共用。[FlagEmbedding：官方 reranker 推理示例](https://github.com/FlagOpen/FlagEmbedding/blob/master/examples/inference/reranker/README.md)

项目实施条件：key 包含模型/权重版本、精确 query 与完整 passage、tokenizer、模板、截断长度、dtype/运行时策略、normalize 规则；只推理缺失 pair，并按原请求位置补回所有结果。保留全部 96 候选、独立训练排序、独立交付 ID 和反馈状态；缓存有容量/TTL 上限，不缓存失败、非有限分数。批次/padding 改变可能产生浮点差异，需验证 top-k 排序稳定性及相关性，不能把拆批称为 bitwise 等价。

Triton dynamic batching 把多个无状态请求合并送往模型，并允许用短等待窗口凑批。`max_queue_delay_microseconds` 是凑批延迟设置，不是系统总排队时间上限；还需 max_queue_size、queue timeout 与拒绝策略。先在当前 BGE 单 worker 中实现可取消、有界队列和结果路由即可验证，不必第一步迁移整套 Triton。[NVIDIA Triton：Dynamic Batcher](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/batcher.html)

应用推断：按 token 长度分组、在 GPU 空闲时短时凑批，可能改善不同冷查询的并发吞吐；低流量单请求会增加等待，batch 过大会 OOM。必须分别测单请求和并发、queue wait/tokenize/GPU forward，不能把已有“单批 768 pairs 很快”当作完整并发已经提升。

FP16、ONNX、torch.compile 都需当前模型与真实长标题验证。Sentence Transformers 官方说明 FP16 可加速 GPU，但有精度变化；最新 CrossEncoder 基准并不普遍推荐 FlashAttention-2，ONNX/OpenVINO/compile 也可能更慢。这些技术不能消除已经命中缓存后仍存在的持久化耗时。[Sentence Transformers：CrossEncoder 推理优化](https://sbert.net/docs/cross_encoder/usage/efficiency.html)

## 7. P1：修复 SSE 超时与取消，提高完成率，和降延迟分开验收

Spring MVC 异步请求仍存在容器 async timeout，StreamingResponseBody 的写出也仍是阻塞 I/O。需要显式配置 AsyncTaskExecutor、超时和生命周期回调，并把请求 deadline/断连/取消传播到模型、排队和下游调用；不能只认为虚拟线程自动解决下游容量。官方明确建议为 StreamingResponseBody 显式配置执行器。[Spring：异步请求与 HTTP Streaming](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-ann-async.html)，[StreamingResponseBody API（7.0.5）](https://docs.spring.io/spring-framework/docs/7.0.5/javadoc-api/org/springframework/web/servlet/mvc/method/annotation/StreamingResponseBody.html)

应用推断：统一端到端 deadline，给正常大模型路径合理总预算并对过载快速拒绝，可避免当前约 30 秒断流后任务仍占资源。加大 async timeout 本身只改变允许等待多久，不能算响应更快；应同时报告完成率、失败类型、全体请求耗时与成功请求耗时。

## 8. 次优先：重叠商品详情请求，扩展快速路径时保留质量门禁

前端 `AgentChat.tsx` 当前在 `requestChat` 完成后才请求商品详情。可以在收到经过校验的商品卡片事件后预取 Catalog 详情，等待最终 `done` 确认后完成展示；断连和失败时取消或丢弃预取结果。也可通过明确的公开 DTO 携带已取得的目录信息，但必须遵守 ADR-0012 字段白名单。已有详情请求仅约十几毫秒，这个改动收益较小，不是 300ms 的主要突破口。

快速路径目前只覆盖部分明确的首轮品类需求，耳机测试还会因配件候选进入保守回退。扩大命中范围需要商品类目、别名和叶子类目的可验证判定，保留价格、未知属性、超长标题、历史上下文及配件排除等保护。不能通过直接取消回退让所有查询显得更快。GPU 微批也应另外测试不同 query、不同画像的冷请求；已有相同 query 的 8 并发利用了缓存合并，不能代表 8 个独立冷查询。

## 下一轮实验顺序与不能保证的部分

| 顺序 | 只改一个主要变量 | 完整流程必须复核的语义 |
|---|---|---|
| 1 | Agent/Recommend 显式 JDBC 连接池 | 所有 SQL、独立交付、历史与反馈不变，连接数量有界 |
| 2 | 同轮重复读取、Redis 往返、同一原子业务操作的短事务 | Session 内事件顺序、版本推进、失败回滚与重试 |
| 3 | Scylla prepared/合法小批，以及派生投影刷新方案 | 权威提交先于成功、缓存丢失恢复、滞后投影补齐 |
| 4 | 精确 pair 缓存与有界微批 | 96 候选全部计算、分数与相关性门禁、不同冷查询并发 |
| 5 | SSE deadline 与过载控制 | 取消不再占用资源、错误透明、失败计入完成率 |

本目录单次预热样本的 `recommend` 已占 273ms，其余阶段还包括上下文恢复、事实保存、最终提交和展示。即便连接池能显著改善其中若干阶段，也无法据此保证完整冷/热单轮均在 300ms 内。应先验证每一步能省掉的实际关键路径成本，再决定是否需要更大的投影架构调整。完整指标沿用本目录 README 定义，包含真实推荐、权威历史与商品详情完成，不改为首 token、占位卡片或跳过持久化的数字。
