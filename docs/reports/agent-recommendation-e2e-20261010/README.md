# 完整推荐流程真实验收（2026-10-10）

已经接通真实业务链路完成测量。明确首轮需求“推荐鼠标”的优化路径，稳定单请求完整接口约 **1.24–1.42 秒**，浏览器回答与 5 张商品卡片显示约 **1.37–1.90 秒**；清空计算缓存后的 8 用户并发约 **3.13–3.74 秒**。**完整推荐尚未达到 300ms。** 普通 Agent 路径仍需数秒至数十秒。

后续存储与历史读取优化已完成独立验收，最终预热完整接口约 **775–802ms**，浏览器完整显示约 **870–1363ms**；本报告保留原阶段数据，最新结果见 [存储优化验收](../agent-persistence-optimization-20261010/README.md)。

这是隔离验收环境的实测，不是已上线的正式配置，也不是可靠的生产 P95 或最大并发容量。GPU 0/2 的训练保持运行。结束后恢复原 GPU 1 模型参数及启动脚本，关闭测试前停机的基础服务，删除本次创建的数据库、keyspace、Redis 和业务容器。

## 测量范围与环境

服务器内请求从网关发送开始，经过真实鉴权、User 的 Session 归属与生命周期校验、Agent 上下文恢复、BGE 查询向量、Milvus 语义召回、真实目录事实、训练 COLD/DeepFM、96 候选 BGE 重排、推荐交付保存、最终答案处理、Scylla transcript、MySQL 投影与 Redis 热状态、最终 SSE `done`，再补齐目录商品详情才停止计时。创建账户和 Session 属于准备步骤，不计入一轮推荐耗时。

浏览器使用真实 Edge、当前 React 前端与 SSH 转发的真实网关。起点为发送前，终点为最终回答和所有商品详情就绪、5 张卡片出现并完成两次 animation frame。没有 mock API。计时包含本机到服务器的网络与 Vite 代理，不包含外部 Amazon 图片下载完毕，也不把首 token 或占位卡片计为完成。

网络位置为 Windows 开发机到服务器 10.112.125.22；测试结束后补测的 4 次 ICMP RTT 均为 1ms、无丢包，见 [网络记录](network-rtt.txt)。它不是测试每个请求时同步采集的 RTT，也不代表外网用户延迟。

本次对话是 **Milvus 语义召回场景**，trace 的 source_distribution 为 semantic；没有把首页的多路召回、ES 或双塔计入本次对话耗时。多路召回与训练排序运行时可用，语义场景确实执行 COLD/DeepFM 和 BGE。目录、画像与向量索引读取现有真实数据；账户、Session、反馈、交付和历史只写独立 MySQL 数据库、Scylla keyspace 和 Redis。MySQL 原数据只授予 SELECT。

GPU 1：RTX 4090；BGE FP16、batch 64、PyTorch fraction 0.11；Qwen3.5-4B BF16、未量化、prefix caching。现有 4096 上下文会使完整 Agent 请求报错，所以有效对照临时使用 16384 上下文和 vLLM 显存比例 0.78，结束恢复 4096 / 0.85。基线与优化使用相同临时模型和业务依赖，Java heap 均为 768MiB。基线关闭直接推荐与计算缓存，优化开启二者。基线也使用同一个 GPU BGE 运行时，因此这不是原 CPU BGE 与新 GPU BGE 的全套对比。

## 真实结果

各档样本少，报告范围与样本数，不估计生产分位数。

| 测量 | 样本 | 完整耗时 | 完成情况 |
|---|---:|---:|---|
| 优化路径、已预热、单用户新 Session | 4 | 1.236–1.425 秒 | 4/4 |
| 优化路径、Agent 服务首请求，计算缓存已存在 | 1 | 2.569 秒 | 1/1 |
| 优化路径、已预热、8 用户并发 | 8 | 1.714–2.021 秒 | 8/8 |
| 另一档已预热 8 用户并发 | 8 | 1.824–2.336 秒 | 8/8 |
| 清空 Recommend 计算缓存、8 用户同时发同一查询 | 8 | 3.128–3.743 秒 | 8/8 |
| 浏览器优化路径、最终回答与 5 张卡片 | 3 | 1.370–1.898 秒 | 3/3 |
| 原 Agent、单用户新 Session | 2 | 9.830–23.024 秒 | 2/2 |
| 浏览器原 Agent、最终回答与 5 张卡片 | 2 | 9.075–25.446 秒 | 2/2 |
| 原 Agent、8 用户并发 | 8 | 成功请求 23.002–30.137 秒 | 3/8；其余 5 个约 30.9 秒断流 |
| 优化开启但“推荐耳机”回退到 Agent | 1 | 11.537 秒 | 1/1 |

8 用户冷缓存测试是同一个精确查询、不同真实画像和独立 Session。缓存指标实际为 embedding 与 BGE 各 1 miss / 7 hit，包含同键计算合并，**不是 8 个不同新查询的完全无缓存测试**。每个用户仍单独训练排序、读取偏好、创建交付与最终历史，没有共用最终推荐回答。

`optimized-cold-warm.json` 第一条为清空 Recommend 后的单请求，2.155 秒；该档与原 Agent 浏览器对照重叠运行，共享 GPU，单独标注，不当作独占 GPU 的冷请求基准。浏览器每条未同步采集缓存计数，不把它们全部标成命中。早期 `baseline-mouse-first` / `baseline-mouse-warm` 探针对最终商品字段的解析错误，未计入结果；最终探针按 `recommended_items` 发真实目录请求并校验所有 ID。

## 为什么还达不到 300ms

再次预热后的一个完整接口请求为 1.229 秒，Agent 服务端日志为 1.209 秒，其中：

| 阶段 | 耗时 |
|---|---:|
| 入场 | 2.5ms |
| 上下文恢复与路由 | 103ms |
| 推荐调用，包括独立交付 | 273ms |
| 直接最终答案处理，包括语义事件保存 | 384ms |
| 最终提交与快照 | 239ms |
| 未被上述阶段覆盖的准备与保存 | 约 207ms |

答案阶段没有调用大模型。阶段名 `answer` 也包含 journal 写入，不能解释成纯文字生成耗时。该请求 BGE embedding 和重排缓存阶段分别约 0.14ms / 0.37ms；向量检索 11.9ms，目录 7.9ms，COLD/DeepFM 8.5ms，交付保存 170.7ms。详细日志见 [Agent 分段日志](agent-fast-timings.log) 和 [推荐分段日志](recommend-fast-timings.log)。

代码中每条语义事件依次保存 Scylla authoritative entry、MySQL projection 和 Redis 热状态；首轮还恢复上下文、登记 user message，最终再存 final、热历史与快照。本次耗时说明：**继续只优化模型，不能把完整一轮压到 300ms。** 持久化、上下文恢复与分散的顺序调用需要下一阶段专门优化。

下一阶段应先补充数据库/Redis 单调用观测，核验 fsync 与连接池等待，再设计按轮次合并提交、减少重复读取和更新、可恢复投影的异步刷新，并保留 Scylla 最终提交先于成功 `done` 的边界。冷查询还需要 BGE 跨请求微批、真实长商品文本优化与安全的缓存复用。未经恢复、取消、反馈和故障测试，不能通过跳过持久化或省掉排序来宣称 300ms。

进一步核查已确认：Agent 与 Recommend 当前自定义 MySQL 数据源均未池化；快速路径 4 条会话事件会触发至少 8 次 Agent 投影 SQL 独立建连。优先显式连接池，再合并写入与复用恢复结果。官方依据、源码定位、风险与逐项 A/B 顺序见 [下一轮优化调研](optimization-research.md)。这里是代码核查结果，尚未测量新方案的性能收益。

## 正确性与实际问题

脚本核验的 40 个有效请求均有 5 个真实商品、无公开降级、独立 card_set_id、真实训练排序和 96 候选 BGE、单条 FINAL_ANSWER 历史。最终 transcript 在 Scylla 中包含 USER_MESSAGE、两个 ASSISTANT_MESSAGE 和 ASSISTANT_FINAL。反馈成功 APPLIED，重复反馈返回同一 ID。删除对应 Redis 热事件/快照并重启 Agent 后，恢复出的历史与原结果完全相同。见 [核验结果](audit.json)。后补的 3 个分段观测请求及 5 个浏览器请求另有证据。

没有把失败排除后当成全体成功：原 Agent 并发 8 时 5 个请求未收到最终 `done.response`，服务端出现 AsyncRequestTimeoutException。早期 4096 模型配置也导致完整请求失败，属于部署兼容性问题。它们均不作为有效快速回答。

真实目录标题经常 180–200 字符，原快速路径 160 字符上限让正常鼠标/键盘也回退。本次将保护上限改为 512，保留完整标题，超长标题仍回退；增加了真实长度与超上限回退验证。基线与优化 JAR 的业务 class 差异只有 AgentDirectRecommendation，基线本就关闭该路径。

快速路径仍只覆盖严格的首轮有限语法。实际“推荐耳机”会召回 Earpads 等配件，按设计回到 Agent；这证明不能把鼠标的快速结果推广到所有需求。目录还存在 Mice 叶子下的 Cable Management 商品等标注问题；本次 5 卡鼠标结果未包含该条，但 6 候选诊断中观察到了它。因此本次仅验证链路、耗时及所述持久化语义，**尚未证明推荐相关性质量门禁通过，也没有正式启用快速路径**。复杂需求、多轮、未知事实和预算币种仍保留原 Agent 处理。

## 证据与复现

- [汇总统计](summary.json)：直接从有效完成耗时计算，无最终回答单独计失败。
- [已预热接口与 8 并发](optimized-mouse.json)、[另一档冷/热接口](optimized-cold-warm.json)、[清空缓存后的 8 并发](optimized-cold-concurrent.json)。
- [原 Agent 8 并发](baseline-concurrent.json)、[单请求一](baseline-five-1.json)、[单请求二](baseline-five-2.json)、[耳机回退](fallback-headphones.json)。
- [优化浏览器](browser-fast.json)、[原 Agent 浏览器](browser-baseline.json)：记录真实卡片、最终响应与目录详情。
- [环境与 JAR 摘要](environment-evidence.json)、[清理与恢复状态](restoration.json)。
- [环境准备脚本](environment.py)、[完整接口探针](probe.py)、[浏览器探针](browser.cjs)、[正确性核验](audit.py)。脚本记录本次固定目录、容器及模型 PID；复跑需要先重新核验和分配环境，不能直接套用历史 PID。

本次标题保护修改后的 Agent Maven package 通过，200 项测试中 199 项通过、1 项跳过，详见 [构建验证](validation.json)。原优化实现与模型阶段实验见 [前一份报告](../agent-recommendation-optimization-20261010/README.md)。
