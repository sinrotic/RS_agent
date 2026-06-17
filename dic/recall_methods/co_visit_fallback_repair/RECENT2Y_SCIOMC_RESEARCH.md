# co_visit_fallback_repair recent-2y SciOMC 调研

日期：2026-06-03

## 1. 调研结论摘要

`co_visit_fallback_repair` 不应被包装成主力召回源。它更适合定位为：在 pool500 已有主召回对部分用户填充不足时，利用 **train-only 序列转移边 + 商品 metadata neighbor** 做补洞。当前项目实现的 `train_transition_metadata_repair_v0` 与论文中的完整 session graph / item-item CF 有相似归纳偏置，但证据仍不足以宣称完整 co-visit graph。

本轮调研后的落地判断：

- 保持 `TARGET_SLICE_DIAGNOSTIC` / `DEFERRED` 或最多 `DIAGNOSTIC_ONLY`，不宣称 READY。
- source 构建只能读取 recent-2y train-visible 输入，不读取 valid/test/holdout/LOPO/oracle/eval label。
- smoke 只验证 schema、manifest、七件套、no-holdout audit 和候选非零。
- formal 若要成为正式效果依据，必须在受控资源下构建 formal source，并用 evaluation-only label 报告缺口用户覆盖改善、Recall@K、source overlap、候选数和用户桶分层；不能只用 smoke 结果晋升。

## 2. 论文与工业实践要点

### 2.1 Amazon item-to-item CF：共现邻居适合做可缓存候选源

参考：Greg Linden, Brent Smith, Jeremy York, *Amazon.com Recommendations: Item-to-Item Collaborative Filtering*, 2003。

要点：

- 用大量用户历史构建 item-item 相似度，把用户在线请求转化为若干 seed item 的 nearest-neighbor lookup + merge。
- 相似关系离线计算、在线轻量查询，适合作为 candidate generation 的中间层。
- 对本项目的启发：如果要把 `co_visit_fallback_repair` 从 v0 推进到更强版本，应构建真正的 train-only item-item / co-visit graph，记录 pair support、distinct user support、热门 item 去噪和边裁剪规则。
- 对当前 v0 的限制：当前实现主要是 seed-triggered train transition 与 metadata neighbor，并未持久化完整 item-item co-visit graph，所以不能沿用 Amazon item-to-item CF 的完整能力声明。

### 2.2 GRU4Rec：session-only 场景下近期序列是强信号

参考：Hidasi et al., *Session-based Recommendations with Recurrent Neural Networks*, 2015。

要点：

- 论文强调在缺少长期用户画像时，当前 session / recent sequence 可直接用于 next-item prediction。
- 对本项目的启发：fallback repair 的主要信号应来自 train-only recent sequence，而不是跨 split 的评估命中；当前 `recent_positive_item_sequence` seed + transition window 符合这个方向。
- 对当前 v0 的限制：GRU4Rec 是学习式 session 模型；当前方法只是启发式转移边与 metadata neighbor，因此应作为补洞 source，而不是替代训练型序列召回。

### 2.3 SR-GNN：session graph 需要显式图结构和多步转移证据

参考：Wu et al., *Session-based Recommendation with Graph Neural Networks*, AAAI 2019。

要点：

- 将 session 构造成图，用 GNN 捕获复杂 item transition，而不是只看线性相邻转移。
- 对本项目的启发：若后续要升级为完整 co-visit graph，应保留 session/window 内的边、边权、归一化、support、热门惩罚，并评估多步转移带来的补洞价值。
- 对当前 v0 的限制：当前没有完整 session graph artifact，也没有 graph-level support audit，因此 `complete_co_visit_graph_claimed=false` 必须保留。

### 2.4 Session-based evaluation 研究：轻量邻居法常是强 baseline

参考：Ludewig & Jannach 等 session-based recommendation evaluation 研究（WebFetch 到的 arXiv 1803.09587 摘要）。

要点：

- 多个 session-based 数据集上，轻量 nearest-neighbor / co-occurrence baseline 往往能匹配甚至超过复杂模型。
- 对本项目的启发：`co_visit_fallback_repair` 作为轻量补洞 source 有工程合理性，尤其适合先做 diagnostic source，而不是直接上复杂模型。
- 门禁要求：必须与 popular/category/ItemCF 等已有 source 做 overlap 与增量覆盖对比，否则无法证明它是“修复缺口”而不是重复产生热门候选。

### 2.5 推荐评估可复现性：简单 baseline 与严格门禁优先

参考：Dacrema, Cremonesi, Jannach, *Are We Really Making Much Progress? A Worrying Analysis of Recent Neural Recommendation Approaches*, 2019。

要点：

- 许多复杂推荐模型的复现实验不稳定，简单 nearest-neighbor / graph baseline 常被低估。
- 对本项目的启发：当前阶段应优先保证 train-only lineage、manifest、no-holdout audit、可复核指标和 baseline 对照，而不是为了“看起来高级”强行升级方法状态。
- 晋升 READY 前必须有 formal 评估、source overlap、用户桶分层和 route gate 证据。

## 3. 对本项目数据的适配判断

recent-2y train-only governance 显示：

- profiled users：6,826,801。
- fallback_only：871,817。
- sequence_sufficient：637,338。
- collaborative_rich：49,719。
- co-visit formal target users：1,558,964（排除 cold_start，覆盖 fallback_only/medium/sequence_sufficient/collaborative_rich）。

这说明该方法确实有目标切片：大量用户不是 collaborative-rich，但有 2 条以上 train 序列，可被 train-only transition 或 metadata neighbor 补洞。风险是 fallback_only 用户的序列弱，共访边置信度不足，容易退化成 metadata/category/popular 的重复补位。

## 4. smoke / formal 数据集设计建议

### smoke

用途：程序与 schema 验证，不做正式效果结论。

建议 contract：

- target users：10,000，按 fallback_only / medium_behavior / sequence_sufficient / collaborative_rich 分桶抽样。
- 输入：`user_sequences.train.jsonl`、`canonical_interactions.train.jsonl`、`canonical_items.jsonl`、`recall_views/semantic_recall_inputs.jsonl`、`train_only_governance/user_quality_profile.jsonl`。
- 输出：七件套 source artifacts。
- 必须字段：`train_only=true`、`candidate_generation_allowed=false`、`promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`complete_co_visit_graph_claimed=false`。

### formal

用途：正式 diagnostic / route-gate 证据，不自动晋升主路。

建议 contract：

- target users：recent-2y governance 下所有非 cold_start 且有 train sequence 的 repair target；当前为 1,558,964。
- 不设置方法侧无解释小 cap；如必须分片，cap 是资源策略，不是 formal 口径改变。
- 构建前做 preflight：估计候选行数、磁盘、内存、checkpoint 可恢复性。
- 当前 builder 会在内存中累积 `rows` / `per_user`，formal 全量存在高资源风险；建议改成 shard writer + shard-level audit merge 后再远程 formal。

## 5. 构建与训练建议

本方法是非训练型 source，当前应称为“source index / 统计构建”，不是模型训练。

当前 v0 可接受构建策略：

1. 从 train sequence 抽最近 `seed_window` 个 positive seed。
2. 用 train interactions 扫描 seed 后 `transition_window` 内的 item，形成 seed-triggered transition index。
3. 用 metadata neighbor 作为兜底，避免 transition 稀疏导致空候选。
4. 合并时对已见 item 去重，限制 `candidate_per_user`。
5. 在 manifest 中保留 transition scan audit、metadata coverage、undercoverage audit、no_holdout audit。

升级到真实 co-visit graph 前，必须新增：

- pair support / distinct user support 作为 gate，而不是 follow-up-only。
- super-hot item downweight / cap。
- 边权公式与归一化，例如 co-count、Jaccard/cosine/IUF、时间窗内共现距离权重。
- 分片可恢复构建与 shard merge。

## 6. 评估建议

必须区分“整体召回”与“缺口修复”：

- smoke：候选非零率、七件套齐全、no-holdout PASS、candidate count stats、undercoverage audit。
- formal：Recall@K、用户覆盖率、平均候选数、unique item count、用户桶分层、与 popular/category/ItemCF/Swing 的 source overlap、underfilled 用户补足率。
- 如果评估器支持 item universe 分母，应报告 `full_recall_at_500`、`in_universe_recall_at_500`、`universe_positive_ratio`、`out_of_universe_miss_ratio`。
- valid/test label 只允许在 evaluation-only 阶段读取，不能进入 builder、source index 或候选过滤。

## 7. 风险与 gate

| 风险 | Gate |
|---|---|
| 用 smoke 结果冒充正式效果 | `promotion_allowed=false`；METHOD/registry 明确 smoke 只验证链路 |
| 旧 full-data artifact 回流 | registry latest_artifact 不得指向旧 sidecar 作为 current conclusion |
| 完整 co-visit graph 语义夸大 | `algorithm_scope=train_transition_metadata_repair_v0`；`complete_co_visit_graph_claimed=false` |
| metadata neighbor 退化成 category/popular 重复 | formal 必须报告 source overlap 和缺口用户新增覆盖 |
| formal 重资源导致本地失败 | preflight + remote/sharded execution；未完成则保持 DEFERRED/DIAGNOSTIC_ONLY |
| eval label 泄漏 | no_holdout_audit PASS；declared_inputs 不含 valid/test/holdout/LOPO/oracle/eval label |

## 8. 当前建议状态

在 smoke 七件套可复核、formal dry-run contract 可复核，但 formal source artifact 尚未受控构建、route gate 与互补性证据不足之前，本方法不建议晋升 READY。当前建议保持：

- registry status：`DEFERRED` 或 `DIAGNOSTIC_ONLY`（取决于全局主路收口口径）。
- source_status：`TARGET_SLICE_DIAGNOSTIC`。
- candidate_generation_allowed：`false`。
- ranking_input_replacement_allowed：`false`。
- promotion_allowed：`false`。

## Sources

- Greg Linden, Brent Smith, Jeremy York, *Amazon.com Recommendations: Item-to-Item Collaborative Filtering*, 2003 — https://www.cs.umd.edu/~samir/498/Amazon-Recommendations.pdf
- Hidasi et al., *Session-based Recommendations with Recurrent Neural Networks*, 2015 — https://arxiv.org/abs/1511.06939
- Wu et al., *Session-based Recommendation with Graph Neural Networks*, 2019 — https://arxiv.org/abs/1811.00855
- Session-based recommendation evaluation paper fetched from arXiv 1803.09587 — https://arxiv.org/abs/1803.09587
- Dacrema, Cremonesi, Jannach, *Are We Really Making Much Progress? A Worrying Analysis of Recent Neural Recommendation Approaches*, 2019 — https://arxiv.org/abs/1907.06902
