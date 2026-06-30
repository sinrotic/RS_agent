# itemcf_weak recent-2y SciOMC 调研

日期：2026-06-03

## 1. 结论摘要

`itemcf_weak` 应定位为 **宽覆盖、弱共现、补充型 item-item 协同召回**，目标不是替代强 ItemCF、UserCF 或排序输入，而是在 recent-2y train-only governance 下，用 medium/heavy 行为用户构建更宽的 item 邻接图，提升候选覆盖和长尾/中频 item 的可达性。

本轮重建的核心原则：

1. **train-only 构建**：item pair、item 频次、用户桶、item 桶、边权都只能来自 `canonical_interactions.train.jsonl`、`user_sequences.train.jsonl`、`canonical_items.jsonl` 和 `train_only_governance/*`。
2. **弱边保留但不无约束放大**：`min_pair_support=1` 可以用于 weak 覆盖，但必须配套活跃用户惩罚、热门 item 控制、per-seed 排序/必要 shard，以及 manifest 级 dropped reason。
3. **覆盖优先但保持诊断边界**：formal 指标可用于判断是否建议进入主路候选生成，但单方法窗口不能自动宣称 READY、promotion 或 ranking input replacement。
4. **smoke/formal 分层**：smoke 只验证 schema、路径、无泄漏和非零边；formal 才能报告 Recall@K、coverage、source overlap、用户桶分层和 in-universe recall。

## 2. 数据质量依赖

### 用户侧

- 适用桶：`heavy_cf_eligible` / `collaborative_rich` 与少量 `medium_behavior`；recent-2y governance 中 `eligible_for_itemcf_weak=49809`，其中 `medium_behavior=90`、`collaborative_rich=49719`。
- 不适合直接纳入：`cold_start`、`fallback_only`；这些用户历史不足，容易制造随机共现，应交给 popular/category/fallback repair。
- 对长序列用户必须加入活跃用户惩罚，避免超活跃用户把大量弱相关 item 连接成噪声边。

### item 侧

- `item_quality_profile` 中 `cf_ready` 与 `embedding_ready` 是可考虑 universe；严格 weak 可先用 `cf_ready`，coverage formal 可以扩展到 `cf_ready/embedding_ready`，但必须记录 profile。
- 热门 item 不能简单全部删除。实践上 weak ItemCF 可：
  - 对过热 item 做 cap 或 downweight；
  - 保留中频/可协同 item 作为主要候选；
  - 在 formal 报告 `item_user_freq_over_cap`、`item_over_hot`、seed/candidate item 数。
- 长尾 item：单次正反馈的 item 很难产生可靠共现；应在 in-universe 指标中单独报告，不把全量 catalog 长尾 denominator 和可召回 universe 混淆。

## 3. 预处理与边权建议

### 推荐边构建流程

1. 读取 `train_only_governance/manifest.json`，解析 train-only 路径和 profile artifact。
2. 从 `user_quality_profile.jsonl` 选择 `medium_behavior` 与 `collaborative_rich` 用户。
3. 从 `item_quality_profile.jsonl` 和 `item_frequency_train.jsonl` 得到 item 质量、频次和 user_count。
4. 对每个 eligible 用户取 `recent_positive_item_sequence`，去重后生成 item pair。
5. 对每个用户贡献的 pair 加权：
   - 基础活跃用户惩罚：`1 / log1p(filtered_sequence_len)`；
   - 可选 item 频次/IDF/BM25-like 权重，抑制热门 item 主导；
   - weak 允许 `min_pair_support=1`，但必须用 score 排序和 per-seed/topK 或 shard 控制输出。
6. 输出 directed edge：`src_item_id -> dst_item_id`，记录 `pair_support`、`supporting_user_count`、`weighted_cooc`、`src_user_count`、`dst_user_count`、`itemcf_score`、`supporting_user_buckets`、`edge_rank`。

### 分数口径

可落地分数：

```text
itemcf_score = weighted_cooc / sqrt(src_user_count * dst_user_count)
```

其中 `weighted_cooc` 包含活跃用户惩罚；如果启用 SciOMC recent-2y 弱召回 profile，可加入 BM25/IDF 风格 item 权重，但必须在 manifest 中记录 `score_policy`，避免之后把不同口径直接比较。

## 4. smoke 数据集设计

smoke 目标：只证明程序、schema 和治理边界可运行。

建议 contract：

- 输入：`data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json`。
- scale：`smoke`；可保留 `max_output_users=1000`、`max_items_per_user=50`、`max_item_user_freq=5000`、`min_pair_support=1`、`top_k_per_seed=100`。
- 输出：`outputs/recall/pool500_method_datasets/recent_2y/collab_v1/itemcf_weak/method_dataset_manifest.json` 或明确 smoke 子目录。
- 必须检查：
  - `status=PASS`；
  - `train_only=true`；
  - `candidate_generation_allowed=false`；
  - `ranking_input_replacement_allowed=false`；
  - `forbidden_scope_audit.status=PASS`；
  - `row_count > 0` 或若为 0 必须写明只通过 schema、不通过覆盖 gate。

smoke 不可作为 READY、promotion 或主路效果依据。

## 5. formal 数据集设计

formal 目标：在 recent-2y train-only 口径下构建该方法的正式边图。

建议 contract：

- 输入仍只来自 train-visible 与 governance artifact。
- 默认用户桶：`medium_behavior` + `collaborative_rich`；如果为了覆盖引入 `sequence_sufficient`，必须标记为 coverage profile，并在 METHOD/registry 中说明与 guide 默认 medium/heavy 口径的差异。
- weak 边：`min_pair_support=1`；使用活跃用户惩罚与 item frequency normalization。
- 不在方法侧写死无解释的小 cap；若因资源设置 cap/shard，manifest 必须记录原因、实际 eligible/contributing 用户数、边数、seed item 数、candidate item 数和 dropped reason。

## 6. source artifact 构建建议

推荐两段式：

1. `build_pool500_method_dataset.py` 生成 method dataset rows 与 manifest。
2. `pool500/method_dataset_to_itemcf_source.py` 将 method dataset rows 转为 itemcf source edge index。

这样可以明确：method dataset 是 train-only 派生层，source artifact 是只读 edge index 层。source manifest 中继续保持：

- `source_status=DIAGNOSTIC_ONLY`，除非全局 route gate 后升级；
- `candidate_generation_allowed=false`；
- `ranking_input_replacement_allowed=false`；
- `promotion_allowed=false`；
- `diagnostic_boundary.label_usage=none_in_candidate_generation`。

## 7. 评估建议

formal 至少报告：

- artifact 规模：row_count、unique_pair_count、edge_count、edge_seed_count、item_count、contributing_user_count。
- 覆盖：有出边 seed 数、候选 item 数、用户历史 seed 命中率、候选非零用户率。
- Recall@K：评估 label 只在评估阶段读取，不能影响构建。建议报告 @50/@100/@500。
- 用户桶分层：`medium_behavior`、`sequence_sufficient`、`collaborative_rich` 等，明确哪些用户实际可由 weak ItemCF 服务。
- in-universe recall：分母限定为 source item universe 可覆盖的 label，用于区别“方法不可达”和“排序/边权没召回”。
- source overlap：与已 READY 方法（popular/category/swing）及 itemcf_strong/usercf 的候选重叠，判断互补性。

## 8. 常见失败模式与 gate

| 失败模式 | 风险 | gate |
|---|---|---|
| 旧 full-data artifact 被继续引用 | recent-2y 结论失真 | source_config/registry 不得指向旧 sidecar 作为 latest formal |
| eval label 参与构建 | label leakage | no-holdout / forbidden_scope audit 必须 PASS |
| weak 边过宽导致噪声 | 候选多但 Recall 不升 | formal 需报告 Recall@K、overlap、undercoverage，不足则保持 DIAGNOSTIC_ONLY |
| 只跑 smoke 就晋升 | 误把链路验证当效果 | smoke manifest 必须 `promotion_allowed=false` |
| 低质量用户纳入建图 | 随机共现 | 用户桶必须来自 governance，fallback/cold 不入图 |
| formal 资源不可控 | 本地打满或中断 | 大图使用 shard/server；本地只跑受控或拉回 manifest 复核 |

## 9. 论文与工业实践依据

> 注：本轮外部检索工具出现 Exa 超时、ACM 403、Semantic Scholar 429，因此这里采用可复核的经典论文/DOI 线索作为 SciOMC 依据，后续可在联网稳定时补 BibTeX。调研结论不依赖未验证的网页内容，而是把经典 item-based CF、top-N、长尾/热门偏置与评估论文映射到本项目的执行 gate。

| 方向 | 代表论文/实践 | 对 `itemcf_weak` 的启发 |
|---|---|---|
| Item-based CF 基础 | Sarwar, Karypis, Konstan, Riedl, *Item-based Collaborative Filtering Recommendation Algorithms*, WWW 2001, DOI: `10.1145/371920.372071` | item-item 相似度是离线可构建、线上低延迟的经典召回底座；本项目对应 `method_dataset -> source index` 两段式。 |
| Amazon item-to-item 工业实践 | Linden, Smith, York, *Amazon.com Recommendations: Item-to-Item Collaborative Filtering*, IEEE Internet Computing 2003, DOI: `10.1109/MIC.2003.1167344` | item-to-item 适合大规模 catalog 和实时用户历史 seed 扩展；但必须离线构建 item 邻接、在线按用户历史聚合候选。 |
| Top-N ItemKNN | Deshpande, Karypis, *Item-Based Top-N Recommendation Algorithms*, ACM TOIS 2004, DOI: `10.1145/963770.963776` | Top-N 场景要关注邻接边排序、support、相似度归一化和 topK fanout；不能只看边数。 |
| 隐式反馈排序 | Rendle et al., *BPR: Bayesian Personalized Ranking from Implicit Feedback*, UAI 2009 | weak ItemCF 的后验评估应围绕排序/Recall@K，而不是把所有共现边当正样本质量。 |
| 稀疏线性 item 模型 | Ning, Karypis, *SLIM: Sparse Linear Methods for Top-N Recommender Systems*, ICDM 2011 | item-item 权重可以视作稀疏 item 线性模型；需要正则/稀疏/噪声控制，对应 weak 边的 gate。 |
| 事实化 item similarity | Kabbur, Ning, Karypis, *FISM: Factored Item Similarity Models for Top-N Recommender Systems*, KDD 2013, DOI: `10.1145/2487575.2487589` | item similarity 可以从隐式反馈中学习/压缩；说明简单共现是 baseline，不足时可作为后续增强方向。 |
| 浅层强 baseline | Steck, *Embarrassingly Shallow Autoencoders for Sparse Data*, WWW 2019, DOI: `10.1145/3308558.3313710` | 近邻/浅层 item-item 方法常是强 baseline；评估时要严谨比较，不可低估也不可无证据晋升。 |
| Top-N 评估 | Cremonesi, Koren, Turrin, *Performance of Recommender Algorithms on Top-N Recommendation Tasks*, RecSys 2010, DOI: `10.1145/1864708.1864721` | formal 必须报告 Recall@K/HitRate 等 top-N 指标，smoke 不能当效果。 |
| 热门偏置与长尾 | Abdollahpouri, Burke, Mobasher, *Controlling Popularity Bias in Learning-to-Rank Recommendation*, RecSys 2017；Celma, Cano, *From Hits to Niches?*, 2008 | weak ItemCF 若过度依赖热门 item，会牺牲长尾和互补性；需要 item frequency cap/downweight、coverage 与 overlap 报告。 |
| 可复现实验警示 | Dacrema, Cremonesi, Jannach, *Are We Really Making Much Progress?*, RecSys 2019, DOI: `10.1145/3298689.3347058` | 必须保留 manifest、hash、输入边界和可复核评估，避免用旧 artifact 或诊断集冒充正式提升。 |

对本项目的直接落点：

1. `itemcf_weak` 采用 item-based CF / Amazon item-to-item 的离线邻接图思想，但必须绑定 recent-2y train-only lineage。
2. 采用 Top-N 论文强调的 Recall@K、candidate coverage、per-seed fanout，而不是只报告边数。
3. 采用热门偏置/长尾论文的 gate：报告 in-universe denominator、长尾/中频覆盖和 source overlap，防止弱召回变成热门边复制。
4. 采用可复现推荐系统论文的警示：每个 artifact 写 manifest/hash/forbidden input audit，旧 full-data 只能历史参考。

## 10. 对本项目的落地判断

当前仓库已有 recent-2y `build_pool500_method_dataset.py` 和 `method_dataset_to_itemcf_source.py`，适合先走 method_dataset -> source index 的两段式重建。由于 `itemcf_weak` 现有 registry 仍指向旧 `pool500_sidecar_fix` artifact，且 source_config 仍是 `FORMAL_PENDING`，本轮应在 recent-2y 路径下生成 smoke/formal manifest 与 source index 后，再更新文档和配置。若 formal 只证明 artifact 可构建但缺少 route gate / overlap / Recall@K 增益证据，应保持 `DIAGNOSTIC_ONLY`，只给出“可进入全局收口评审”的候选证据，不在单方法窗口直接并入主路。
