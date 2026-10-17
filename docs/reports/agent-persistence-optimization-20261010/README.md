# 完整推荐流程：存储与历史读取优化验收（2026-10-10）

已实现并验收：显式 MySQL 连接池、会话投影短事务、推荐商品批量写入、Redis 事件追加与 TTL 合并，以及同轮权威历史复用。最终版本预热完整接口 **775–802ms**，8 用户预热并发 **1179–1347ms**，浏览器完整展示 **870–1363ms**。**仍未达到完整推荐 300ms。**

## 实现及功能边界

- Agent、Recommend 自定义数据源改为受 Spring 生命周期管理的 HikariDataSource。每个服务实例默认最多 8 个连接、最少 2 个空闲连接、获取连接超时 3000ms；Compose 和 `.env.example` 提供独立配置。
- Agent 同一语义事件对应的 Session、Turn、可选工具投影共用一个连接和短事务；Checkpoint 投影也按一次原子操作提交。使用 JdbcTemplate 与 TransactionTemplate 参与 Spring 事务，避免直接 getConnection 导致连接不共享。原来快速路径 4 条事件对应至少 8 次独立建连/提交，现在是 4 次短事务，物理连接可复用。
- 推荐交付头与商品仍在原事务中保存，商品使用参数化多行 INSERT。保留所有商品、排名、属性、交付 ID 与反馈归因；没有调整反馈事件、偏好版本和 Outbox 的事务边界。
- Redis 事件追加和 TTL 更新用同键短 Lua 完成，保留完整事件内容和现有过期策略。Redis 仍可从 Scylla 权威历史恢复。
- 对带 client_turn_id 的请求，复用幂等检查已经读到的完整权威历史，供检查点尾部过滤、首轮判定、既有 Turn 视图和下一事件序号使用。复用范围只在当前 Session Execution Lane；没有把客户端参数或空 Redis 当作首轮依据。无 client_turn_id 和自定义恢复实现保留原回退行为。

所有语义事件仍先写 Scylla，再更新 MySQL、Redis；最终 Scylla 记录成功后才发送成功 done。没有修改一致性级别、落盘参数、候选数量、模型权重、价格保护、品类保护、普通 Agent 回退或前端业务逻辑。本轮未实现后台异步投影、BGE pair 缓存或跨请求微批。

## 同环境前后对照

基线和优化版都开启已有直接推荐与计算缓存，都使用真实 Gateway 鉴权、User Session、Milvus 语义召回、Catalog、训练排序、96 候选 BGE、MySQL 交付、Scylla 会话事实和 Redis 状态。问题为“推荐鼠标”，每次新建 Session，返回 5 个真实商品；不同请求保留独立交付。账号/Session 创建不计入单轮耗时，最终商品详情查询计入。

| 测量 | 样本数 | 完整耗时范围 | 样本中位数 |
|---|---:|---:|---:|
| 存储优化前，预热单请求 | 8 | 1155–1332ms | 1205ms |
| 连接池＋短事务＋商品批量＋Redis 合并，预热单请求 | 8 | 689–961ms | 766ms |
| 存储优化前，8 用户预热并发 | 8 | 1896–2207ms | 2110ms |
| 存储优化后，8 用户预热并发 | 8 | 1142–1389ms | 1241ms |
| 再加入同轮历史复用，预热单请求 | 4 | 775–802ms | 787ms |
| 最终版本，8 用户预热并发 | 8 | 1179–1347ms | 1344ms |
| 最终版本，真实 Edge 浏览器完整展示 | 3 | 870–1363ms | 1358ms |

同环境存储改动组的预热单请求中位数下降约 **36%**，8 并发中位数下降约 **41%**。单请求交替测前后版本，并发先逐画像预热再测。多个存储改动组成一组，这些结果不能拆成各个改动的独立收益。同轮历史复用没有显示明确的额外延迟改善，不能把读次数减少直接换算成毫秒收益。

这是明确首轮品类需求的快速推荐，不代表任意复杂需求、多轮对话、首页多路召回或所有品类。8 并发使用同一 query，两个 Recommend 的计算缓存各有 1 次 miss、24 次 hit（存储对照结束时）；不能代表 8 个不同冷 query，也不是最大 Agent 并发量。样本较少，不报告生产 P95/P99。

最终 Agent 重启后第一个有效完整请求为 1928ms，单独列出，没有混入预热结果。模型冷启动阶段的两个先导完整请求为优化版 3470ms、基线 2590ms，先后顺序及 GPU 模型初次调用不同，不能用于冷启动速度对照。另外，替换最终 Agent 后过早调用一次网关得到 HTTP 500，发生在服务未就绪时；本轮记录这次启动失败，不纳入稳态耗时/完成率。替换脚本现已加入健康就绪等待。

浏览器使用当前 React 前端、真实 Edge 与 SSH 转发网关，关闭 mock，计时至回答、所有商品详情、5 张卡片和两次 animation frame 完成。包含网络、Vite 代理和现有浏览器探针等待，不包含外部商品图片全部下载完成。

## 正确性与资源核验

核验 **63 个完整接口请求**，全部返回 5 个真实商品、独立交付、非降级训练排序与 96 候选 BGE、正确的最终历史。3 个浏览器样本另行保存。抽检 Scylla 保存 USER_MESSAGE、两个 ASSISTANT_MESSAGE 和 ASSISTANT_FINAL，seq 为 1–4；MySQL Session last_seq=4、Turn first_seq=1/last_seq=4。

重复 client_turn_id 返回相同完整结果、同一交付 ID，不新增历史。真实反馈 APPLIED，重复反馈保持同一反馈 ID。Redis 事件 TTL 有效；删除事件/快照热键并重启 Agent 后，历史与重试结果完全相同。

最终 Java 回归：Agent 206 项（205 通过、1 跳过），Recommend 104 项全部通过。新增检查覆盖物理连接复用、短事务连接共享和失败回滚、批量交付顺序与独立身份、检查点过滤、重试及事件序号。H2 用于事务机制测试；实际 MySQL SQL 与完整业务语义由真实链路验收覆盖。

GPU 1 使用本地 BGE FP16、batch 64、显存比例 0.11，与现有 Qwen 共享 RTX 4090；没有重启或调整 vLLM，原 4096 上下文/显存比例 0.85 保持不变。GPU 0/2 训练未改动。QA 使用独立 MySQL 数据库/用户、Scylla keyspace、Redis 和业务端口，原目录/画像只读。结束删除 QA 资源和凭据、停止独立 BGE，恢复此前停机的 6 个项目基础容器；GPU 1 回到 20257MiB，模型健康检查 200。

代码与本地构建产物已更新；本次测试使用独立容器，正式业务服务仍保持测试前状态。

## 剩余瓶颈与后续顺序

最终浏览器样本对应一个 Agent 记录仍约 699ms：恢复及路由 111ms、推荐 158ms、回答处理 217ms、收尾 128ms；阶段之外尚有约 82ms。匹配推荐日志的交付保存约 97ms，BGE 缓存约 0.27ms。阶段日志尚未将建连、SQL、commit、Scylla、Redis、生命周期通知逐个拆开，不能断言这些时间全部是 fsync。

下一步先细分持久化与 Session 生命周期通知耗时，再评估按 Turn 合并派生投影或可靠后台投影：需要持久水位、幂等、重放、滞后修复及崩溃恢复，最终权威提交仍先于成功。不同冷 query 的并发另测 BGE pair 缓存和有界微批。原 Agent 的 4096 上下文兼容问题和 SSE 总超时问题仍属于独立待完善事项，不能通过当前快速路径成绩当作已修复。

## 证据与复跑

- [汇总](summary.json)、[同环境对照原始请求](comparison.json)、[最终版本原始请求](final-matrix.json)、[正确性核验](audit.json)。
- [浏览器原始结果](browser-final.json)、[浏览器截图](browser-final.png)、[环境元数据](environment-evidence.json)、[恢复确认](restoration.json)。
- [构建与产物校验](validation.json)、[基线校正](baseline-control.json)、[Agent 最终阶段日志](agent-fast-final-timings.log)、[Recommend 最终阶段日志](recommend-fast-final-timings.log)。
- [隔离环境](environment.py)、[接口探针](probe.py)、[前后对照](compare.py)、[正确性脚本](audit.py)、[浏览器探针](browser.cjs)、[替换并等待就绪](replace_fast.py)。

基线校正使两边使用相同的非本轮工具执行器 class，避免工作区先前未编译改动干扰对照；实际基线控制产物 hash 以 baseline-control.json 为准。存储对照的其余业务 class 差异仅为本轮 6 个 Agent 存储 class 和 2 个 Recommend class。最终阶段另外加入历史复用相关 class。

脚本包含本次固定临时根目录及端口。环境已经清理，复跑必须重新分配根目录、端口、凭据、资源预算和基线/最终产物；不能直接复用已清理 state，也不能把历史 PID 当作当前进程。研究依据与更大架构方案见 [上一轮调研](../agent-recommendation-e2e-20261010/optimization-research.md)。
