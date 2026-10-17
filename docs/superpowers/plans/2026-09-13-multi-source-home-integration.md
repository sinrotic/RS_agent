# 原多路召回接入 Java 首页

已完成部署和真实浏览器验收。16 个真实画像的首屏中，ItemCF weak/strong、Swing、UserCF、Category 分别有 9/3/3/6/2 次来源标记；这些是有限验收样本中的展示计数，重叠商品可有多个来源，不能解释为效果提升。冷启动候选池为 Popular 72、Catalog 探索 24；无历史协同来源均为 0。新增运行时连接失败时原首页继续返回六项并标记降级。

浏览器连续三批共 18 件不同商品，喜欢后找相似、不喜欢后过滤补满均通过。首个换批的真实线上 Trace 包含 ItemCF weak 9、strong 9、Swing 9、UserCF 9、Category 11、双塔 15。当前访问地址 `http://127.0.0.1:18088/` 返回 HTTP 200。运行时在验收后约占 11MB 内存，完整索引文件 5178322944 字节；已启用 systemd 自启动，没有执行整机重启验证。

证据：[原始产物与索引核验](../evidence/2026-09-13-multi-recall-index.json)、[产物 manifest](../evidence/2026-09-13-multi-recall-serving-manifest.json)、[16 画像与故障](../evidence/2026-09-13-multi-recall-home.json)、[发布](../evidence/2026-09-13-multi-recall-deployment.json)、[浏览器](../evidence/2026-09-13-multi-recall-browser.json)、[线上 Trace](../evidence/2026-09-13-multi-recall-live-trace.json)。

预算口径：96 是基础排序候选预算；反馈重排沿用现有实现，可另附加需要保留的当前批次商品。来源计数是实际召回命中的归因，Popular 与协同命中同一商品时会保留双重来源，即使本次没有消耗热门补量席位。

用户要求回看原方案并接入对应方法。本次以 `python_agent/dic/recall_methods/*/METHOD.md`、source registry、candidate_store 和 online_retrieval 编排为依据：商品邻居扩展行为兴趣，UserCF 补充较丰富历史，Category/Popular 提供覆盖与兜底；不把所有方法无条件堆成同一角色。

原线上断点有三处：Java 首页没有调用 Python 的多路编排；当前服务数据库的四张候选表均为空；内部诊断接口按请求预算平均生成来源数量。已有真实算法与产物不能证明部署已经调用。本次补全客户端、候选导入、首页融合、来源统计与验收。

## 接入范围

| 方法 | 实际产物与线上角色 |
|---|---|
| ItemCF weak | recent2y `src3_dst3_user2_keep_hot_cosine_v1`，16454229 条边；最近正向历史商品的广覆盖邻居 |
| ItemCF strong | `formal_relaxed_from_recent2y`，514216 条边；高置信补充 |
| Swing | `run_20260606_datawhale_f1_main_route_v1`，457372 条边；保留真实 Swing 得分 |
| UserCF | `usercf_itemfirst_src2_dst3_user3_keep_hot_full_diagnostic_v1`，64327024 个候选；至少三项正向历史且存在用户产物时补充 |
| Category | `category_recent2y_all_eligible_index_v1`，107942 个类目索引条目；使用原离线用户类目画像 |
| Popular | `popular_recent2y_formal_v1`，762622 个商品；只补兴趣候选缺口 |
| 双塔、BGE | 保留已部署的 epoch 5 双塔和现有 BGE 语义召回、排序 |
| Co-visit | 文档目标为 v2，但本机/远端找到的仍是 v0 小范围诊断切片，不作为正式路由启用 |
| 标题类目扩展 | 原方案已合并到语义路线，不新增同义独立来源 |

UserCF 等原登记仍为诊断或受限状态。本次按照用户明确授权，为 Java 首页新增有限预算的 serving 范围；不篡改旧 manifest，不声称原 pool500 路由已经正式晋级。功能、资源和有限样本贡献验收不能替代离线效果、线上 CTR 或因果增益评估。

## 服务与查询

产物目录：`/home/luo/RS_agent_java/data/models/multi_recall_20260913`。版本化 SQLite 只读索引按来源/种子/用户/类目查询，UserCF 按用户保存有序候选列表，避免把 6432 万个候选拆成高成本在线业务表写入。原 MySQL 候选表保留；本次实际使用 SQLite 运行时，不宣称已填充 MySQL。Swing 与 Popular 的正式文件从本机复制到发布目录，其余文件直接读取远端存量产物。全部文件记录哈希，建立索引并通过完整性检查后才发布 manifest。

运行时是 Python 标准库 HTTP 服务，监听 Docker 内部地址 `172.21.0.1:18118`，由 `rs-multi-recall-runtime.service` 管理，内存上限 512MB，最多同时处理 8 个查询。Java 客户端限制连接 1 秒、读取 2 秒，并验证版本、来源、数量与有限分数。

普通首页取最近正向历史并排除明确不喜欢的种子；ItemCF/Swing 要求至少两项历史，使用最近十项种子、每种子最多 40 个邻居。ItemCF 乘 0.85 的时间衰减，Swing 保留原边得分，同路同商品取最大分。Category 使用原用户类目画像前五个 bucket，其贡献按 bucket 顺序衰减。UserCF 保留离线候选得分。这里复用已计算的相似度与候选，不重新训练。

每路最多请求 80 个候选，Catalog 按每批 100 个 ID 回填，避免服务端截断后面的来源。多路交错进入最多 72 个兴趣候选位，Popular 只补该部分缺口，探索补至最多 96 个排序候选。然后使用现有 BGE、反馈调整和多样性选择。结果不强制每路展示；没有历史或未命中产物时返回空来源，不伪造候选。新增运行时故障使用 `multi_recall_unavailable` 明确标记并保留旧路由。

首页 Trace 和商品 tags 保留重叠来源，统计实际进入排序的候选；不同来源可指向同一商品，计数之和可超过去重后的候选总数。内部召回诊断按真实返回项统计，并遵守总预算。Agent 的 profilePipeline/coldFallback 复用首页服务，因此同步受益；显式语义查询工具仍执行语义检索。

## 验证与发布

Java 最终安装包 91 项测试通过，包括来源重叠、来源故障、超过 100 个商品的分批回填、96 候选上限、诊断真实数量和 HTTP Content-Length/版本验证。Python 3 项测试覆盖时间衰减、去重、已见过滤、冷启动和无效来源。完整产物计数、真实画像、部署及浏览器验证结果另存同日期 evidence JSON，以报告中的 PASS 为准。

最终 JAR SHA256：`a8d38f15c3ec59314b0b9171065662f3f2cea358884f3fd084851ed688360199`。发布脚本先校验线上仍为上一轮双塔版本、运行时健康及验收 PASS，再备份并仅重建 Recommend。备份目录为 `/home/luo/RS_agent_java/backups/20260913-multi-recall`。源码保留当前工作区的其他未提交改动，不重新部署前端。

快速回退：服务器 `app_deploy/.env` 设置 `RS_RECOMMEND_MULTI_RECALL_ENABLED=false`，执行 `docker compose -p rs-agent-java-app -f docker-compose.yml -f docker-compose.override.yml up -d --no-deps --force-recreate rs-service-recommend`。如需完整恢复，停止该服务后恢复备份中的 JAR、Compose、环境文件及发布 manifest，再启动。候选索引是独立版本，不需要删库或逆向迁移。域名和 HTTPS 仍按用户要求延后。
