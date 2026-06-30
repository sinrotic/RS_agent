# usercf_recall recent-2y 低覆盖问题论文调研与解决方案

日期：2026-06-03

## 1. 背景

`usercf_recall` recent-2y formal source artifact 已经构建成功，但覆盖不足：

- formal source：`outputs/recall/pool500_method_sources/recent_2y/usercf_recall/usercf_recent_2y_sciomc_formal_v1/source_index_manifest.json`
- `target_user_count=15884`
- `candidate_user_count=2081`
- `candidate_total_count=4043`
- `user_coverage_rate=0.131012`
- readiness：`DIAGNOSTIC_ONLY`

当前 blocker 不是构建失败，而是候选释放不足，尤其是：

- `only_seen_items_after_neighbor_merge=13803`
- `positive_count p50=15`，但 `unique_item_count p50=1`

这说明很多用户原始正反馈不少，但经过 `cf_ready / non-over-hot / eligible item sequence` 预处理后，可用于 UserCF 邻居扩展的 item 只剩很少。

## 2. 论文与经典方法依据

### 2.1 UserCF / kNN CF 的基本启发

- **Resnick et al., 1994, GroupLens**：User-based CF 的基本逻辑是寻找相似用户，并汇总邻居反馈。对本项目的启发是：UserCF 的价值不只在“找邻居”，还在“邻居能否贡献目标用户未见的新 item”。
- **Herlocker et al., 1999, Algorithmic Framework for Collaborative Filtering**：把 CF 拆成相似度、邻居选择、归一化、推荐生成等模块。对本项目的启发是：低覆盖应拆开看，是用户筛选、item 筛选、相似度、邻居 topK，还是候选去已看导致。
- **Sarwar et al., 2001, Item-Based CF**：虽然主讲 ItemCF，但指出 kNN 方法受稀疏性和在线计算成本影响。对 UserCF 的启发是：不能只扩大邻居数，必须同时做资源 guard 和噪声控制。
- **Koren, 2008, Factorization Meets the Neighborhood**：邻域方法能补充隐因子方法，优势是局部相似和解释性。对本项目的启发是：UserCF 更适合做 heavy 用户 supplemental/diagnostic source，而不是替代主路。

### 2.2 implicit feedback 与 Top-N 排序

- **Hu, Koren & Volinsky, 2008, Collaborative Filtering for Implicit Feedback Datasets**：隐式反馈要区分 preference 与 confidence，交互次数/行为强度是置信度，不等于显式评分。对本项目的启发是：UserCF 不应把未交互当强负样本，也不能把 eval label 回灌候选生成；但可以用行为数、item 频次、用户桶做置信度控制。
- **Rendle et al., 2009/2012, BPR**：隐式反馈推荐应优化 personalized ranking，而不是评分重建。对本项目的启发是：UserCF 的 formal 判断必须落到 Recall@K / HitRate@K / NDCG@K，而不是只看 source 是否能构建。
- **Cremonesi et al., 2010, Top-N Recommendation Evaluation**：Top-N 评估受候选集和负采样方式影响很大。对本项目的启发是：如果 UserCF item universe 很窄，必须同时报告 full denominator 与 in-universe denominator，避免误判。

### 2.3 BM25 / TF-IDF / IUF 与热门惩罚

BM25/TF-IDF 的核心思想是：

- 高频词区分度低，应降低权重。
- 文档越长，匹配越容易，需要长度归一化。
- 词频增长应饱和，不能线性无限加分。

映射到 UserCF：

- 用户 = document
- item = term
- 用户历史长度 = document length
- item 被多少用户交互 = document frequency
- IUF/IDF = 降低热门 item 的邻居贡献
- BM25 length normalization = 降低超长用户历史导致的伪相似

对本项目的启发：

- 当前策略直接用 `cf_ready=true and over_hot=false` 过滤，安全但可能过窄。
- 对热门 item 不一定要直接 drop；更合理的 next step 是对比：drop hot vs keep hot with IUF/BM25-like downweight。
- 如果直接 drop 导致 `unique_item_count p50=1`，说明召回空间被截断，需要放宽 item universe 或改为降权。

### 2.4 coverage / diversity / popularity bias

- **McNee et al., 2006, Being Accurate is Not Enough**：准确率不是唯一目标，还要看覆盖、多样性、新颖性和用户体验。
- **Adomavicius & Kwon, 2012, diversity**：推荐列表容易被头部 item 垄断，需要 aggregate diversity 控制。
- popularity bias 相关工作：热门 item 会同时提升表面命中和降低个性化，需要用 popularity concentration、source overlap、long-tail coverage 检查。

对本项目的启发：

- UserCF 不能只用 Recall@K 晋升；还要看 source overlap、热门集中度、长尾/中频 item 占比、用户桶覆盖。
- 如果放宽过滤后 Recall 上升但 overlap/popularity concentration 过高，也不应直接 READY。

## 3. 当前低覆盖的证据诊断

### 3.1 预处理后 eligible item 过窄

formal coverage audit：

```text
positive_count:
  min=10, p50=15, p90=41, max=50

unique_item_count:
  min=1, p50=1, p90=2, max=9

train_only_overlap_potential:
  min=1, p50=1, p90=2, max=9
```

解释：用户原始正反馈数中位数 15，但进入 UserCF 构图的 unique item 中位数只有 1。这几乎必然导致邻居合并后只剩目标用户已见 item。

### 3.2 过滤原因集中在 item universe

formal method dataset manifest：

```text
user_bucket_not_allowed: 6777082
no_cf_ready_non_over_hot_items: 33835
item_over_hot: 335032
item_not_cf_ready: 416006
```

解释：用户桶过滤是方法定位的一部分，但 `item_over_hot` 与 `item_not_cf_ready` 大量出现，说明 item 侧过滤显著收缩了可召回空间。

### 3.3 不是资源不足

formal resource audit：

```text
peak_rss_mb=67
runtime_seconds=0.598863
target_user_count=15884
candidate_user_count=2081
candidate_total_count=4043
```

解释：这次不是资源跑不动，也不是 batch/shard 失败，而是候选空间本身被压窄。

### 3.4 当前结论

最可能原因：

> 当前 UserCF 的 `cf_ready + non-over-hot + eligible_item_sequence` 过滤过于保守，使多数用户只剩 1-2 个 eligible item；邻居虽然存在，但邻居合并后新 item 被过滤掉或只剩目标用户已看 item。

但还不能直接断言“过滤错了”，需要下一步用 valid/test 做 evaluation-only 诊断，确认未来正样本是否位于 raw neighbor reachable universe。

## 4. 解决方案总思路

不要马上把 UserCF 直接放宽并晋升。推荐三阶段：

1. **先证明有没有未来预测信号**：raw neighbor reachability。
2. **再定位是哪个过滤层截断了候选**：filtered-vs-raw ablation。
3. **最后选择降权/放宽策略重建 source artifact**：IUF/BM25-like、mid-frequency item、hot item keep-with-penalty。

## 5. 阶段一：raw neighbor reachability 诊断

目标：回答 UserCF 对后续窗口是否有潜在价值。

### 5.1 实验定义

对每个评估用户 u：

1. 只用 train 构建相似邻居。
2. 不使用 valid/test 参与邻居构建。
3. 用 valid/test label 只做评估。
4. 检查 valid/test 正样本是否出现在：
   - raw neighbor train items
   - filtered eligible neighbor items
   - final UserCF candidates

### 5.2 指标

建议输出：

```text
raw_neighbor_reachable_label_count
filtered_neighbor_reachable_label_count
final_candidate_hit_count
label_total_count
raw_reachability_rate
filtered_reachability_rate
final_recall_at_k
raw_to_filtered_loss_rate
filtered_to_final_loss_rate
```

### 5.3 判断

- 如果 raw reachability 高，但 filtered reachability 低：说明预处理过滤截断了有效未来候选。
- 如果 raw reachability 也低：说明 UserCF 邻居结构本身对未来窗口弱，不应重点优化。
- 如果 filtered reachability 高但 final recall 低：说明排序/topK/去已看/候选截断环节有问题。

## 6. 阶段二：过滤 ablation

围绕 item universe 做小规模对照，不直接跑全主路。

### 6.1 推荐实验组

| 组别 | 变化 | 目的 |
| --- | --- | --- |
| A baseline | 当前 `cf_ready && non-over-hot` | 当前对照 |
| B allow embedding_ready | `cf_ready ∪ embedding_ready`，仍过滤 over-hot | 增加 item universe |
| C allow mid/head with IUF | 保留更多高频 item，但用 IUF/IDF 降权 | 验证 drop vs downweight |
| D hot seed allowed, hot candidate excluded | 热门 item 可作为相似度 seed，但不作为候选输出 | 利用热门 item 找邻居，但避免热门候选污染 |
| E min unique item guard | 只保留过滤后 unique item ≥ 2/3 的用户 | 提高邻居质量，减少 only-seen |
| F raw-neighbor diagnostic | 用 raw train items 做 reachability，不产正式候选 | 只判断潜在上限 |

### 6.2 必看指标

- candidate_user_count / target_user_count
- candidate_total_count
- Recall@K / HitRate@K / NDCG@K
- in-universe recall
- source overlap with popular/category/swing/itemcf
- popularity concentration：top item share、head/mid/tail 分布
- unique item per user 分布
- only_seen_items_after_neighbor_merge 占比
- peak_rss_mb / runtime

## 7. 阶段三：候选生成策略改造方向

### 7.1 从 drop hot 改为 keep-hot-as-signal / downweight-as-candidate

当前 drop hot 可能让用户只剩 1 个 eligible item。建议拆成两层：

```text
similarity_seed_items: 可允许部分热门/embedding_ready item，但做 IUF/BM25 降权
candidate_output_items: 继续过滤极热门 item，或限制热门候选占比
```

这样可以用热门 item 帮助找到邻居，但不让热门 item 直接污染候选输出。

### 7.2 IUF cosine / BM25-like UserCF

候选相似度可以从简单 overlap 改成：

```text
weight(item) = log((N + 1) / (user_freq(item) + 1))
user_norm = BM25-like length normalization
sim(u, v) = sum_i weight(i) over shared items / normalized_length
```

工程上先不要一步到位复杂化，可以先实现离线 ablation：

- weighted_overlap
- iuf_cosine
- bm25_user_similarity

### 7.3 minimum post-filter unique item guard

如果某用户过滤后只有 1 个 item，UserCF 很难给出新候选。建议：

- source 构建时报告 `post_filter_unique_item_count` 分层。
- 对 unique item < 2 或 < 3 的用户，不强行计入 UserCF target_user_count，转给 popular/category/itemcf fallback。
- 同时保留这些用户的 raw reachability 诊断，判断是否是过滤过窄导致。

### 7.4 两阶段候选池

构建两个池：

1. `strict_candidates`：当前 cf_ready/non-hot，质量高但覆盖低。
2. `relaxed_candidates`：放宽 item universe + IUF/BM25 penalty，覆盖更高但需 popularity/source-overlap gate。

最终 route gate 决定是否只使用 strict、strict+relaxed，或只保留 diagnostic。

## 8. 可复用仓库入口

只读搜索定位到以下可复用入口：

- UserCF source 构建：`rs_lab/experiments/recall/pool500/methods/usercf_recall/builder.py`
- 候选融合与去重：`rs_core/recsys/candidate_merge.py`
- 全链路 recall-only 与 source overlap：`rs_lab/experiments/recall/run_full_data_pool500_recall_only.py`
- route gate / in-universe denominator 校验：`rs_core/workflow/full_data_pool500_route_gate.py`
- Recall@K baseline：`rs_lab/experiments/recall/run_pool500_offline_eval_baseline.py`
- label artifact：`rs_lab/experiments/recall/build_pool500_label_artifact.py`
- shadow audit：`rs_lab/experiments/recall/validate_pool500_recall_layer_shadow_audit.py`

建议下一步先新增或复用诊断脚本，输出 `raw_neighbor_reachability_report.json`，再决定是否改 builder。

## 9. 推荐执行路线

### Step 1：做 raw-vs-filtered reachability，不改主 artifact

产物建议：

```text
outputs/recall/pool500_method_diagnostics/recent_2y/usercf_recall/raw_vs_filtered_reachability_v1/report.json
```

必须保证：valid/test 只作为 evaluation labels。

### Step 2：做 3-5 组 item filtering ablation

优先顺序：

1. baseline strict
2. `cf_ready ∪ embedding_ready`
3. hot seed allowed + hot candidate excluded
4. IUF cosine
5. BM25-like length norm

### Step 3：用 source overlap 和 in-universe recall 收口

如果 relaxed 组提升 Recall 但高度重叠 popular 或热门集中，仍不晋升。

### Step 4：再更新 UserCF source artifact

只有当 ablation 证明：

- coverage 明显提升
- Recall@K 有收益
- source overlap 可接受
- popularity concentration 不失控
- no-holdout audit PASS
- 资源可控

才考虑生成 `usercf_recent_2y_relaxed_iuf_v1` 或类似新 run。

## 10. 当前建议

本轮不应直接把 `usercf_recall` 从 `DIAGNOSTIC_ONLY` 晋升，也不建议只靠扩大 `similar_users_top_k` 解决。真正优先级是：

1. 先做 raw neighbor reachability，验证未来窗口预测信号是否存在。
2. 如果 raw 有信号，再把 hot item / embedding_ready 从“直接 drop”改成“分层降权/限制输出”。
3. 如果 raw 没信号，则停止 UserCF 晋升，保留为诊断源。

### 10.1 已执行的 bounded smoke 诊断

已新增并运行只读诊断脚本：

```text
scripts/experiments/recall/pool500/diagnose_usercf_raw_vs_filtered_reachability.py
```

bounded smoke 产物：

```text
outputs/recall/pool500_method_diagnostics/recent_2y/usercf_recall/raw_vs_filtered_reachability_v1/report.json
```

本次仅取 `target_user_limit=100`，valid/test 只作为 evaluation-only label，不参与邻居构建或候选生成。结果：

```text
label_total_count=20
raw_neighbor_reachable_label_count=1
filtered_neighbor_reachable_label_count=0
final_candidate_hit_count=0
raw_reachability_rate=0.05
filtered_reachability_rate=0.0
final_recall_at_k=0.0
raw_to_filtered_loss_rate=1.0
```

解释：小样本 smoke 初步显示 raw 邻居空间中存在少量未来 label 可达，但 strict filtered eligible item universe 把这部分信号截断；该结果支持继续做更大范围 reachability / filtering ablation，但不足以作为 formal 效果或晋升依据。

一句话：

> 当前 UserCF 的问题很可能是预处理把可扩展 item universe 收得太窄；解决方向不是盲目放宽，而是用 raw-vs-filtered reachability + IUF/BM25-like ablation 证明哪些过滤应该保留、哪些应改为降权。

### 10.2 relaxed IUF smoke 已执行

已实现 `usercf_relaxed_iuf` profile 和 sidecar `scoring_policy=iuf_cosine`：

- method dataset：`outputs/recall/pool500_method_datasets/recent_2y/usercf_relaxed_iuf_v1/smoke/usercf_method_dataset/method_dataset_manifest.json`
- source artifact：`outputs/recall/pool500_method_sources/recent_2y_usercf_relaxed_iuf_smoke/usercf_recall/usercf_recent_2y_relaxed_iuf_smoke_v1/source_index_manifest.json`
- eval report：`outputs/recall/pool500_method_evals/recent_2y/usercf_relaxed_iuf_smoke_v1/method_source_eval_report.json`

核心变化：

```text
eligible_user_buckets = sequence_sufficient ∪ collaborative_rich
eligible_item_buckets = cf_ready ∪ embedding_ready
hot item = allow as similarity signal, but IUF downweighted
sidecar scoring_policy = iuf_cosine
```

smoke 结果：

```text
method_dataset.row_count=5000
method_dataset.item_count=19097
source.candidate_user_count=3783
source.candidate_total_count=169565
source.underfilled_user_coverage=0.7566
candidate_count.p50=20
candidate_count.p90=117
candidate_count.max=500
peak_rss_mb=73
```

evaluation-only 结果：

```text
scored_user_count=25
Recall@20=0.04
Recall@50=0.04
Recall@100=0.04
Recall@500=0.04
HitRate@20/50/100/500=0.04
```

解释：这证明 relaxed item universe + IUF 降权在 smoke 范围内显著改善了候选覆盖，并出现少量未来窗口命中；但 `scored_user_count=25`，仍不能作为 formal 效果或主路晋升依据。下一步应进入 formal / route-gate / source-overlap / popularity concentration 审计，而不是直接把 `usercf_recall` 标成 READY。
