# 2026-09-05 服务可靠性修复记录

后续已完成远端部署，并通过 Gateway 反馈持久化、缓存重建和 Agent 重启恢复验证，见 [远端服务修复与验收](2026-09-05-remote-service-repair.md)。下文保留初次本地修复时的范围与验证记录。

## 范围与路线

按 ask-matt 的故障入口采用 diagnosing-bugs：把已有探针转成公共接口回归测试，按反馈持久化、会话归属、分页、平台观察、模型能力逐项修复。
范围是当前 Java 工作区及配套 BGE 运行时，不代表远程实例已经升级。原有未提交工作保留，不创建提交、不修改远程数据库。

## 已落实的修复

| 故障 | 修复与验证 |
| --- | --- |
| Redis 偏好无法序列化时间字段 | Recommend 显式依赖并注册 Jackson JavaTimeModule；测试完整偏好快照的写入和读回 |
| 乱序事件被画像总版本跳过 | 使用商品级版本和删除标记，画像版本取最大值；内存与 Redis 适配器执行相同行为测试 |
| 撤销重试降低版本、恢复错误状态 | 保留撤销后的商品版本，重试幂等；撤销旧反馈保留较新的有效反馈；重建走同一撤销处理逻辑 |
| 重建只处理前 1000 条 | 按 Profile User、item_id 保存扫描游标，每次最多 1000 条；失败留在未完成位置，扫描结束后下一轮从头核对 |
| 多实例覆盖 Redis 更新 | 对每个快照使用 Lua 比较更新；冲突重新读取，超过有界重试次数交回 Outbox |
| Agent 重启丢失归属和历史 | 从 Durable Session History 恢复原归属和已完成 Turn；在推荐、模型调用前校验归属；同步聊天也串行并持久化 |
| 首页过滤、重排后分页错误 | 使用目录扫描位置作为游标，独立 lookahead 判断 hasMore；有界补取过滤后的缺额 |
| 平台观察掩盖下游失败 | 平台入口仅 ADMIN/OBSERVER 可读；内部调用携带 OBSERVER；转换 Agent 的对象形式 tool_calls 为平台工具名称；调用失败返回 502 |
| 模型服务返回固定结果 | Mock 限制在 mock-models profile；默认 HTTP 适配器分别配置 embedding 和重排；未接入能力返回 503，健康检查核对能力 |

## 模型链路的更正

最初检查发现 Java Model 默认 Bean 是 Mock，但现有 `docker-compose.override.yml` 已将 Recommend 直接指向真实 BGE embedding 服务，因此不能认定远程 embedding 一直使用 Mock。
实际缺口是该运行时原先只有 `/internal/model/embed`，重排请求同址返回 404。

现在 Recommend 统一经 Model 服务调用，Model 分别使用：

- `RS_MODEL_RUNTIME_EMBEDDING_BASE_URL`：提供 `/internal/model/embed` 和 `/health`。
- `RS_MODEL_RUNTIME_RERANK_BASE_URL`：提供 `/internal/model/rank` 和 `/health`，不配置时明确不可用。
- BGE 运行时设置 `BGE_RERANKER_MODEL_PATH` 后可同时提供重排；仅加载本地模型，不自动下载。
- `/health` 的 `capabilities` 区分 `embed`、`rank`，仅进程存活不代表所有模型就绪。
- 通用 infer、rank-signals、Model chat/stream 尚无真实适配器时返回 503；Agent 现有直接模型连接保留。

CrossEncoder 初始化与预测参数核对了 [Sentence Transformers 官方接口](https://www.sbert.net/docs/package_reference/cross_encoder/model.html)。本地契约测试使用轻量运行时替身，没有加载真实权重。

## 部署与验收

1. 打包并部署相关 Java JAR 和更新后的 BGE 运行时；如启用重排，明确本地模型路径并核对资源预算。
2. Redis 新快照前缀为 `rs:pref:v2:*`，由 MySQL 在线投影重建；旧前缀不删除。首次切换期间偏好可能暂时缺失，应等待完整扫描并对照事件核验后放量。
3. 新的完全撤销保留 MySQL `current_state=none` 行作为删除标记，现有 Schema 字段无需增加。历史已经删除的投影行需在上线验收中与权威事件核对，不能仅比较在线键数。
4. 验证 like/dislike、乱序重试、撤销、重启，以及超过 1000 条记录的重建；确认 APPLIED/PENDING 与实际在线偏好一致。
5. 验证 Agent 重启后原用户可读，其他画像用户/不匹配账号在外部调用前被拒绝。
6. 验证平台角色权限、下游停机返回 502；模型缺失返回 503，embedding-only 状态不报告重排就绪。
7. 执行真实 Gateway smoke 和 Redis 故障恢复演练。MySQL SQL、Redis Lua、Scylla 与真实模型运行仍需远程联调，不能由隔离单测替代。

## 本地验证入口

```powershell
$env:JAVA_HOME='C:/Users/luo/.jdks/corretto-21.0.5'
mvn -B -f java_agent/pom.xml test
.venv/Scripts/python.exe -m pytest tests/test_bge_runtime_http.py -q
```

新增回归集中在 JacksonConfigTest、OnlinePreferenceRecoveryTest、RecommendFeedbackClosedLoopServiceTest、AgentSessionPersistenceFlowTest、DefaultHomeRecommendServiceTest、HttpPlatformTraceDownstreamClientTest、PlatformTraceAuthorizationTest 和 HttpModelGatewayServiceTest。

## 本次验证结果

- 全工程 Maven 回归：389 项通过。
- 随后补充 Model profile/真实 trace 与平台 wire 转换：Model 模块 19 项通过，Platform Trace 模块 38 项通过。
- BGE HTTP 契约测试：1 项通过；改动的 Python 文件 Ruff 通过。
- 相关工作区文件 `git diff --check` 通过。
- 未运行远程部署、真实 MySQL/Redis/Scylla 故障演练或模型权重推理；以上结果不等于生产验收。
