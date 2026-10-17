# 训练双塔首页接入记录

部署后真实 Gateway 请求通过：候选来源为双塔 15、画像语义 30、画像类目 30、探索 21。浏览器连续三批共 18 件不同商品，不喜欢过滤补满、喜欢后找相似均通过。本机 SSH 转发断开导致的连接拒绝已恢复，访问地址为 `http://127.0.0.1:18088/`；域名与 HTTPS 继续按用户要求延后。证据见 [线上 Gateway](../evidence/2026-09-13-two-tower-live-gateway.json) 和 [浏览器](../evidence/2026-09-13-two-tower-browser.json)。验收使用独立账号；浏览器测试结束撤销反馈并登出，账号及审计记录保留。

2026-09-13，用户明确要求把已有双塔接入首页。原来线上首页只有 BGE 与 Catalog 路由：已有双塔 Provider 未注册到 Spring，用户塔客户端和向量缓存没有生产实现，默认还指向 epoch 1。现已补全并部署 Recommend、专用用户塔运行时和独立索引。

使用 `two_tower_sparse_aware_serial_checkpoints/checkpoints/epoch_5`，模型为 YouTubeDNN，64 维商品向量共 448282 条。集合为 `rs_agent_two_tower_epoch5_20260913`，模型键为 `two_tower_sparse_aware_epoch5_queryv2`。服务目录 `/home/luo/RS_agent_java/data/models/two_tower_epoch5_20260913`，模型文件 SHA256 为 `b406a0834c93e5a4f769d0cda3276f9e18e68a28082c3cdaf879a5db56c2f858`。

正向历史去重后最多 80 项；不足两项不调用双塔。匹配训练词表的商品向量按 0.85 衰减聚合并归一化，经过训练好的 64→128→64 用户 MLP、ReLU 和残差，再归一化。此路径对齐既有 queryv2；没有导入 6GB 离线用户向量，也没有重新训练。双塔最多召回 120 项，经 Catalog 回填后参与现有融合、BGE 排序、探索与换批去重。Trace 和商品 source_tags 记录真实 `two_tower` 来源；同一候选可有多个来源，因此来源计数之和可以超过去重候选数。

Java 客户端校验模型键、维度和归一化向量；连接超时 1 秒、读取超时 2 秒。缓存按模型、画像和有序历史隔离，最多 5000 项，TTL 10 分钟。CPU 运行时受 systemd 管理，内存上限 768MB，异常退出自动恢复。修复了 Java HTTP 客户端使用 chunked 请求体而 Python 初版只读取 Content-Length 导致的 400，并保留回归测试。

验证结果：Java 87 项通过；Python HTTP 回归 2 项通过。10 组固定随机历史的运行时结果与仓库 queryv2 参考实现最大绝对误差为 0；ANN 对精确 Top20 的平均召回为 0.96。最终 JAR 隔离验收涵盖五个真实画像（含之前使用的画像），每个画像均有 15 个双塔候选，其中一个首屏展示 2 个双塔商品；换批无重复、商品回填、无历史及连接故障降级均通过。运行时 SIGKILL 后 6.05 秒恢复，未执行整机重启。

最终 Recommend JAR SHA256：`4d8bdc1bf64975c821cced2ec6a55fcf308c6c037c01f4f85b3c0626e6c56279`。仅更新该服务及其四个双塔配置项；线上前端沿用现有版本。运行时在 `172.21.0.1:18117`，Recommend readiness 为 UP。部署备份位于 `/home/luo/RS_agent_java/backups/20260913-two-tower`，包含原 JAR、Compose、私有环境文件与发布 manifest。

快速退出双塔：在服务器 `app_deploy/.env` 设置 `RS_RECOMMEND_TWO_TOWER_ENABLED=false`，从该目录执行 `docker compose -p rs-agent-java-app -f docker-compose.yml -f docker-compose.override.yml up -d --no-deps --force-recreate rs-service-recommend`。完整回滚应先停止 Recommend，再恢复上述备份中的对应文件并用同一命令启动；无需数据库迁移或删除双塔集合。

证据：[推理与 ANN](../evidence/2026-09-13-two-tower-inference.json)、[真实画像与故障](../evidence/2026-09-13-two-tower-home.json)、[进程恢复](../evidence/2026-09-13-two-tower-recovery.json)、[部署](../evidence/2026-09-13-two-tower-deployment.json)、[产物范围](../evidence/2026-09-13-two-tower-serving-manifest.json)。这些验证证明链路接通及有限样本行为，不证明 CTR 提升；原预计算用户向量的离线 Recall 指标不能直接套用到当前在线 queryv2。
