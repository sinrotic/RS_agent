# itemcf_weak recent-2y 结果不佳原因诊断与修复方案

日期：2026-06-03

## 1. 结论摘要

`itemcf_weak` formal strict 结果不好，不是因为构建失败，也不是因为 label 泄漏治理错误；直接原因是 **strict profile 把弱召回本应承担的“宽覆盖”能力过滤得过窄**，导致 source 边图与评估用户历史、valid/test label 的交集极低。

当前证据支持的结论：

1. strict source artifact 构建成功，但只有 `9856` 个 seed/candidate item、`17866` 条 directed edge，平均每个 seed 只有约 `1.813` 条边，最大候选数也只有 `14`。
2. 评估中 `evaluated_users_with_train_sequence=54362`，但 `users_with_seed_hit=274`、`users_with_candidates=232`，`candidate_user_rate=0.004268`。
3. eval label 与 source item universe 的交集极低：`in_universe_label_total=281 / raw_label_total=71669`，`in_universe_label_ratio=0.003921`。
4. Recall@50/100/500 和 in-universe Recall@50/100/500 全为 `0.0`，说明问题首先是覆盖和候选可达性，不是排序尾部没有排上。
5. 当前 strict 配置只使用 `medium_behavior + collaborative_rich` 用户桶，并要求 item 为 `cf_ready` 且非 over-hot；这与 evaluated users 里大量 `cold_start`、`fallback_only`、`sequence_sufficient` 用户明显错位。

因此，下一轮不应直接调排序或强行 READY，而应先做 **train-only 的 weak_coverage 对照实验 + seed/user fanout 控制 + source overlap / marginal Recall gate**。本轮进一步远程运行了去噪网格，结论是：support=1 弱边虽然噪声高，但也是当前 raw Recall 的主要来源；简单 support>=2、BM25/IDF 或 hot-dst 排除会显著牺牲 raw Recall。当前最稳的修复不是“强去噪”，而是保留 support=1 宽覆盖，同时用 `top_k_per_seed=200` 和 route 侧 `per_user_candidate_cap=500` 先把候选爆炸收住。

## 2. 证据复核

### 2.1 formal method dataset

路径：

`outputs/recall/pool500_method_datasets/recent_2y/collab_v1/itemcf_weak/method_dataset_manifest.json`

关键字段：

- `status=PASS`
- `train_only=true`
- `forbidden_scope_audit.status=PASS`
- `row_count=17866`
- `unique_pair_count=8933`
- `directed_edge_count_after_topk=17866`
- `user_count=4313`
- `item_count=9856`
- `effective_user_bucket_policy=heavy_cf_eligible_or_medium_behavior`
- `effective_item_bucket_policy=item_quality_profile.cf_ready=true and over_hot=false for collaborative filtering`

大量 drop 发生在候选构建前：

- `user_bucket_not_allowed=6776992`
- `insufficient_pair_items=45496`
- `item_over_hot=335032`
- `item_not_cf_ready=416006`

这说明 formal strict 的边图不是全量用户/全量 item 上的弱召回图，而是一个非常窄的协同过滤诊断图。

### 2.2 formal source artifact

路径：

`outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/formal_strict_v1/source_index_manifest.json`

关键字段：

- `status=PASS`
- `row_count=17866`
- `sharded=true`
- `shard_count=8`
- `source_status=DIAGNOSTIC_ONLY`
- `candidate_generation_allowed=false`
- `ranking_input_replacement_allowed=false`
- `promotion_allowed=false`

source adapter 没有明显丢行：manifest row count、edge count、method dataset row count 都是 `17866`。因此当前失败不是 adapter 丢数据导致的。

### 2.3 formal evaluation

路径：

`outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/formal_strict_v1/evaluation_report.json`

关键字段：

- `evaluated_users_with_train_sequence=54362`
- `raw_label_total=71669`
- `in_universe_label_total=281`
- `in_universe_label_ratio=0.003921`
- `users_with_seed_hit=274`
- `seed_hit_user_rate=0.00504`
- `users_with_candidates=232`
- `candidate_user_rate=0.004268`
- `candidate_count_stats.p50=0`
- `candidate_count_stats.p90=0`
- `candidate_count_stats.max=14`
- `raw_recall@50=0.0`
- `raw_recall@100=0.0`
- `raw_recall@500=0.0`
- `in_universe_recall@50=0.0`
- `in_universe_recall@100=0.0`
- `in_universe_recall@500=0.0`

`p50=0`、`p90=0` 表明绝大多数评估用户根本拿不到该 source 的候选。Recall 为 0 是覆盖问题的结果，而不是 topK 太小的问题。

## 3. 额外诊断统计

本轮使用 `.venv` 做了只读统计，未修改候选生成输入。统计目的仅是解释失败原因。

### 3.1 用户桶错位

`train_only_governance/user_quality_profile.jsonl` 中用户质量桶分布：

| bucket | 用户数 |
|---|---:|
| cold_start | 5,267,837 |
| fallback_only | 871,817 |
| sequence_sufficient | 637,338 |
| collaborative_rich | 49,719 |
| medium_behavior | 90 |

当前 strict 只允许 `medium_behavior + collaborative_rich`，合计约 `49,809` 用户；`sequence_sufficient` 的 `637,338` 用户没有进入图构建。对一个定位为 weak/wide 的辅助召回源，这个入口过窄。

评估用户按质量桶粗略统计显示，valid/test 中有 train sequence 的 label 很多来自 `cold_start`、`fallback_only`、`sequence_sufficient`，而 strict 图主要从 `collaborative_rich` 建边，用户侧存在明显分布错位。

### 3.2 item universe 过窄

只读统计显示：

| 口径 | item 数 |
|---|---:|
| strict non-hot `cf_ready` item universe | 113,250 |
| weak coverage `cf_ready ∪ embedding_ready` item universe，含 hot | 448,282 |
| 当前 source 实际 item union | 9,856 |

当前 source item union 只有 `9,856`，远小于 strict 可用 item universe，也远小于 weak coverage 可用 universe。

方向性统计还显示，eval label 对 `cf_ready ∪ embedding_ready` 的覆盖远高于 strict non-hot 口径。这说明下一轮最值得验证的不是“把 strict 图排序调好”，而是“扩大可达 item universe，同时用权重/门禁控制热门噪声”。

### 3.3 边图太稀疏

source 边图统计：

- `source_src_item_count=9856`
- `source_dst_item_count=9856`
- `source_union_item_count=9856`
- src degree：`min=1`，`max=10`，`avg≈1.813`

一个 recall source 的 seed item 平均只有不到 2 个候选，且 `candidate_count_stats.max=14`，无法承担 pool500 的宽候选扩展任务。

### 3.4 weak_coverage 后验诊断结果

为验证“strict 失败是否主要由覆盖过窄造成”，本轮复核了既有 `weak_coverage` method dataset，并基于 method dataset rows 做了一次 **evaluation-only 流式候选模拟**。该诊断没有生成正式 source artifact，也没有使用 valid/test label 参与构建；valid/test label 只用于后验 Recall@K 计算。

已有 `weak_coverage` method dataset：

`outputs/recall/pool500_itemcf_new_dataset/method_datasets_smoke/itemcf_weak/method_dataset_manifest.json`

关键规模：

- `status=PASS`
- `train_only=true`
- `forbidden_scope_audit.status=PASS`
- `row_count=4445902`
- `user_count=120000`
- `item_count=185326`
- `unique_pair_count=2401767`
- `directed_edge_count_after_topk=4445902`
- `top_k_per_seed=200`

流式后验诊断报告：

`outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/weak_coverage_eval_from_method_dataset_v1/evaluation_report.json`

关键结果：

- `edge_rows_scanned=4445902`
- `source_item_union_count=185326`
- `eval_seed_items_with_edges=35741`
- `candidate_user_rate=0.83305`
- `in_universe_label_ratio=0.6837`
- `candidate_count_stats.p50=58`
- `candidate_count_stats.p90=219`
- `candidate_count_stats.max=4569`
- `raw_recall@50=0.008122`
- `raw_recall@100=0.010523`
- `raw_recall@500=0.01478`
- `in_universe_recall@50=0.01188`
- `in_universe_recall@100=0.015391`
- `in_universe_recall@500=0.021617`

对比 strict formal：

| 指标 | strict formal source | weak_coverage eval-only method dataset |
|---|---:|---:|
| item union | `9856` | `185326` |
| `candidate_user_rate` | `0.004268` | `0.83305` |
| `in_universe_label_ratio` | `0.003921` | `0.6837` |
| `raw_recall@500` | `0.0` | `0.01478` |
| `in_universe_recall@500` | `0.0` | `0.021617` |
| candidate p90 | `0` | `219` |
| candidate max | `14` | `4569` |

结论：`weak_coverage` 明显恢复了候选可达性和非零 Recall，证明 strict 失败的核心原因确实是 coverage profile 过窄。但 `candidate_count_stats.max=4569` 和 support=1 边占比高，说明候选爆炸和弱边噪声风险也同时出现。因此它仍不能直接 READY，需要进一步做正式 source artifact、候选预算控制、source overlap 和 route gate。

### 3.5 去噪网格远程诊断结果

根据“效果仍然偏差”的反馈，本轮在授权远程服务器 `server:/home/luo/RS_agent_remote` 上运行了 evaluation-only 去噪网格。为了避免占满 `/home` 分区，3.2GB method dataset rows 临时移动到 `/tmp/itemcf_weak_diagnostics/method_dataset_rows.jsonl`，输出报告拉回本地：

`outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/weak_coverage_denoising_grid_v2/evaluation_report.json`

该诊断仍然只用 valid/test label 做后验评估，不参与构建、打分、过滤或候选生成。

关键对比：

| variant | raw_recall@500 | in_universe_recall@500 | candidate_user_rate | p90/max candidates | 结论 |
|---|---:|---:|---:|---:|---|
| `baseline_support1_no_cap` | `0.01478` | `0.021617` | `0.83305` | `202 / 4569` | Recall 最好但 max 爆炸 |
| `support1_existing_seed200_user500` | `0.01478` | `0.021617` | `0.83305` | `202 / 500` | 与 baseline Recall 相同，同时把 per-user max 收到 500 |
| `support1_existing_seed100_user500` | `0.012771` | `0.018679` | `0.83305` | `133 / 500` | 进一步控量但 Recall 有明显损失 |
| `support1_existing_seed50_user500` | `0.010387` | `0.015192` | `0.83305` | `92 / 500` | 控量更强，Recall 损失更大 |
| `support2_no_cap` | `0.005789` | `0.025294` | `0.314332` | `4 / 109` | in-universe 精度提高，但 raw Recall/覆盖大幅下降 |
| `support3_no_cap` | `0.003967` | `0.04832` | `0.1209` | `1 / 25` | 更像高置信窄源，不适合 weak wide recall |
| `support1_bm25idf_shrink25_seed100_hotdst_nonhot` | `0.000051` | `0.000121` | `0.559968` | `9 / 216` | 过度去热门/重排，几乎打掉命中 |
| `support2_bm25idf_shrink25_seed100_hotdst_nonhot` | `0.0` | `0.0` | `0.004088` | `0 / 3` | 不可用 |

修复结论：

1. **不能简单把 support=1 边过滤掉。** `support>=2` 虽然把 max candidates 从 `4569` 降到 `109`，但 `raw_recall@500` 从 `0.01478` 降到 `0.005789`，说明当前 raw 命中主要依赖 support=1 长尾/弱边。
2. **BM25/IDF + hot-dst 排除在当前实现下过强。** 该组合把 `raw_recall@500` 打到 `0.000051` 甚至 `0.0`，暂不适合作为正式修复主路。
3. **当前最稳的工程修复是保留 `support=1 + existing score`，加候选预算边界。** `support1_existing_seed200_user500` 与 baseline 维持同样 `raw_recall@500=0.01478`，但把单用户候选上限从 `4569` 收敛到 `500`。
4. 因此新增 `weak_denoised` profile 的第一版不再采用 BM25/IDF/hot 排除，而是采用 `top_k_per_seed=200`、保留 hot/embedding-ready item、继续 `candidate_generation_allowed=false`，后续只允许在 route gate 中以受控预算参与边际收益验证。

## 4. 构建逻辑中的关键原因

代码入口：`rs_lab/experiments/recall/build_pool500_method_dataset.py`

### 4.1 strict 用户桶过窄

当前 `itemcf_weak` strict 默认策略：

- `eligible_user_buckets=["medium_behavior", "collaborative_rich"]`
- 实际 `medium_behavior` 只有 `90` 用户。
- 大量 `sequence_sufficient` 用户被排除。

这会导致图只代表极少量强协同用户的共现关系，而不是 recent-2y 的广覆盖弱召回关系。

### 4.2 strict item 过滤和 over-hot 排除过强

当前 strict 默认：

- item 需要 `cf_ready=true`
- `over_hot=false`

manifest 中：

- `item_over_hot=335032`
- `item_not_cf_ready=416006`

这能降低热门噪声，但也会把大量 valid/test label 所在 item universe 排除掉。对于弱召回，完全排除 hot/embedding-ready 可能比“降权/限额”更伤覆盖。

### 4.3 support=1 弱边既是噪声源，也是当前命中来源

当前 score：

`weighted_cooc / sqrt(src_user_count * dst_user_count)`

并且：

- `min_pair_support=1`
- `shrinkage_alpha=0.0`

样例边中大量 `pair_support=1`，确实会带来偶然共现噪声。但远程网格显示，直接提升到 `support>=2` 会把 `raw_recall@500` 从 `0.01478` 降到 `0.005789`，说明 support=1 边也是当前弱召回 raw 命中的主要来源。因此第一版修复不能简单过滤 support=1，而应先通过 `top_k_per_seed=200` 和 route/eval 侧 `per_user_candidate_cap=500` 控制候选爆炸。

### 4.4 BM25/TF-IDF 权重能力暂不作为第一版主路

代码中已有：

- `ITEMCF_RECENT_2Y_WEAK_SCORE_POLICY = "sciomc_bm25_tfidf_idf_weighted_cooc_cosine_v1"`
- `_itemcf_bm25_tfidf_idf_weight(...)`

`_itemcf_edge_rows(...)` 也支持当 score policy 等于该值时，对 pair weight 乘以 item IDF/BM25-like 权重。

但本轮 evaluation-only 网格显示，`BM25/IDF + shrinkage + hot-dst non-hot` 组合的 `raw_recall@500` 只有 `0.000051` 或 `0.0`，过度牺牲覆盖。因此 BM25/IDF 暂时保留为后续消融/高精度窄源方向，不作为 `weak_denoised` 第一版主路。

## 5. 论文与工业实践启发

外部检索通道说明：本轮 Exa 和 WebSearch 多次返回超时或 API tool-output 异常；ACM/DOI 页面部分 403。成功复核到 Harald Steck 2019 EASE arXiv 页面。以下论文清单使用经典论文题名、作者、年份和 DOI/arXiv 线索作为可复核参考，不使用不可访问网页内容编造实验结论。

| 方向 | 代表论文/实践 | 对本项目的启发 |
|---|---|---|
| Item-based CF 基础 | Sarwar, Karypis, Konstan, Riedl, *Item-based Collaborative Filtering Recommendation Algorithms*, WWW 2001, DOI `10.1145/371920.372071` | Item-item 相似度可作为可解释、低延迟召回底座；但相似度要结合邻域大小、共现支持和归一化。 |
| Amazon item-to-item 工业实践 | Linden, Smith, York, *Amazon.com Recommendations: Item-to-Item Collaborative Filtering*, IEEE Internet Computing 2003, DOI `10.1109/MIC.2003.1167344` | 工业 item-to-item 依赖大规模 item 邻接和用户历史 seed 扩展；如果 seed/item 覆盖太窄，就失去线上召回意义。 |
| Top-N ItemKNN | Deshpande, Karypis, *Item-Based Top-N Recommendation Algorithms*, ACM TOIS 2004, DOI `10.1145/963770.963776` | Top-N 目标不是只构边，而是每个 seed 有足够邻接、用户能拿到候选、Recall/coverage 达标。 |
| Implicit feedback | Hu, Koren, Volinsky, *Collaborative Filtering for Implicit Feedback Datasets*, ICDM 2008, DOI `10.1109/ICDM.2008.22` | 隐式反馈应区分偏好与置信度；不能把单次共现边与高置信相似等价看待。 |
| Pairwise ranking | Rendle et al., *BPR: Bayesian Personalized Ranking from Implicit Feedback*, UAI 2009 | 后续排序/重排可学习 pairwise preference，但召回侧必须先保证候选可达。 |
| SLIM | Ning, Karypis, *SLIM: Sparse Linear Methods for Top-N Recommender Systems*, ICDM 2011 | 稀疏 item-item 权重可以学习而非只靠 cosine；本项目可先用 shrinkage/BM25 近似，再考虑学习型 item-item。 |
| FISM | Kabbur, Ning, Karypis, *FISM: Factored Item Similarity Models for Top-N Recommender Systems*, KDD 2013, DOI `10.1145/2487575.2487589` | 用户历史可通过 item similarity 聚合；但历史 seed 覆盖和 item embedding/latent 泛化很关键。 |
| EASE | Harald Steck, *Embarrassingly Shallow Autoencoders for Sparse Data*, 2019, arXiv `1905.03375` | 简单线性 item-item 模型在 sparse implicit data 上很强，可作为 ItemCF 后续升级方向；但需要离线矩阵求解和资源评估。 |
| Top-N 离线评估 | Cremonesi, Koren, Turrin, *Performance of Recommender Algorithms on Top-N Recommendation Tasks*, RecSys 2010, DOI `10.1145/1864708.1864721` | 评估必须看 Recall@K、hit rate、候选可达性和采样偏差；当前 Recall=0 应先诊断 universe/coverage，而不是只改排序。 |
| 热门偏置与长尾 | long-tail / popularity bias recommender literature | 弱召回不能简单放开热门 item；应采用热门降权、每用户/每 seed 配额、source overlap gate 和长尾覆盖指标。 |

## 6. 根因假设树

```text
itemcf_weak strict formal Recall@K = 0
├── H1 覆盖不足（高置信）
│   ├── source item union 只有 9856
│   ├── seed_hit_user_rate=0.00504
│   ├── candidate_user_rate=0.004268
│   └── in_universe_label_ratio=0.003921
├── H2 用户桶错位（高置信）
│   ├── strict 只用 medium_behavior + collaborative_rich
│   ├── sequence_sufficient 大量用户未参与建图
│   └── evaluated users 主要不是 strict 建图用户分布
├── H3 item 过滤过强（高置信）
│   ├── cf_ready non-hot 限制导致 item universe 缩小
│   ├── embedding_ready 和 hot item 被排除
│   └── eval label 多数不在 source universe
├── H4 边图太稀疏（高置信）
│   ├── 平均 src degree≈1.813
│   └── candidate_count p50/p90=0
├── H5 打分策略不适合扩大后的弱边（中置信）
│   ├── 当前 support=1 边较多
│   ├── 远程网格显示 support>=2/BM25/IDF/hot 排除会显著降低 raw Recall
│   └── 当前第一修复应优先做 seed/user fanout cap，再做 route gate 边际验证
└── H6 source adapter 或治理失败（低置信，基本排除）
    ├── source row_count 与 method dataset 一致
    ├── forbidden_scope_audit=PASS
    └── eval label 只用于 post-hoc evaluation
```

## 7. 修复路线

### 7.1 低成本：weak_coverage smoke + 覆盖诊断

目的：先验证扩展用户桶和 item universe 后，source item/seed/candidate coverage 是否明显改善。

建议配置：

- `source_method=itemcf_weak`
- `scale_tier=smoke`
- `itemcf_coverage_profile=weak_coverage`
- 输入仍只允许 recent-2y train-only governance。

应检查：

- `forbidden_scope_audit.status=PASS`
- `row_count`、`unique_pair_count`、`item_count` 是否显著高于 strict smoke/formal 的相对口径。
- `source_src_item_count`、`source_dst_item_count`、src degree p50/p90。
- 不做 READY claim。

### 7.2 中成本：formal weak_denoised + 候选预算控制

目的：在已证明 `weak_coverage` 可恢复覆盖和非零 Recall 的基础上，把 eval-only method dataset 诊断推进为正式、可审计的 source artifact，同时先控制候选爆炸，而不是过早做强过滤。

当前已有证据：`weak_coverage` method dataset 的流式后验评估已达到 `candidate_user_rate=0.83305`、`raw_recall@500=0.01478`、`in_universe_recall@500=0.021617`；远程去噪网格进一步证明 `support1_existing_seed200_user500` 可以保持同样 `raw_recall@500=0.01478`，并把 `candidate_count_stats.max` 从 `4569` 控制到 `500`。但它还不是 full source artifact，也缺少 overlap / route gate 证据。

建议改动：

1. 新增 `weak_denoised` profile：
   - `score_policy=weighted_cooc_cosine_normalized_v1`
   - `min_pair_support=1`
   - `top_k_per_seed=200`
   - `shrinkage_alpha=0.0`
   - `allow_over_hot=true`
   - route/eval 侧使用 `per_user_candidate_cap=500` 做预算上限。
2. 用户桶：
   - `sequence_sufficient + collaborative_rich + medium_behavior`
3. item 桶：
   - `cf_ready + embedding_ready`
4. 热门控制：
   - 当前不采用 hot-dst 硬排除；必须通过 source overlap、popular/category 重复率和 route budget 判断是否有边际价值。
5. 暂缓项：
   - BM25/IDF、support>=2/3、hot-dst 排除在本轮诊断中 raw Recall 损失过大，不作为第一版修复主路，只保留为后续高精度窄源消融。
6. 输出：
   - method dataset manifest
   - source index manifest
   - evaluation report
   - source overlap report

通过门槛建议：

- `candidate_user_rate` 至少显著高于 strict 的 `0.004268`，建议先看是否能到 `>0.05` 作为最低诊断门槛。
- `in_universe_label_ratio` 明显高于 strict 的 `0.003921`。
- `raw_recall@500` 或 `in_universe_recall@500` 非 0。
- 若 Recall 非 0 但热门 overlap 过高，需要保持 `DIAGNOSTIC_ONLY`，不能 READY。

### 7.3 高成本：server formal profile + source overlap / marginal Recall gate

目的：判断 `itemcf_weak` 是否对 pool500 READY sources 有边际价值。

需要对比：

- `popular`
- `category`
- `swing_recall`
- `itemcf_strong`
- `usercf_recall`

指标：

- source overlap：candidate item overlap、user coverage overlap、seed overlap。
- marginal Recall@K：加入 `itemcf_weak` 后相对 READY route 的新增命中。
- long-tail/new item coverage：是否只是在重复 popular/category。
- cost：row_count、shard_count、构建时间、内存、单用户候选数分布。

晋升要求：

```yaml
candidate_generation_allowed: true  # 仅当以下全部满足才考虑
requires:
  - train_only_for_construction: true
  - forbidden_scope_audit: PASS
  - formal_not_smoke: true
  - candidate_user_rate_materially_improved: true
  - recall_at_500_nonzero_or_fallback_value_proven: true
  - marginal_recall_against_ready_sources_positive: true
  - popularity_overlap_not_excessive: true
  - resource_cost_acceptable: true
```

若任一关键条件不满足，应继续保持：

```text
DIAGNOSTIC_ONLY
```

## 8. 不建议立刻做的事

1. **不建议直接把 strict formal 晋升 READY。** 现有 Recall@K 为 0，coverage 不达标。
2. **不建议只调排序。** 当前绝大多数用户没有候选，排序无法解决候选不可达。
3. **不建议用 valid/test label 反向扩 item universe。** 这会违反 train-only governance。
4. **不建议无约束放开 hot item。** 可能 Recall 变好但只是 popular source 的重复，损害互补性。
5. **不建议马上上 EASE/SLIM/FISM。** 它们可能更强，但需要矩阵构建、资源评估和新 artifact contract；应在 weak_coverage + BM25/shrinkage 仍不足后再升级。

## 9. 面试可讲点

这次失败不是“模型没调好”这么简单，而是一次典型的推荐系统工程诊断：

- 先确认数据治理和 artifact 构建是否正确：train-only、forbidden audit、source adapter row count 都通过。
- 再拆 Recall=0 的原因：发现核心是 candidate_user_rate、in-universe label ratio、source degree 太低。
- 进一步定位到用户桶和 item universe 策略：strict profile 与 weak recall 的定位冲突。
- 最后结合 ItemCF/Top-N/implicit feedback 论文，把方案从“调参”升级为“覆盖 profile + 去噪网格 + 候选预算 + route gate”的实验设计。

可复述为：

> 我没有把 Recall 为 0 简单归因于算法差，而是用 manifest lineage、drop reason、source graph degree、eval in-universe ratio 做分层诊断。结论是 strict profile 把弱召回过滤成了窄诊断图；进一步的远程网格说明 support=1 弱边虽然噪声高，但也是 raw Recall 来源。因此第一版修复是在 train-only 约束下保留 weak coverage，用 seed/user cap 控制候选爆炸，再通过 source overlap gate 验证边际 Recall，只有证明边际价值才允许晋升。
