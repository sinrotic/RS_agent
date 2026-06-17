# itemcf_strong recent-2y SciOMC 调研

日期：2026-06-03

## 1. 论文与工业文献依据

本轮调研优先使用能直接指导 `itemcf_strong` 落地的 ItemCF / implicit feedback 论文与工业文献：

| 文献 | 关键结论 | 对本项目的落地含义 |
|---|---|---|
| Sarwar, Karypis, Konstan, Riedl, *Item-Based Collaborative Filtering Recommendation Algorithms*, WWW 2001（公开 PDF：https://files.grouplens.org/papers/www10_sarwar.pdf） | 离线构建 item-item similarity matrix；保留每个 item 的 top-N 邻居；cosine / adjusted cosine 是核心相似度；评估除误差外还需看覆盖、效率和可扩展性 | `itemcf_strong` 应先构建 train-only item-item 边表，再由用户 seed item 查边；manifest 必须记录 similarity / topK / coverage，而不是只记录候选数 |
| Linden, Smith, York, *Amazon.com Recommendations: Item-to-Item Collaborative Filtering*, IEEE Internet Computing 2003（公开 PDF：https://www.cs.umd.edu/~samir/498/Amazon-Recommendations.pdf） | 大规模线上推荐适合把 item-item 表离线算好，服务时根据用户历史 item 查询邻居并合并；比 user-user 更稳定可扩展 | 本项目 source artifact 应是可加载的 item-item edge source；正式并入前要验证 source loader、route gate 和资源成本 |
| Hu, Koren, Volinsky, *Collaborative Filtering for Implicit Feedback Datasets*, ICDM 2008（公开 PDF重定向抓取成功：https://www.chrisvolinsky.com/publications/17546.pdf） | implicit feedback 中未观测不等于负样本；行为强度应转成 confidence；训练与评估要分离 | 本项目只能把 train 行为用于共现/置信度构建，valid/test label 只作评估；强边要考虑行为强度和噪声，不把所有未命中当负反馈 |
| Rendle et al., *BPR: Bayesian Personalized Ranking from Implicit Feedback*, UAI 2009 / arXiv 2012（https://arxiv.org/abs/1205.2618） | implicit feedback 推荐应优化排序目标；评价目标和训练信号不能混淆 | `itemcf_strong` 不应使用 eval label 反向筛边；Recall@K/HitRate@K 是评估层证据，不是候选生成输入 |

补充说明：SLIM / sparse linear item-item models 对“稀疏 item-item 权重 + 正则化”也有参考价值，但本次 DOI/公开页抓取受限，暂不作为已验证文献证据；后续如要把 strong 从统计共现升级为可学习 item-item 权重，可再补 SLIM 论文细读。

## 2. 最佳实践摘要

`itemcf_strong` 的目标不是最大覆盖，而是在用户已有强交互 seed item 周围提供高置信 item-item 邻居。它应当与 `itemcf_weak` 分工：weak 负责较宽覆盖与补量，strong 负责更可信的候选补充与解释性边。高置信 ItemCF 的核心质量条件包括：

- 用户侧：优先使用行为足够、协同信号稳定的用户；本轮 formal 默认使用 `collaborative_rich`，避免低行为用户造成偶然共现。
- item 侧：候选侧优先保留 train-only 中达到 CF 统计可靠性的 item；默认排除 over-hot 目的 item，避免热门 item 支配候选。
- 边侧：至少要求 pair support、weighted cooc、cosine / shrinkage 类归一化分数；强边宁可少，也不能把 weak coverage 逻辑包装成 strong。
- 口径侧：构建数据集/source artifact 只能读取 recent-2y train-visible 输入与 train-only governance；valid/test/holdout/LOPO/oracle/eval label 只能用于评估，不能参与候选生成或训练输入。

## 2. 数据质量条件

| 维度 | 要求 | 本项目适配 |
|---|---|---|
| 用户行为数 | 用户需有足够正反馈和多个唯一 item | train-only governance 中 `eligible_for_itemcf_strong=49719`，对应 `collaborative_rich` |
| 共现密度 | pair 至少有多个用户或高权重支持 | strict formal 使用 `min_pair_support=2`；如边数过少，只能保持 diagnostic |
| item 频次 | 候选 item 需具备 CF 统计稳定性 | 默认 `cf_ready` 且排除 over-hot；避免单次长尾和超热门噪声 |
| 时间窗 | 只使用 recent-2y train 历史 | 数据根为 `data/processed/amazon_2023_recall_recent_2y_1m_3m/` |
| seed 质量 | strong seed 应来自强正反馈序列 | source 查询使用 `recent_strong_positive_item_sequence` |

## 3. 数据预处理建议

1. 用户过滤：
   - strict strong formal：只使用 `collaborative_rich`。
   - 如需 relaxed variant，应单独标记为 relaxed supplemental，不与 strict strong 混为 READY 依据。
2. item 过滤：
   - strict formal 使用 `cf_ready` 且 `over_hot=false`。
   - 不使用 label 命中结果反向筛边。
3. 共现构造：
   - 从 `user_sequences.train.jsonl` 构造用户正反馈序列内 item pair。
   - 使用 active-user penalty 抑制长序列用户：`round(1 / log1p(filtered_sequence_len), 6)`。
   - 使用 `weighted_cooc / sqrt(src_user_count * dst_user_count)` 做 cosine-like 归一化；必要时加 shrinkage。
4. 排序与截断：
   - 每个 src item 内按 `itemcf_score desc, cooc_cnt desc, dst_item_id asc` 排序。
   - smoke 可以小规模 topK；formal 不应写死无解释的小 cap。

## 4. smoke 数据集设计

smoke 只用于验证程序路径、schema 和审计边界：

- 输入：recent-2y train-only governance manifest。
- 规模：小规模、可本地 `.venv` 快速运行。
- 产物：`method_dataset_manifest.json`、`method_dataset_rows.jsonl`。
- 验证：`forbidden_scope_audit.status=PASS`、`candidate_generation_allowed=false`、`promotion_allowed=false`。
- 不得声明：正式效果、READY、ranking input replacement。

## 5. formal 数据集设计

formal 是当前 official method logic dataset：

- 输入仍只来自 recent-2y train-visible 数据。
- strict strong 默认：`collaborative_rich` 用户、`cf_ready + non-over_hot` item、`min_pair_support=2`。
- 不追求最大覆盖；应报告边数、用户数、item 数、pair support/drop reason、weighted cooc。
- 若 formal row_count 过低，应作为 blocker 记录，而不是通过放宽到 weak 口径硬晋升。

## 6. source artifact 构建建议

`itemcf_strong` 属于非训练型统计/索引方法。source artifact 应从 formal method dataset 转换为 item-item edge source：

- 输入：formal `method_dataset_manifest.json` 与 `method_dataset_rows.jsonl`。
- 输出：`source_index_manifest.json` 与边文件/分片。
- source manifest 必须保留：`train_only=true`、`source_status=DIAGNOSTIC_ONLY`、`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`。
- 如 formal 边数很小，source artifact 仍可作为可复核 evidence，但不建议并入 READY 主路。

## 7. 评估建议

formal 效果验证需要区分“构建合规”和“召回贡献”：

- 构建合规：manifest lineage、input hash、forbidden scope audit、resource audit。
- 召回效果：Recall@20/50/100/500、HitRate@K、candidate count、user coverage。
- 分层：hot/warm/cold-ish 或 governance user bucket。
- 互补性：与 `itemcf_weak`、`swing_recall`、category/popular 的 source overlap、marginal candidate share。
- 资源：运行时间、row_count、shard_count、候选生成耗时。

评估 label 可以来自 valid/test，但只能在评估脚本中读取，不得写回 method dataset/source artifact。

## 8. 失败模式与 gate

| 失败模式 | Gate |
|---|---|
| 旧 full-data artifact 被当作当前结论 | registry/source_config 必须指向 recent-2y 当前产物或明确 archived |
| strict strong 边过少 | 保持 `DIAGNOSTIC_ONLY`，写清 blocker，不硬晋升 READY |
| 为了覆盖放宽成 weak 口径 | relaxed variant 必须单独标注，不作为 strict strong 晋升证据 |
| eval label 泄漏进构建 | forbidden scope audit、read_files、manifest lineage 必须 PASS |
| smoke 被误当 formal 效果 | 文档和配置明确 smoke 只做 program/schema validation |
| route gate 证据不足 | 不允许 candidate generation / ranking replacement / pool1000 |

## 9. 本项目适配结论

当前最稳妥路线是：先以 strict strong recent-2y formal 形成标准路径产物和 source artifact；如果 formal 边数/召回贡献不足，则保持 `DIAGNOSTIC_ONLY`，将 blocker 记录为“strict high-confidence 口径在 recent-2y 下共现密度不足”。后续如要提升覆盖，应另开 relaxed strong supplemental 方案，并与 `itemcf_weak` 做 overlap 和质量对照，不能直接替代 strong strict 结论。
