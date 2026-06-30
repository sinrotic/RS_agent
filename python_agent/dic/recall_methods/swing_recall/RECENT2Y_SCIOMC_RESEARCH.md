# swing_recall recent-2y SciOMC 调研

## 调研目标

本调研服务于 pool500 recent-2y 单方法重建中的 `swing_recall`。目标不是复述 Swing 算法概念，而是把文献/工业实践转成当前项目可执行的数据治理、构图、评估和晋升门禁。

## 参考资料与论文依据

> 说明：公开可抓取资料中，`Swing` 更常见于工业召回经验和中文技术资料，而不是一个统一命名的顶会标准算法。当前文档将 Swing 视为 item-item 协同过滤的一种带共同用户/活跃度惩罚的工程变体，并用 item-based CF、implicit-feedback ranking 和大规模推荐系统论文支撑其设计边界。

1. Sarwar et al., **Item-Based Collaborative Filtering Recommendation Algorithms**, WWW 2001。
   - 关键点：item-item 相似度可基于用户共现离线预计算，在线阶段只需按用户历史 item 查邻居；top-k neighborhood pruning 可显著降低服务成本。
   - 对本项目启发：Swing source index 应离线构建 `item -> related items` 边，并记录 `per_seed_top_k`、边数、seed item 数和剪枝策略，不能在线全量算 pair。
2. Linden, Smith, York, **Amazon.com Recommendations: Item-to-Item Collaborative Filtering**, IEEE Internet Computing 2003。
   - 关键点：Amazon 使用 item-to-item CF 解决大规模 catalog 下的实时推荐问题，重计算前置到离线 item similarity，线上按用户历史商品聚合相似商品。
   - 对本项目启发：`swing_recall` 适合作为行为协同扩展 source，不适合作为冷启动主力；需要记录离线 source artifact 与在线候选生成权限位。
3. Rendle et al., **BPR: Bayesian Personalized Ranking from Implicit Feedback**, UAI 2009 / arXiv 2012。
   - 关键点：implicit feedback 推荐应关注排序目标，并严格区分训练可见行为与 evaluation label。
   - 对本项目启发：valid/test label 只可用于 Recall@K / HitRate@K 评估，不得进入 Swing 构图、边过滤或 candidate generation。
4. He et al., **Neural Collaborative Filtering**, arXiv 2017。
   - 关键点：implicit-feedback top-k 推荐是工业推荐的常见评估场景，协同信号依赖用户-item 交互质量。
   - 对本项目启发：即使后续引入深度召回，也需要与 Swing 这类浅层行为协同 source 做 overlap / marginal contribution 对比。
5. Cheng et al., **Wide & Deep Learning for Recommender Systems**, arXiv 2016。
   - 关键点：大规模推荐系统常把 memorization/co-occurrence 与 generalization 分层处理。
   - 对本项目启发：Swing 更接近 memorization/co-occurrence recall，应该与 two_tower/semantic 等泛化召回分工，而不是互相替代。
6. Kang & McAuley, **Self-Attentive Sequential Recommendation**, ICDM 2018。
   - 关键点：序列推荐强调最近行为和行为顺序对下一 item 预测的重要性。
   - 对本项目启发：Swing 虽不是序列模型，但候选生成时可以使用 recent seed window；本轮 source index 构建仍只用 train-only 全局边，候选聚合时再按用户 train seed 过滤已见 item。

## 最佳实践摘要

### 1. 数据质量条件

`swing_recall` 最依赖以下条件：

- 用户至少有 2 个 train 正反馈 item，否则无法提供 item-item 共现证据。
- item 需要有足够但不过热的 train user support。过热 item 会把大量无关 item 连接成噪声边。
- 共现边需要 `min_pair_support >= 2` 才适合作为 formal 证据；smoke 可放宽为 1 以验证 schema 和路径。
- 高活跃用户应被限制或惩罚，避免单个长序列用户贡献过多 pair。
- recent-2y 场景中，valid/test label 分布与 train 历史用户重合有限，因此应分桶报告：冷/单 seed、2-3 行为、4-9 行为、10+ 行为。

### 2. train-only 预处理

本项目采用两层数据：

1. `data/processed/amazon_2023_sciomc_swing_recent2y/{smoke,formal}`
   - 从 `data/processed/amazon_2023_recall_recent_2y_1m_3m/manifest.json` 派生。
   - train：positive-only、按 user-item 去重、按时间排序，输出 `user_sequences.train.jsonl`。
   - valid/test：只保留 train item universe 内正样本，输出 `swing_valid_in_universe.jsonl` / `swing_test_in_universe.jsonl`，仅用于评估。
2. `outputs/recall/pool500_method_datasets/recent_2y/swing_recall/{smoke,formal}/swing_method_dataset`
   - 从 train-only governance 派生。
   - 读取 `user_quality_profile.jsonl`、`item_quality_profile.jsonl`、`item_frequency_train.jsonl`、`user_sequences.train.jsonl`。
   - 不读取 valid/test/holdout/LOPO/oracle/eval label。

### 3. smoke/formal 数据集设计

- smoke：
  - 目标是程序、schema、路径和 no-holdout contract 验证。
  - 可使用 deterministic first-N 或 bounded graph users。
  - 不可作为效果结论或晋升依据。
- formal：
  - 目标是 recent-2y train-only 正式方法证据。
  - 不继承旧 smoke/10k/full 固定数量 cap。
  - 必须记录 input hash、lineage、用户/item/边数、过滤原因和 forbidden scope audit。

### 4. source index 构建策略

推荐 formal 参数：

- `max_user_items=50`：限制高活跃用户单次贡献，保留最近 train 行为。
- `max_item_user_freq=100`：严格剔除过热 item，控制热门噪声。
- `min_pair_support=2`：formal 边至少由两个共同用户支持。
- `per_seed_top_k=100`：控制每个 seed item 的邻居数量。
- `min_score=0.0`：保留非负 Swing 分数，排序阶段再按 score/route 融合。

当前实现的 Swing 分数近似为：

```text
score = co_count / (alpha + sum(1 / len(user_item_set_u) for u in common_users))
```

它保留 common users 的支持，同时通过用户行为长度项降低活跃用户对 pair 的过度贡献。

### 5. 评估建议

单方法评估至少报告：

- `Recall@20/50/100/500` 与 `HitRate@20/50/100/500`。
- candidate user coverage、seed edge hit rate、candidate count 分布。
- 用户行为桶分层：cold/single seed、2-3、4-9、10+。
- source artifact 规模：edge_count、seed_count、dropped_hot_item_count。
- no-holdout audit：构图只读 train sequence，valid/test 仅用于 evaluation-only label。

进入 pool500 主路前，还必须做全局 route gate：

- 与 popular/category/itemcf/two_tower/semantic 等已有 source 的 overlap。
- marginal positive hit users。
- pool500 候选数、underfill、source contribution。
- route gate / loader regression tests。

### 6. 常见失败模式与门禁

| 失败模式 | 表现 | 门禁 |
| --- | --- | --- |
| 旧 artifact 回流 | registry/source_config 指向 `pool500_sidecar_fix` 或旧 full-data 路径 | 文档和配置必须改为 recent-2y artifact；旧路径只作历史参考 |
| label 泄漏 | valid/test/holdout/eval label 进入构图或边过滤 | builder manifest 只暴露 `train_user_sequences_path`；no-holdout audit PASS |
| 热门 item 主导 | 大量边集中在热门 item，候选同质化 | `max_item_user_freq`、dropped_hot_items、source overlap audit |
| 低行为用户覆盖差 | cold/single seed 桶 candidate coverage 低 | 分桶报告，不强行宣称覆盖全用户 |
| formal 效果弱 | raw source Recall/HitRate 很低 | 保持 `READY_GUARDED` 或 `DIAGNOSTIC_ONLY`，等待全局 route gate，不直接 promotion |
| route 证据不足 | 单 source eval 有结果但无 marginal lift | `candidate_generation_allowed=false`，不自动并入主路 |

## 本项目适配判断

当前 recent-2y formal source artifact 已能构建出 `237681` 条 Swing 边、`46788` 个 seed item，no-holdout audit 显示构图阶段只读 formal train sequence。raw source evaluation 显示：

- valid：`HitRate@500=0.002295`、`Recall@500=0.001898`。
- test：`HitRate@500=0.000508`、`Recall@500=0.000457`。
- test 中 `medium_behavior_4_9` 桶 `HitRate@500=0.022648`，说明 Swing 的主要价值在有一定 train 历史的用户，而不是冷启动。

结论：`swing_recall` 可以作为 **formal evidence ready 的 guarded 行为协同 source** 保留，但本窗口不应直接开启主路 candidate generation 或 promotion。下一步应在全局 pool500 route gate 中验证它与其他 READY source 的互补性与 underfill 改善。