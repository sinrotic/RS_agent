# 完整推荐耗时归因与 NVMe 对照评测（2026-10-10）

当前预热推荐的主要瓶颈是 **MySQL 写入与事务提交**。原 MySQL 数据目录实际位于机械盘 `/dev/sdb`，单请求中 4 次 Agent 投影提交平均耗时 **421ms**。加上推荐交付提交和 User Session 准入 SQL，约占 Agent 总耗时 **79%**。

使用独立 NVMe QA MySQL、保持业务构建和落盘设置后，**关闭计时探针的完整推荐为 188–210ms，中位数 197ms**；8 用户并发为 **288–354ms，中位数 317ms**。本次已验证明确品类需求、计算缓存命中的快速推荐具备进入 300ms 的条件；尚不能承诺全部对话、冷计算或稳定 8 并发均低于 300ms。

## 测量范围与方式

计时从真实 Gateway 的 SSE 请求发送开始，至完整回答成功 done、所有最终商品详情查询完成。账号注册和新 Session 创建在计时之前；本次没有新增浏览器渲染测量。

使用真实鉴权、User Session、Milvus、Catalog、训练 DeepFM、96 候选 BGE、MySQL 交付与投影、Scylla 权威事件和 Redis 热状态。单请求问题为“推荐鼠标”；每次新 Session、独立交付，返回 5 个真实商品。先逐用户预热，再测 8 个单请求与 8 用户并发。

可移除的 Java Agent 只记录匿名方法名、调用树、时间和失败标志，不记录参数、SQL、凭据或回答内容。通过 JDBC 驱动拆出 SQL 执行、commit、setAutoCommit 和 Hikari 借连接时间。调用树的互斥时间严格闭合；HTTP 外层时间与服务内部 SQL 不重复相加。

`detailed` 是包含完整 JDBC 操作计时的最终探针。先导 `profiled` 探针因转换过程加载 JDBC 类而漏计 Statement 方法，已经修正；其 JDBC SQL=0 不代表 SQL 没有耗时，**不用于 SQL 归因结论**。报告中的关键调用树折叠了访问器等细小调用，时间计入最近保留祖先；[折叠校验](profile-pruning.json) 保存原始文件 hash、节点数量及闭合结果。

## 原环境的关键路径

以下为 `detailed` 的 8 个预热单请求均值，Agent 内部总耗时约 786ms，完整接口约 802ms。表中各行互斥。

| 操作 | 平均耗时 | Agent 内部占比 |
|---|---:|---:|
| Agent 会话投影：4 次 MySQL commit | 420.5ms | 53.5% |
| User Session 准入 SQL，包含自动提交更新 | 98.0ms | 12.5% |
| User 准入 HTTP 的其余时间 | 6.6ms | 0.8% |
| 推荐交付事务，包含头与 5 商品批量写入 | 139.3ms | 17.7% |
| 推荐其余计算及 HTTP | 80.6ms | 10.3% |
| Scylla 操作 | 10.6ms | 1.3% |
| Redis 操作 | 10.4ms | 1.3% |
| Agent 其余操作 | 19.8ms | 2.5% |

推荐交付内部平均 commit **98.0ms**、SQL **38.8ms**。因此仅 5 次显式 commit 与 User 准入 SQL 的逐请求占比均值就达 **78.7%**。commit 是 JDBC 调用等待时间；未直接测量服务器内部 fsync 系统调用，不能把这段时间全部等同于单个 fsync。

Agent 执行 8 条 SQL 的总时间只有 **6.0ms**，借连接共 **0.22ms**；Recommend 借连接 **0.39ms**、User **0.06ms**。单请求继续扩大连接池不会解决当前主要等待。8 并发时，Agent/Recommend 借连接均值升至 **40/61ms**，推荐 SQL 升至 **342ms**，交付事务整体约 **546ms**，数据库突发等待明显放大。

预热 BGE 缓存评分约 **0.37ms**，DeepFM HTTP 约 **7.7ms**。推荐多样性选择约 **38ms**，是移除存储瓶颈后值得继续优化的 CPU 操作。快速路径本身不调用 Qwen 生成完整回答；不能用这组结果代表普通 Agent 推理速度。平台 Trace HTTP 由虚拟线程异步提交，不属于主请求的同步 HTTP 等待。

## NVMe 对照结果

创建同版本 MySQL **8.0.45** 的独立 QA 实例，将本次 17 张自有测试表复制到 `/tmp` 所在的 NVMe `/dev/nvme0n1p4`。Agent、Recommend、User 的写入连接切到该实例；Catalog 等原有读取路径继续使用原读库。

两边均保留 `innodb_flush_log_at_trx_commit=1`、`sync_binlog=1`、binlog 开启、`innodb_flush_method=fsync`、doublewrite 开启。业务 Agent/Recommend JAR hash 相同。NVMe 实例限制 1GiB 内存、4 CPU、256MiB buffer pool。本对照同时包含独立实例、缓冲池和数据布局差异，不能解释为只换磁盘的严格因果分解；实际 commit 等待下降及端到端收益共同支持优先优化存储。

| 场景 | 样本数 | 完整耗时范围 | 中位数 |
|---|---:|---:|---:|
| 原机械盘，关闭探针，预热单请求 | 8 | 680–907ms | 790ms |
| NVMe，关闭探针，预热单请求 | 8 | **188–210ms** | **197ms** |
| 原机械盘，关闭探针，8 用户并发 | 8 | 1227–1533ms | 1402ms |
| NVMe，关闭探针，8 用户并发 | 8 | **288–354ms** | **317ms** |
| 原机械盘，最终探针，预热单请求 | 8 | 701–901ms | 814ms |
| NVMe，最终探针，预热单请求 | 8 | 207–273ms | 215ms |
| 原机械盘，最终探针，8 用户并发 | 8 | 1233–1727ms | 1595ms |
| NVMe，最终探针，8 用户并发 | 8 | 299–371ms | 347ms |

关闭探针的单请求中位数下降约 **75%**，8 并发中位数下降约 **77%**。探针与阶段先后也会影响成绩：NVMe 开启探针的单请求中位数高约 9.5%；原环境的并发两组波动也明显。因此最终端到端结论采用关闭探针的成绩，细分计时用于判断主要等待位置，不承诺这些均值就是生产 P95/P99。

带探针的 NVMe 单请求中，Agent 4 次 commit 从 **421ms → 53ms**，User 准入 SQL **98ms → 12ms**，交付事务 **139ms → 30ms**；其他推荐计算及 HTTP 约 **78ms**，变化较小。此时优先级应从慢存储转向推荐 CPU、冷模型调度及突发连接准备。

服务重启后的首个有效完整请求仍为秒级：原环境关闭探针约 **2387ms**，NVMe 约 **1867ms**。这些请求包含 JVM、缓存与首次调用因素，单独列出，不能混入预热成绩。

## 冷计算、重复并发与已有失败

测试 8 个不同的简单鼠标问题，形成 8 个新的 embedding/BGE 缓存 key。NVMe 关闭探针时，6 个成功请求完整耗时 **838–2245ms**，2 个普通 Agent 回退失败。计数器为 embedding/BGE 各 **9 miss、24 hit**：包含第一个“推荐鼠标”的 miss、其后 24 次 hit 和 8 个新 query 的 miss。

原环境最终探针的不同 query 批次，BGE 阶段约 **281–1652ms**，均值约 **918ms**；query embedding 也随并发排队。当前 BGE embedding 与 rerank 共用模型锁，耗时包含 GPU 推理与等待。下一步应针对不同冷 query 评估 BGE pair 缓存、有界跨请求批处理和公平调度，保留完整候选、模型版本校验与排序质量。

正确性验收后另测 3 轮 8 并发。前两轮全部成功，完整耗时分别 **262–335ms / 262–325ms**，中位数 **322ms / 308ms**。第三轮 **7 成功、1 失败**；成功项 264–294ms，但不能宣称整轮 8 并发达到 300ms。该请求也为“推荐鼠标”，此前已执行真实反馈，说明个性化结果变化也可能使请求转入普通 Agent。

错误日志确认普通模型回退存在已有的上下文兼容问题：输入至少 **2897 tokens**，输出预算 **1200**，合计 **4097**，超过本地 vLLM 的 **4096** 上限。需要按实际输入和模型窗口分配输出预算或受控调整上下文，并验证普通、多轮和个性化回退；不能关闭品类校验强行使用快速回答。

## 正确性、环境恢复与建议顺序

共记录 **181 个新 Turn 测试请求：174 成功、7 失败**。失败由 3 组不同 query 各 2 个，以及重复并发中的 1 个组成，全部保留。143 个成功请求经主验收核验，另 31 个重复并发/预热成功请求独立核验：5 个真实商品、不同交付 ID、DeepFM 和 96 候选 BGE、无排序降级及 FINAL 历史正确。

真实 Scylla 记录 seq 1–4，包含 USER_MESSAGE、两个 ASSISTANT_MESSAGE、ASSISTANT_FINAL；NVMe MySQL Session last_seq=4、Turn first_seq=1/last_seq=4。相同 client_turn_id 返回同一完整响应与交付；反馈 APPLIED 并可去重；删除 Redis 热键并重启后从权威事实恢复同一历史与重试结果。

建议实施顺序：

1. **先把正式 MySQL 写入存储迁到 NVMe。** 做备份、完整数据校验和可回退切换，保留当前持久性要求。这是本次端到端证据最充分的方向。
2. **修复普通 Agent 的窗口与输出预算兼容问题。** 个性化和复杂输入能够触发回退，需要先确保可完成回答。
3. **优化推荐多样性选择的重复计算。** 按请求复用 token/属性特征，保持相同选择顺序与输出；约 36–38ms 是已测到的 CPU 空间。
4. **单独优化冷 query 模型队列。** 评估 pair 缓存和有界批处理，另设不同 query 与多轮质量验收。预热 200ms 不代表冷 GPU 推理也在 200ms。
5. **再测连接池预热及派生投影事务合并。** NVMe 8 并发下 Agent 借连接仍有约 25ms；先验证连接扩容与后台任务竞争。后台投影需要可靠重放、水位与修复，不能直接删掉权威记录或放松反馈事务。

本轮仅新增评测工具与证据，正式数据库尚未迁移。测试使用 GPU 1 的独立 BGE FP16 服务；vLLM 原 PID 3551299、4096 上下文、0.85 显存比例与 prefix caching 保持原配置。结束删除 QA 数据库、Scylla keyspace、Redis、NVMe 实例及私有临时数据/凭据，停止独立 BGE，6 个项目基础容器恢复原停机状态。GPU 1 回到 20257MiB，模型健康检查 200；GPU 0/2 训练持续运行。

评测始终使用上传后冻结的 JAR，存储对照的业务产物 hash 完全一致。结束检查发现本地 target 在评测过程中另有重打包：Recommend 业务 class 全部一致；Agent 仅 `VirtualThreadAgentToolUseExecutor.class` 不同，该工具执行器不参与本次成功的快速推荐路径。保留两个模块的 class hash 对照，不能把完整 JAR hash 不同写成完全相同，也不据此宣称已验收普通工具执行路径。

## 证据与复跑

- [统计汇总](summary.json)、[原环境关闭探针](control.json)、[最终细分计时](detailed-spans.json)、[NVMe 细分计时](nvme-spans.json)、[NVMe 关闭探针](nvme-control.json)。
- [主正确性验收](audit.json)、[重复并发核验](repeat-validation.json)、[重复并发请求](nvme-repeated.json)、[回退错误证据](fallback-diagnosis.json)。
- [存储挂载与设置](storage-environment.json)、[NVMe 实例设置](nvme-environment.json)、[服务连接去向](nvme-service-evidence.json)、[业务构建 hash](artifacts.json)、[Agent class 对照](agent-current-class-comparison.json)、[Recommend class 对照](recommend-current-class-comparison.json)、[环境元数据](environment-evidence.json)、[恢复确认](restoration.json)、[本轮验证](validation.json)。
- [计时 Java Agent](LatencyAgent.java)、[环境准备](setup.py)、[测量](measure.py)、[重复并发](repeat.py)、[统计](analyze.py)、[调用树折叠](prune_profiles.py)、[NVMe QA 数据库](nvme_database.py)、[实例切换](restart_services.py)、[清理](cleanup_nvme.py)。

隔离环境已清理。复跑应先分配新的 `/tmp/rs-agent-e2e-20261010-*` 根目录并检查端口，再同步更新各工具中的根目录；准备原始只读依赖、模型与业务 JAR。不能直接复用已清理 state 或历史 PID。本次没有修改业务源码，因此未重复运行 Maven；实际全链路和探针闭合校验作为本轮验证。
