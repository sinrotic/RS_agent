# 首页个性化与服务收口

> 2026-09-08 后续修复：ID 不同仍可能是同款变体，已补内容去重、兴趣轮换和真实探索席位。当前换批行为与证据见 [修复记录](2026-09-08-home-refresh-content-diversity.md)。

用户已要求补齐首页画像召回、真实排序、多样化与曝光去重、反馈召回、效果验收和对话入口一致性。域名由用户明确延后，本轮继续使用本地 SSH 转发入口。

## 实施与验收

- [x] User 提供真实正向历史；首页依据 Catalog 回填后的历史与明确喜欢生成召回查询。
- [x] 接入现有 BGE-M3 / Milvus 语义召回，Catalog 分类探索补充候选；模型失败时显式降级。
- [x] BGE reranker 真实分数进入首页最终排序；反馈规则、多样性保护与近期已交付／曝光排除共同生效。
- [x] 换批与反馈刷新使用不同语义；游标验证账号、画像、会话归属。
- [x] 普通聊天与流式聊天共用 Agent Loop、会话执行通道和持久记录。
- [x] 单测、真实 Gateway / 浏览器效果验收、有限并发与隔离故障恢复测试。
- [x] BGE 运行进程加入自动恢复管理，部署备份、发布摘要与回滚说明。

## 实测结果

本次已部署 User、Catalog、Recommend、Agent 四个服务和前端。七个服务健康检查均为 `UP`，本地 SSH 转发入口 `http://127.0.0.1:18088/` 返回 HTTP 200。四个部署 JAR 的 SHA-256 与本地构建产物一致。

| 验收 | 结果 |
| --- | --- |
| 后端单测 | User 24、Catalog 18、Recommend 75、Agent 144，合计 261 项通过 |
| 前端单测 | 7 个文件、21 项通过 |
| 两个真实历史画像 | 均经过语义召回与 BGE 排序，首屏重叠率 0，分别覆盖 3 和 5 个 Catalog 类目 |
| 连续换批 | 三批 18 个商品不重复；新建会话仍排除近期交付 |
| 反馈 | 喜欢后召回新的相关商品；不喜欢后过滤并补满；重复提交幂等；撤销恢复偏好且保留交付去重 |
| 浏览器对话 | 普通聊天得到真实模型回答；SSE 正常完成；两个轮次均可查询 |
| 有限并发与延迟 | 最大并发 2；12 次请求 P95 2060.4 毫秒，包含双并发六次请求 |
| 隔离故障 | 模型失联时明确降级到 Catalog；独立 Redis 停止时反馈持久化为 PENDING，恢复后约 1.04 秒变为 APPLIED |
| Agent 重启 | 约 8.91 秒恢复就绪；两个轮次内容不变；其他画像读取返回 404 |
| BGE 进程故障 | SIGKILL 后 systemd 自动恢复，约 21.14 秒重新健康 |

验收同时修复了 Catalog 类目扫描慢查询、通用商品元数据误加兴趣分、Agent 重复工具调用耗尽轮次，以及部署库旧版会话表缺少投影列的问题。类目查询改为覆盖索引取 ID 后回表，实测八个类目 24 个商品约 143 毫秒。Agent 最后一轮收束为最终回答，仍保留真实工具结果和执行记录。

指标由 Recommend 的 `/actuator/metrics` 提供：`rs.recommend.home.latency`、`rs.recommend.home.candidates`、`rs.recommend.home.category.coverage`，发生降级时增加 `rs.recommend.home.degraded`。当前已验证前三者包含真实请求样本。

## 发布、证据与回滚

服务器根目录为 `/home/luo/RS_agent_java`：

- `releases/20260907-personalized-home/`：本次四个 JAR、前端 dist、迁移 SQL、验收脚本与结果。
- `personalized-home-acceptance.json`：画像差异、反馈召回、跨会话去重、有限并发与延迟。
- `isolated-feedback-fault-acceptance.json`：隔离 Redis 与模型故障结果。
- `agent-session-recovery-acceptance.json`、`model-recovery-acceptance.json`：重启与异常退出恢复证据。
- `feedback-smoke-final.log`：Gateway 反馈持久化、幂等、撤销验收。
- `final-service-verification.json`、`release-manifest.json`：健康状态、实际指标与 JAR 校验值。
- `backups/20260907-personalized-home/`：部署前 JAR、前端、Compose、私有环境配置和 Agent 表备份；目录权限限制为部署用户可读写。

回滚时先停止 User、Catalog、Recommend、Agent，恢复备份中的四个 JAR 和前端 dist，再启动服务并检查健康、登录与首页。需要回滚容器配置时使用同一备份中的 Compose 和原 override；不要覆盖其他服务或私有环境变量。新增索引和会话投影列为增量兼容迁移，可以保留；不要把旧数据库备份直接覆盖到已有新反馈的库上。恢复后按实际文件重新生成发布清单。

BGE 已使用用户级 `rs-bge-runtime.service`，启用 linger 和自动重启。部署方法与验收命令见 [远端部署说明](../../../java_agent/deploy/remote/app/README.md)，路由设计见 [ADR-0018](../../adr/0018-personalized-home-recommendation-route.md)。

## 边界

仅使用已存在的 Catalog 商品事实和语义索引，不晋级未经门禁验证的双塔或实验 pool500 产物。现有语义索引为 1024 维 COSINE，已加载，321536 行；Catalog 约 887002 行，覆盖仍不完整，由 Catalog 类目召回与探索补充。相关性验收使用商品类目和语义分数代理指标；类目标签不完全统一，不等于主题多样性或线上 CTR 提升。

当前仅部署一个 Recommend 和一个 Agent 实例。同画像生成与交付写入使用实例内串行化；水平扩展前仍需跨实例协调。上述延迟只代表本次有限样本，不构成生产容量结论。

故障注入使用隔离服务连接，没有停止共享 Redis，也没有执行整机重启。验收偏好均已撤销并登出，测试账号及审计事件保留。域名和 HTTPS 按用户要求延后；本地入口依赖 SSH 转发保持运行。
