# ScyllaDB 连接、Java Driver 连接池与背压研究

日期：2026-07-17  
范围：ScyllaDB CQL 原生协议、DataStax Java Driver 4.17，以及本仓库 `java_agent/rs-service-agent` 的实际用法。  
资料约束：只使用 ScyllaDB、DataStax/Apache Cassandra Driver 的官方文档或仓库内代码。

## 结论摘要

1. **ScyllaDB 没有一个类似 MySQL `max_connections`、适合直接拿来做容量规划的单一连接数上限。** 官方资料说明连接会占用内存，连接增多时 ScyllaDB 会从缓存腾出内存；新连接初始化和每个 shard 的并发请求则分别有节流/丢弃负载机制。因此实际极限由节点 CPU、内存、文件描述符、协议并发、查询成本和配置共同决定，必须通过指标与压测确定，不能只看 TCP 连接数。[ScyllaDB FAQ](https://docs.scylladb.com/manual/stable/faq.html#how-many-connections-is-it-recommended-to-open-from-each-scylladb-client-application)；[ScyllaDB 配置参数](https://docs.scylladb.com/manual/stable/reference/configuration-parameters.html#max-concurrent-requests-per-shard)
2. **本项目已经有连接池，不应再为每次查询创建连接，也不应像 JDBC/HikariCP 那样自行包装一层“借连接池”。** 一个长生命周期 `CqlSession` 会为每个已连接节点维护连接池；CQL 原生协议通过 stream id 在一条 TCP 连接上复用许多并发请求。Java Driver 4.17 默认每节点 1 条数据连接，每条连接最多 1024 个并发请求（协议理论上最多 32768 个 stream id）。[Driver 4.17 连接池](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/pooling/index.html)
3. **可以排队，但正确机制是 Driver 的有界 Request Throttler，而不是连接池队列。** 4.x 连接池在连接繁忙时会尝试查询计划中的下一个节点；所有连接都没有可用 stream id 时会失败。`ConcurrencyLimitingRequestThrottler` 才负责“最多 N 个执行、其余最多排队 M 个”；队列满时抛 `RequestThrottlingException`。[Driver 4.17 请求节流](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/throttling/index.html)
4. **队列必须有界且保持较短。** 请求超时从进入 Driver 时已经开始计时，包含节流队列等待、重试和推测执行；大队列会把过载变成高延迟和队列内超时。过载时应快速失败并由 API 层返回可重试响应，而不是无限排队或无界重试。[Driver 4.17 请求节流](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/throttling/index.html)；[Driver 4.17 升级说明](https://docs.datastax.com/en/developer/java-driver/4.17/upgrade_guide/)
5. **对本仓库当前的单节点、单 shard、1 GB 开发部署，Driver 默认连接池容量不是瓶颈。** 当前 Agent 服务最多 32 个活跃 loop，Scylla 调用使用同步 `CqlSession.execute(...)`，而一条默认连接已有 1024 个 stream 槽位。现阶段优先事项是复用现有 Session、改 PreparedStatement、加有界节流和指标，不是增加连接数。

## 1. ScyllaDB 到底有没有“连接限制”

### 1.1 没有一个可直接回答所有部署的固定连接数

ScyllaDB 官方 FAQ 没给出硬性的“最大客户端连接数”，而是说明：客户端连接增多会占用内存，ScyllaDB 会从数据缓存腾出内存，连接减少后再把内存归还缓存。这意味着连接数仍然有资源成本，只是容量表现为资源退化或其他下游限制，而不是一个通用常数。[ScyllaDB FAQ：内存管理](https://docs.scylladb.com/manual/stable/faq.html#scylladb-is-using-all-of-my-memory-why-is-that-what-if-the-server-runs-out-of-memory)

官方给出的性能经验是：**每个客户端应用、对每个 ScyllaDB 节点，至少每个 ScyllaDB core 建立 1–3 条连接**。这是性能经验值，不是上限，也不能直接套到非 shard-aware 的通用 Cassandra Driver 上无限加连接。[ScyllaDB FAQ：推荐连接数](https://docs.scylladb.com/manual/stable/faq.html#how-many-connections-is-it-recommended-to-open-from-each-scylladb-client-application)

ScyllaDB 另有两个容易被误读成“连接上限”的配置：

- `uninitialized_connections_semaphore_cpu_concurrency`：每个 shard 同时用 CPU 初始化的新驱动连接数，默认 8；超过时是**节流新连接初始化**，已可服务请求的连接不受影响。它不是已建立连接总数上限。
- `max_concurrent_requests_per_shard`：单个 shard 处理的最大并发请求数，超过后开始 shedding extra load；当前官方参考的默认值为 `uint32_t` 最大值，即默认不靠此项丢弃请求。它限制的是请求并发，不是 TCP 连接数。

来源：[ScyllaDB 配置参数](https://docs.scylladb.com/manual/stable/reference/configuration-parameters.html#uninitialized-connections-semaphore-cpu-concurrency)。本仓库固定使用 `scylladb/scylla:6.2`，上线修改服务端参数前应再以 6.2 镜像内的 `scylla --help`/对应版本配置参考核对；这里引用 stable 文档用于解释参数语义，不主张直接修改这些服务端默认值。

### 1.2 连接容量与请求容量是两个维度

一条 CQL TCP 连接不是一次只能跑一个请求。原生协议用 stream id 标记同一连接上的并发请求，响应到达后再按 id 对应到请求。Java Driver 4.17 文档说明每条连接协议上最多有 32768 个 stream id；Driver 自己默认只允许每连接 1024 个并发请求，避免在服务端堆积过多工作。[Driver 4.17 连接池基础](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/pooling/index.html#basics)

所以容量应至少拆成：

- 建立了多少 TCP 连接；
- 每条连接允许多少 in-flight 请求；
- Session 全局允许多少并发请求；
- 服务端每个 shard 能以目标延迟处理多少请求；
- 单条查询的分区大小、返回数据量和读写成本。

仅增加连接不会让数据库自动变快；可能只会让更多请求同时压到一个内存只有 1 GB 的开发节点上。

## 2. Java Driver 4.17 的连接池模型

Driver 4.17 的关键模型是：

```text
一个应用进程中的 CqlSession
  ├─ 节点 A 的连接池：默认 1 条数据连接 × 每连接 1024 个并发请求
  ├─ 节点 B 的连接池：默认 1 条数据连接 × 每连接 1024 个并发请求
  └─ 控制连接：最多额外连接到集群中的一个节点，用于拓扑/模式事件
```

默认配置为：

```hocon
datastax-java-driver.advanced.connection {
  max-requests-per-connection = 1024
  pool {
    local.size = 1
    remote.size = 1
  }
}
```

Driver 官方明确提示“不要像 JDBC 池一样调优”，并建议只有在具体性能数据证明需要时才修改这些值。将 `max-requests-per-connection` 调高到 1024 以上通常没有明显收益，因为服务端最终只能同时处理有限工作；想限制 Session 全局吞吐应使用 throttler，而不是降低每连接 stream 数。[Driver 4.17 连接池配置与调优](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/pooling/index.html#configuration)

连接池在 4.x 中是固定大小，不会根据当前负载自动扩缩；配置可以热更新。默认 1 条连接通常足够，官方给出的“可能需要更多连接”的典型信号是极高吞吐时单条连接对应的 Driver I/O 线程打满一个 CPU core，同时整体系统资源尚未打满。[Driver 4.17 连接池调优](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/pooling/index.html#number-of-connections-per-node)

## 3. “连接不够时排队”应该怎么做

### 3.1 连接池本身不是排队器

默认 `PassThroughRequestThrottler` 不做节流，也不排队。如果所有连接的 stream id 都耗尽，Driver 会尝试查询计划中的其他节点；全部节点都忙时，最终得到 `AllNodesFailedException`，各节点错误为 `BusyConnectionException`。[Driver 4.17 请求节流：Pass through](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/throttling/index.html#pass-through)

因此，不应依赖“连接池自动排队”。连接池容量是协议槽位；背压是另一个显式策略。

### 3.2 使用有界并发 throttler

如果业务需要“数据库忙时短暂排队”，Driver 4.17 内置的 `ConcurrencyLimitingRequestThrottler` 正好表达这个策略：

```hocon
datastax-java-driver {
  advanced.throttler {
    class = ConcurrencyLimitingRequestThrottler
    max-concurrent-requests = 32
    max-queue-size = 64
  }
}
```

上面的 `32/64` **不是官方通用推荐值**，而是结合本仓库当前 `max-active-loops=32`、单节点 `--smp=1 --memory=1G` 的保守压测起点：先把 Scylla 同时执行的应用请求控制在 Agent 主并发同一量级，并只允许约两批请求短暂等待。正式值应由目标 P95/P99 延迟、超时和 Scylla 指标压测得出；如果后台归档/恢复任务也共享同一 Session，需要把它们计入容量或为工作负载设置单独的上层并发预算。

`max-queue-size` 达到上限后，Driver 抛 `RequestThrottlingException`，这正是有界过载保护。排队时间计入 `session.execute()` / `executeAsync()` 的请求超时，因此队列不能大到让请求几乎必然超时。[Driver 4.17 并发节流](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/throttling/index.html#concurrency-based)

配置容量还必须满足：

```text
max-concurrent-requests
  < 可连接节点数 × 每节点连接数 × max-requests-per-connection
```

并留出安全余量，因为重试和推测执行会消耗额外 stream id。否则请求会先碰到 `BusyConnectionException`，根本进不了预期的 throttler 排队路径。官方建议持续观察 `pool.available-streams`，确保不降到 0。[Driver 4.17 并发节流](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/throttling/index.html#concurrency-based)

### 3.3 排队不是无限等待，也不是无限重试

过载处理建议分层：

1. Agent 自身的 `max-active-loops` 先限制业务并发；
2. Driver throttler 再限制共享 `CqlSession` 的数据库并发，并提供一个小的有界等待区；
3. 队列满、Driver 超时或 Scylla 返回 overload 时快速失败，映射为 API 的可重试错误；
4. 只有请求明确幂等时才允许有限重试，并使用抖动退避；不要在业务层无界重试。

Driver 4.17 默认重试策略最多重试一次，且只有幂等请求才进入相关重试路径。`basic.request.default-idempotence` 默认是 `false`；语句可逐条 `setIdempotent(true)`。对于写入，超时意味着无法确定变更是否已经应用，因此不能随意重试。[Driver 4.17 重试](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/retries/index.html)；[Driver 4.17 幂等性](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/idempotence/index.html)

## 4. 本仓库现状

### 4.1 已经正确复用一个 Session

`java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/config/AgentSessionPersistenceConfiguration.java` 声明了一个 Spring `CqlSession` Bean。所有 Scylla Store 注入并共享该 Bean，没有逐请求创建 Session。这正是 Driver 推荐的长生命周期使用方式。

`java_agent/rs-service-agent/pom.xml` 固定使用 `com.datastax.oss:java-driver-core:4.17.0`。当前 Builder 没有传 `DriverConfigLoader`，资源目录也没有 `application.conf`，因此连接池和 throttler 使用 Driver `reference.conf` 默认值，即每节点连接池大小 1、每连接最大并发 1024、throttler 为 pass-through。Driver 默认配置系统会读取 classpath 上的 `application.conf` / `application.json` / `application.properties`，但**不会把现有 Spring `application.yml` 的 `rs.agent.*` 自动映射成 Driver 配置**。[Driver 4.17 配置加载](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/configuration/index.html#default-implementation-typesafe-config)

### 4.2 当前部署其实是标准 CQL 端口，不是 shard-aware 端口

`java_agent/deploy/remote/infra/docker-compose.yml` 使用：

```yaml
ports:
  - "127.0.0.1:${RS_SCYLLA_HOST_PORT:-19042}:9042"
```

这里宿主机的 `19042` 被映射到容器标准 CQL 端口 `9042`。虽然 ScyllaDB 官方的高级 shard-aware 端口默认也叫 `19042`，但本 Compose **没有暴露容器的 19042**；当前依赖也是通用 DataStax Driver 4.17，不应因为宿主机端口数字相同而误判为已启用 shard-aware 连接。[ScyllaDB 端口配置](https://docs.scylladb.com/manual/stable/reference/configuration-parameters.html#native-shard-aware-transport-port)

当前 Scylla 参数为 `--smp=1 --memory=1G`，即单节点单 shard 的开发资源。此时 shard-aware 路由本身没有多 shard 可优化，没必要为了它先增加连接复杂度。

### 4.3 当前查询方式会阻塞调用线程，但不会独占连接

`ScyllaAgentTranscriptEntryStore`、`ScyllaAgentTranscriptCheckpointStore`、`ScyllaAgentMemoryItemStore` 和 `ScyllaAgentColdSessionArchiveStore` 都调用同步 `cqlSession.execute(...)`。同步 API 会阻塞当前应用线程等待结果，但底层连接依然由异步原生协议复用，并不是“一个 Java 线程占一条 TCP 连接”。Driver 官方说明其内部几乎完全异步，只有同步包装 API 会阻塞调用方。[Driver 4.17 并发模型](https://docs.datastax.com/en/developer/java-driver/4.17/manual/developer/common/concurrency/)

Spring 已开启虚拟线程，因而同步调用的线程成本比平台线程低；但虚拟线程不会降低数据库负载，所以仍需要在高并发场景设置数据库层并发预算。

### 4.4 SimpleStatement 是比连接数更靠前的优化点

当前 Store 每次用 `SimpleStatement.newInstance(...)` 执行固定 CQL。ScyllaDB 官方 FAQ 明确建议 Java 客户端使用 PreparedStatement，因为 SimpleStatement 默认不能提供 token-aware 路由所需的路由信息；Driver 也建议缓存固定查询的 PreparedStatement。[ScyllaDB FAQ：SimpleStatement](https://docs.scylladb.com/manual/stable/faq.html#using-the-java-driver-simplestatements-are-slow-why-does-this-happen)；[Driver 4.17 性能建议](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/performance/)

当前单节点部署暂时看不到跨节点路由收益，但 PreparedStatement 仍是扩容前应完成的基础改造。

## 5. 针对本项目的分阶段建议

### 现在：不要新造连接池

- 保持一个共享 `CqlSession`，不要每个请求/每个 Session 创建新的 `CqlSession`。
- 保持 `pool.local.size=1`、`max-requests-per-connection=1024` 默认值；在没有 `pool.available-streams` 接近 0 或 Driver I/O 单核打满证据前，不增加连接。
- 将固定 CQL 改为启动时 prepare、运行时 bind，并为确实幂等的语句显式标记幂等性。

### 需要过载保护时：加 Driver 有界 throttler

- 通过 classpath `application.conf`，或在现有 `CqlSession.builder()` 上传入 programmatic `DriverConfigLoader`；若希望继续由 `rs.agent.session-persistence.*` 统一配置，后者更容易接入 Spring Properties。[Driver 4.17 编程式配置](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/configuration/index.html#programmatic-application-config)
- 压测起点可用 `max-concurrent-requests=32`、`max-queue-size=64`；这只是与当前 Agent 上限对齐的项目初始值，不是生产定值。
- 显式设置请求超时，并保证它小于上游 HTTP/Agent Turn 的剩余超时预算；队列等待也在该超时内。
- 捕获 `RequestThrottlingException`、`DriverTimeoutException`、`AllNodesFailedException`/`BusyConnectionException` 和 `OverloadedException`，区分“本实例排队已满”“Driver 连接槽位耗尽”“服务端过载”，向上层返回可重试但非无限重试的错误。

### 监控后再调参

至少观察：

- 节点级：`pool.open-connections`、`pool.in-flight`、`pool.available-streams`、`pool.orphaned-streams`；
- Session 级：`throttling.delay`、`throttling.queue-size`、`throttling.errors`；
- 应用级：CQL 请求成功率、P50/P95/P99、超时、按语句/读写分类；
- ScyllaDB：每 shard 的读写延迟、队列/调度、CPU、内存、cache、overload/load shedding 相关指标。

Driver 指标默认关闭，需要显式开启。[Driver 4.17 连接池监控](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/pooling/index.html#monitoring)；[Driver 4.17 throttler 监控](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/throttling/index.html#monitoring)

只有出现以下证据时才考虑把 `pool.local.size` 从 1 增加到 2：

- `pool.available-streams` 经常接近 0；或
- 单条连接对应的 Driver I/O 线程打满 CPU，而应用整体、网络和 ScyllaDB 尚有余量；或
- 使用多 shard 的生产节点并迁移到 ScyllaDB shard-aware Driver 后，按该 Driver 的官方连接策略重新压测。

## 6. 对问题的直接回答

**有资源和并发限制，但不是一个通用固定的“最多 N 个数据库连接”。你现在已经通过一个 `CqlSession` 获得了 Driver 内置连接池，不需要再造连接池。可以排队，应该使用 `ConcurrencyLimitingRequestThrottler` 做“小而有界”的等待队列；队列满就快速失败。当前单 shard/1 GB、最多 32 个活跃 Agent loop 的环境，先保持 1 条数据连接和每连接 1024 请求的默认值，若要保护 ScyllaDB，可从 32 并发、64 排队开始压测，而不是先增加连接数。**

## 官方资料

- [ScyllaDB FAQ：内存、连接数建议、PreparedStatement 建议](https://docs.scylladb.com/manual/stable/faq.html)
- [ScyllaDB 配置参数：CQL 端口、每 shard 并发和新连接初始化节流](https://docs.scylladb.com/manual/stable/reference/configuration-parameters.html)
- [DataStax Java Driver 4.17：Connection pooling](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/pooling/index.html)
- [DataStax Java Driver 4.17：Request throttling](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/throttling/index.html)
- [DataStax Java Driver 4.17：Configuration](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/configuration/index.html)
- [DataStax Java Driver 4.17：Retries](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/retries/index.html)
- [DataStax Java Driver 4.17：Query idempotence](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/idempotence/index.html)
- [DataStax Java Driver 4.17：Performance](https://docs.datastax.com/en/developer/java-driver/4.17/manual/core/performance/)

