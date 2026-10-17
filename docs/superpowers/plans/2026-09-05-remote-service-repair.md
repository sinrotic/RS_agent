# 2026-09-05 远端服务修复与验收

## 最终状态

已将当前工作区的七个推荐相关 Java 服务部署到 SSH 别名 `server` 对应主机。Gateway、User、Catalog、Recommend、Agent、Model、Platform Trace 的 `/actuator/health/readiness` 均返回 200 / UP。

本次修复了此前验收发现的会话 404、Gateway 身份头缺失、反馈不落库、过滤后错误结束分页、重排 404，以及模型健康报告失真。部署过程中还发现并修复了 Model 缺少 HTTP 客户端自动配置的启动故障。

## 变更

- 重新创建容器加载新版 JAR 和 Compose 配置；原有数据库密码、Redis 密码和 Agent 模型配置保留。
- Gateway 使用 Redis token 校验；User 使用 Redis token store，实际会话创建接口已就绪。
- Recommend 使用 JDBC 权威存储及 Redis v2 在线投影，交付、反馈、Outbox、撤销删除标记均有真实 MySQL 记录。
- 部署此前完成的按商品版本、撤销幂等和分页补取修复；不喜欢过滤后仍返回 5 条，且正确保留下一页。
- Model 增加 `spring-boot-starter-restclient`，补充不注入测试替身的完整应用启动回归测试。该测试先复现缺少 `RestClient.Builder`，增加依赖后通过。
- 更新 BGE 运行时，加载现有本地 bge-m3 和 bge-reranker-v2-m3 权重。运行时使用 GPU 2，监听 `172.21.0.1:18116`；Java Model 的 embedding 和 reranking 地址都指向此处。
- GPU、端口及重排权重路径保存在远端 `model_deploy/bge-runtime.env`；启动脚本读取该文件，避免手动重启时丢失配置。
- 在新链路成功后停止了经过 PID 和命令行核对的旧 18115 embedding 进程。最终 GPU 2 显存约 4865 MiB；未修改其他项目容器。

## 真实验收

`python3 /home/luo/RS_agent_java/app_deploy/feedback_acceptance.py` 修复前在会话创建处失败，修复后输出：

```text
PASS register
PASS session
PASS home and durable delivery
PASS exposure
PASS like durability, idempotency, ranking and pagination
PASS dislike durability, idempotency, ranking and pagination
PASS reversal, restored item and durable tombstone
PASS gateway feedback acceptance
```

额外实测：

| 项目 | 结果 |
| --- | --- |
| 无效 Bearer token | Gateway 返回 401 |
| 真实 embedding | Java Model 转发成功，返回 1024 维向量 |
| 真实重排 | Java Model 转发成功，相关耳机候选排在汤勺候选之前，候选 ID 保留 |
| Model 健康 | ready_model_count=2，embedding、reranking 均 UP |
| Redis 缓存重建 | 仅删除独立验收画像及会话的两条 v2 偏好缓存；58.4 秒后从 MySQL 自动恢复喜欢状态 |
| Agent 交付 | Gateway 同步聊天返回 request_id 与 card_set_id |
| Agent 重启恢复 | 重启 Agent 容器后，会话历史条数与 request_id 保持一致 |
| 重启后跨画像访问 | 不相关画像读取验收会话返回 404，未泄露历史 |

所有验收显式偏好在结束时撤销，验收账号登出。保留验收账号、交付及反馈事件作为审计记录，没有删除既有用户数据。

本次 Redis 检查验证的是缓存丢失重建，没有停止共享 Redis，因此不能视为 Redis 整体停机下的 PENDING 恢复演练。没有执行浏览器完整交互、流式聊天恢复、整机重启或并发压测。26 ms embedding 和 76 ms reranking 是直接运行时的小样本观测，不是性能指标。

## 构建证据

- 七个部署模块首次打包：319 项测试通过。
- Model 启动回归按先失败后修复执行；修复后 Model 模块 20 项测试通过。
- BGE HTTP 契约测试：1 项通过；相关 Python 文件 Ruff 通过。
- 七个已部署 JAR 的 SHA-256 与最终本地构建逐一匹配。
- `target/surefire-reports` 存在旧诊断测试遗留文件；上述计数依据本次构建日志，不累计旧报告。

## 部署与回滚材料

远端工作目录：`/home/luo/RS_agent_java`。

- 最终版本目录：`releases/20260905-service-repair/`，已补入最终 Model JAR 和 manifest。
- 当前 JAR 校验清单：`services/release-manifest.json`。
- 回滚副本：`backups/20260905-service-repair/`，包含原 JAR、配置、运行中容器快照及本次涉及的小型权威表备份。
- `rollback-running.compose.json` 从原运行容器重建，并通过 Compose 配置校验。原磁盘 Compose 与原运行容器本就存在漂移，回滚时应使用这份运行配置快照。
- 首次上传包已标记为 `rs-service-release-20260905.initial-not-final.zip`，其中尚未包含最终 Model 启动修复；不能作为最终发布包使用。

回滚应用时先恢复原 JAR 并使用运行配置快照重建相应容器；不自动导入 `application-before.sql`，避免覆盖部署后的反馈与账号写入。若回退模型链路，需同时恢复旧模型脚本、监听地址和相应 Java 配置。

相关记录：[修复前远端验收](2026-09-05-remote-service-acceptance.md)、[本地可靠性实现](2026-09-05-service-reliability-repairs.md)。
