# itemcf_weak

## 方法定位

`itemcf_weak` 是 pool500 recent-2y 召回体系中的 **宽覆盖 ItemCF / item-to-item 弱共现辅助召回**。它基于 train-only 用户正反馈序列构建 item-item 边，服务 medium/heavy 行为用户的 seed item 扩展，目标是补充候选覆盖和潜在长尾/中频 item 可达性。

当前本方法已从旧的 strict/formal flat edge dataset 路线收口到 **src3/dst3/user2/keep-hot/cosine ItemCF source adapter** 路线。当前状态晋升为 `READY_GUARDED_SOURCE_ADAPTER_READY`：选定矩阵/边口径已经固定，source index 已构建并接到 recall-only 默认 `itemcf_weak` manifest，可被主路 loader 读取；但 source manifest 仍保持 `DIAGNOSTIC_ONLY` 治理标记，不替代 `popular`、`category`、`swing_recall` 等已并入主路的 source，也不直接替换 ranking input。

## 当前 readiness

- 状态：`READY_GUARDED_SOURCE_ADAPTER_READY`
- 当前主产物：`src3_dst3_user2_keep_hot_cosine_v1` sharded source index `PASS`
- source manifest：`outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/src3_dst3_user2_keep_hot_cosine_v1/source_index_manifest.json`
- source row/edge count：`16,454,229`
- shard count：`64`
- formal method dataset：`cold_u2_i3_cosine_seed200` train-only edge rows，作为当前 source adapter 输入
- smoke dataset：仅用于 program/schema/gate 测试，不参与规则选择或晋升
- 是否允许 candidate generation：`false`
- 是否允许 ranking input replacement：`false`
- 是否允许 promotion / final pool500 ready：`false`

晋升边界：本次 READY 指 **ItemCF 方法口径、边矩阵和 source adapter 已固定并可被主路 loader 读取**，不是自动最终晋升。candidate generation 权限、ranking replacement、pool1000 或 final pool500 仍需完整 route gate、source overlap、marginal Recall 和 stoploss 通过后再单独打开。

## recent-2y 治理契约

本轮 current artifact 只允许使用：

- `data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json`
- `train_only_governance/user_quality_profile.jsonl`
- `train_only_governance/item_quality_profile.jsonl`
- `train_only_governance/item_frequency_train.jsonl`
- `user_sequences.train.jsonl`

禁止作为构建/训练/候选生成输入：

- holdout / valid / test
- LOPO / oracle / eval label
- clean_10000 / pool1000
- 旧 full-data-derived method dataset 或旧 sidecar artifact

valid/test label 仅可用于 `evaluation_report.json` 的后验评估，不能反向参与边图、候选或 source index 构建。

## SciOMC 调研与 RALPLAN

- SciOMC 调研：`dic/recall_methods/itemcf_weak/RECENT2Y_SCIOMC_RESEARCH.md`
- RALPLAN 计划：`dic/recall_methods/itemcf_weak/RECENT2Y_REBUILD_PLAN.md`
- 低效果诊断与修复方案：`dic/recall_methods/itemcf_weak/RECENT2Y_FAILURE_DIAGNOSIS_AND_FIX_PLAN.md`

论文/实践依据包括：Sarwar et al. 2001 item-based CF、Linden et al. 2003 Amazon item-to-item、Deshpande & Karypis 2004 Top-N ItemKNN、Hu/Koren/Volinsky implicit feedback、BPR、SLIM、FISM、EASE、Cremonesi/Koren/Turrin Top-N evaluation、热门偏置/长尾推荐和可复现推荐系统评估。补充调研 KDD 2019 `Enhancing Collaborative Filtering with Generative Augmentation` 后确认：AugCF 不是一个可直接替换 `weighted_cooc / sqrt(src_user_count * dst_user_count)` 的显式 item-item similarity 公式，而是用 conditional GAN / Gumbel-Softmax 为 inactive/sparse users 做生成式交互增强。因此当前只落地 `augcf_lite` 诊断 profile：复刻“train-only 生成增强后重算 CF score”的工程思想，不声明完整 GAN 复现；strict formal 失败主因仍是用户桶、item universe 和 source 边图过窄，第一版主路修复仍以 `weak_denoised + route gate` 为准。

## 数据与矩阵策略

当前 `itemcf_weak` 已固定为 train-only `src3_dst3_user2_keep_hot_cosine` 口径：先按 item 正向用户数筛 eligible item，再按过滤后的用户正反馈序列要求 `eligible positive items >= 2`，最后按 Datawhale ItemCF 余弦公式 `weighted_cooc / sqrt(src_user_count * dst_user_count)` 输出有向 item-item 边。valid 月只参与后验筛选证据，不进入构建输入。

### smoke

- 作用：仅用于 program/schema/gate validation，不参与正式矩阵构建、候选生成、规则选择或晋升。
- 历史 smoke manifest：`outputs/recall/pool500_method_datasets/recent_2y/collab_v1_smoke/itemcf_weak/method_dataset_manifest.json`
- scale tier：`smoke`
- profile：`strict`
- promotion_allowed：`false`

### formal source dataset

- 当前策略：`selected_train_only_source_rows`
- `custom_dataset_required=true`
- method dataset manifest：`outputs/recall/pool500_method_datasets/recent_2y/itemcf_weak_cold_filtered_valgrid_20260606c/cold_u2_i3_cosine_seed200/itemcf_weak/method_dataset_manifest.json`
- source manifest：`outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/src3_dst3_user2_keep_hot_cosine_v1/source_index_manifest.json`
- row/edge count：`16,454,229`
- shard count：`64`
- 原 strict formal flat dataset / source index 只保留为历史失败诊断，不再作为 current route、latest artifact 或 READY 判断依据。

### 当前正式主产物

- artifact type：`sharded_item_pair_source_index`
- source manifest：`outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/src3_dst3_user2_keep_hot_cosine_v1/source_index_manifest.json`
- dataset variant：`src3_dst3_user2_keep_hot_cosine_v1`
- 筛选口径：`src>=3,dst>=3,user_after_item_filter>=2,keep_hot`
- score policy：`weighted_cooc_cosine_normalized_v1`
- flat method dataset rows written：`true`

### 主路接入 smoke

已将 `run_full_data_pool500_recall_only.py` 的默认 `itemcf_weak` source manifest 指向 `src3_dst3_user2_keep_hot_cosine_v1`，并在远程执行 1000-user isolated route smoke：

- output dir：`outputs/recall/full_data_pool500_recall_only/itemcf_weak_src3_dst3_user2_keep_hot_cosine_smoke1000_v2`
- processed users：`1000`
- candidate rows：`500000`
- `itemcf_weak` contribution rows：`19540`
- `itemcf_weak` user coverage：`643 / 1000 = 0.643`
- marginal candidate share：`0.03908`
- loader contract：`load_itemcf_source_manifest(..., allowed_src_items)` 抽样通过
- smoke decision：`STOP`，原因是 isolated smoke 显式禁用了 `swing_recall` / `usercf_recall` 等 ready sources 后触发 unrelated ready-source stoploss；ItemCF source 本身可加载、有贡献，仍保持 `DIAGNOSTIC_ONLY` 和 promotion closed。

## 历史 source artifact

以下 strict flat-dataset source 只作为历史诊断记录，用于说明旧路线失败原因；实体 artifact 已在清理记录 `dic/recall_methods/itemcf_weak/CLEANUP_RECORD_2026_06_07.md` 中登记并删除，它不是当前 latest artifact。

### smoke source

- manifest：`outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/smoke_strict_v1/source_index_manifest.json`
- `status=PASS`
- `row_count=4152`
- `sharded=false`
- `candidate_generation_allowed=false`

### formal source

- manifest：`outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/formal_strict_v1/source_index_manifest.json`
- evaluation report：`outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/formal_strict_v1/evaluation_report.json`
- `status=PASS`
- `row_count=17866`
- `sharded=true`
- `shard_count=8`
- `source_status=DIAGNOSTIC_ONLY`
- `candidate_generation_allowed=false`
- `ranking_input_replacement_allowed=false`
- `promotion_allowed=false`

## 历史 strict formal 后验评估

评估报告：`outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/formal_strict_v1/evaluation_report.json`

评估边界：valid/test label 仅在后验评估阶段读取，不参与 method dataset 或 source index 构建。

关键结果：

- `evaluated_users_with_train_sequence=54362`
- `raw_label_total=71669`
- `in_universe_label_total=281`
- `in_universe_label_ratio=0.003921`
- `users_with_seed_hit=274`
- `seed_hit_user_rate=0.00504`
- `users_with_candidates=232`
- `candidate_user_rate=0.004268`
- `candidate_count_stats.max=14`
- `raw_recall@50=0.0`
- `raw_recall@100=0.0`
- `raw_recall@500=0.0`
- `in_universe_recall@50=0.0`
- `in_universe_recall@100=0.0`
- `in_universe_recall@500=0.0`

结论：strict formal 边图的 item universe 和 seed 命中覆盖过窄，在当前评估集上没有产生可证明召回收益。因此不建议从 strict formal alone 晋升 READY，也不建议进入主路候选生成。

## weak_coverage 后验诊断

为验证 strict 失败是否主要来自覆盖过窄，本轮复核了既有 `weak_coverage` method dataset，并基于 method dataset rows 做 evaluation-only 流式候选模拟。该诊断没有生成完整 formal source artifact，也没有把 valid/test label 用于构建；valid/test label 只用于后验评估。

method dataset：

`outputs/recall/pool500_itemcf_new_dataset/method_datasets_smoke/itemcf_weak/method_dataset_manifest.json`

诊断报告：

`outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/weak_coverage_eval_from_method_dataset_v1/evaluation_report.json`

关键结果：

- `row_count=4445902`
- `user_count=120000`
- `item_count=185326`
- `source_item_union_count=185326`
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

结论：`weak_coverage` 明显恢复候选可达性和非零 Recall，证明 strict profile 过窄是主要失败原因。但该结果仍是 method dataset diagnostic，不是完整 source artifact；并且 `candidate_count_stats.max=4569`、support=1 边占比高，说明候选爆炸和弱边噪声需要通过 per-seed/per-user cap 与 source overlap / route gate 控制。因此当前仍保持 `DIAGNOSTIC_ONLY`，不打开 candidate generation。

### 去噪网格远程诊断

在授权远程服务器 `server:/home/luo/RS_agent_remote` 上运行了 evaluation-only 去噪网格，报告已拉回：

`outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/weak_coverage_denoising_grid_v2/evaluation_report.json`

关键结论：

- `baseline_support1_no_cap`：`raw_recall@500=0.01478`、`in_universe_recall@500=0.021617`、`candidate_user_rate=0.83305`、candidate max `4569`。
- `support1_existing_seed200_user500`：保持 `raw_recall@500=0.01478`、`in_universe_recall@500=0.021617`、`candidate_user_rate=0.83305`，但 candidate max 降到 `500`。
- `support>=2`：candidate max 降到 `109`，但 `raw_recall@500` 降到 `0.005789`。
- `BM25/IDF + shrinkage + hot-dst non-hot`：`raw_recall@500` 只有 `0.000051` 或 `0.0`，当前不适合作为第一版修复主路。

因此第一版修复不是强行过滤 support=1 或排热门，而是新增 `weak_denoised` profile：保留 `support=1 + existing weighted cosine` 的宽覆盖能力，设置 `top_k_per_seed=200`，并要求 route/eval 侧 `per_user_candidate_cap=500`、overlap/marginal Recall gate 通过后才允许讨论候选源权限。

### AugCF-lite 历史诊断结论与产物清理

针对 KDD 2019 AugCF 的相似度问题，已确认论文核心不是一个可直接替换 `weighted_cooc_cosine_normalized_v1` 的显式 item-item sim，而是面向 sparse/inactive users 的生成式交互增强。此前在 `itemcf_weak` 上做过 `augcf_lite`、v2 score/cap 网格和 v3 sparse/side-info 三轮 eval-only 诊断，结论如下：

- AugCF-lite 的收益主要来自 augmented graph 扩大 seed 可达性，而不是 pseudo score 权重本身。
- v3 最优 `sideinfo_category_boost_v1` 只有极小增益：`raw_recall@500=0.024707`、`sparse hit@500=0.018064`、candidate p50/p90/max=`200/400/500`。
- sparse-targeted fanout/cap 压缩没有提升 sparse hit，反而降低全局 Recall。
- 完整 AugCF GAN/Gumbel-Softmax 复刻需要训练闭环、side-info encoder 和更重的 artifact 治理，当前阶段性价比不如轻量 RPA-lite。

在用户确认放弃该方向后，`itemcf_weak` 下 AugCF-lite 本地结果目录已删除，不再作为当前主线 artifact 保留：

- `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/augcf_lite_eval_seed200_user500_v1`
- `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/augcf_lite_v2_grid_seed_cap_score_v1`
- `outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/augcf_lite_v3_sparse_sideinfo_v1`

AugCF-lite 只保留为历史消融结论和论文对照口径，不再进入 `itemcf_weak` 后续优化主线。

### Recursive CF / RPA-lite 10GB 分片诊断

继续复核 Zhang & Pu 2007 `A recursive prediction algorithm for collaborative filtering recommender systems` 后，本轮将论文里的“未评目标 item 的相似邻居可先递归预测后参与上层预测”改造成当前 implicit Top-N 召回可用的 **RPA-lite**：不照搬 explicit rating prediction 公式，也不做多层在线递归，而是用 train-only user-user IUF 相似传播，为 sparse/medium 用户生成少量 pseudo candidates。论文依据：RecSys 2007，DOI `10.1145/1297231.1297241`，核心思想是通过递归/间接邻域补全缓解评分矩阵稀疏性；对当前项目只借鉴 bounded neighbor expansion，不照搬 MAE 评分预测目标。

先按用户要求在本地限制 10GB 内存跑 hash-sample 诊断，随后迁移到远程服务器做 20 分片聚合诊断：

- 本地 hash-sample：`outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/rpa_lite_local_10gb_v1/evaluation_report.json`
- 远程 20 分片聚合：`outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/rpa_lite_local_10gb_sharded_remote_v1/evaluation_report.json`

治理边界：target selection 只使用 train-only sequence bucket 和 deterministic user_id hash shard；valid/test label 在 train-only RPA-lite candidate scores 构建完成后才加载，只用于 post-hoc evaluation；不写正式 candidates，不打开 candidate generation / promotion。该结果仍是 eval-only diagnostic evidence，不是 READY source artifact。

| variant | raw_recall@500 | in_universe_recall@500 | sparse hit@500 | medium hit@500 | candidate p50/p90/max | 解释 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| `rpa_iuf_sparse_medium_p50_user500_sharded10gb` | `0.022538` | `0.051251` | `0.021031` | `0.046375` | `50/50/50` | sparse 已超过 AugCF-lite v3，但 raw 低于 v3 best |
| `rpa_iuf_sparse_medium_p100_user500_sharded10gb` | `0.026407` | `0.050346` | `0.024730` | `0.053875` | `100/100/100` | 当前最优；raw、sparse、medium 均超过 AugCF-lite v3 |
| `rpa_iuf_sparse_only_p100_user500_sharded10gb` | `0.014190` | `0.030516` | `0.024730` | `0.000000` | `38/100/100` | sparse 命中可用，但放弃 medium 导致 global 低 |

远程聚合范围：20/20 shards 完成，`train_only_target_users_total=5,147,753`，`evaluated_target_users_with_labels_total=41,605`，每分片峰值 RSS 最大 `6.8637GB`，低于 10GB guard。最优 `rpa_iuf_sparse_medium_p100_user500_sharded10gb` 相比 AugCF-lite v3 best：

- `raw_recall@500`：`0.024707 -> 0.026407`，绝对提升 `+0.001700`。
- `sparse hit@500`：`0.018064 -> 0.024730`，绝对提升 `+0.006666`。
- `medium hit@500`：`0.053702 -> 0.053875`，小幅提升 `+0.000173`。
- 候选预算：从 `200/400/500` 降到 `100/100/100`。

决策：后续 `itemcf_weak` 优化主线正式从 AugCF-lite 切到 RPA-lite sparse/medium user augmentation。RPA-lite 已补齐 diagnostic replay artifact：`outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/rpa_lite_diagnostic_replay_v1/rpa_lite_replay_manifest.json`，同时保留 `candidate_artifact_written=false`、`candidate_generation_allowed=false`、`promotion_allowed=false`。该 artifact 用于治理、审计和后续 overlap/route-gate 复核，不是 READY source；不能仅凭 eval-only replay 更新 registry READY。

### RPA paper-binary Top500 远程诊断

在 v3 paper-faithful depth1 只做 bounded top100 rerank 后，进一步按论文显式评分预测的口径做更接近的 binary implicit 适配：去掉候选构建阶段的额外 IDF 偏置（`candidate_idf_power=0.0`），把每用户候选预算放宽到 `500`，仍只使用 train-only sequence/user-user similarity 构建候选，valid/test label 仅用于 post-hoc evaluation。

远程输出：`outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/rpa_lite_v4_paper_binary_p500_remote_no_mem_limit_4jobs_v1/evaluation_report.json`。

| variant | raw_recall@500 | in_universe_recall@500 | hit_user_rate@500 | sparse hit@500 | medium hit@500 | candidate p50/p90/max | 解释 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `rpa_v4_paper_binary_sum_similarity_p500` | `0.038220` | `0.056959` | `0.046821` | `0.034529` | `0.078614` | `194/500/500` | 当前 RPA 系列最强诊断；收益主要来自去掉 IDF 偏置并放宽 Top500 候选预算 |
| `rpa_v4_paper_binary_observed_neighbor_mass_p500` | `0.038220` | `0.056959` | `0.046821` | `0.034529` | `0.078614` | `194/500/500` | observed neighbor mass 归一化对同一用户是常数，排序等同 sum-similarity |
| `rpa_v4_paper_binary_recursive_lambda05_depth1_p500` | `0.038220` | `0.056955` | `0.046821` | `0.034529` | `0.078614` | `194/500/500` | depth1 recursive 只轻微改变 top50/top100 排序，对 Recall@500 无额外增益 |
| `rpa_v4_paper_binary_recursive_lambda05_depth1_idf025_p500_sensitivity` | `0.037814` | `0.056132` | `0.046268` | `0.034029` | `0.077924` | `194/500/500` | 额外 IDF sensitivity 仍降低效果，不作为主线 |

相对 v2 confidence best（`raw_recall@500=0.026923`、`hit_user_rate@500=0.033506`、candidate p50/p90/max=`100/100/100`），v4 best 提升：`raw_recall@500 +0.011297`、raw hits `+613`、hit users `+554`、sparse hit `+0.009499`、medium hit `+0.023188`。但它使用更大的候选预算（p90/max 到 500），因此仍是 `DIAGNOSTIC_ONLY`，后续必须做 route-level overlap、边际 Recall 和预算治理后才能讨论 source adapter 或候选生成权限。

### RPA index-backed Top500 远程诊断

按论文中的用户-物品评分矩阵、邻居索引和递归预测思想，进一步把 v4 的 train-only replay 改造成 compact RPA index-backed 诊断：每个 shard 在构建候选后写出 `rpa_index_manifest.json`、`user_neighbor_samples.jsonl`、`candidate_evidence_samples.jsonl` 和 `index_sample_stats.json`，用于记录 implicit binary rating adapter、`unknown_not_zero` missing policy、top-K neighbor、path support 与候选证据。该 index 仍是诊断快照，不写正式 candidates，不打开 candidate generation / promotion。

远程输出：`outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/rpa_lite_v5_rpa_index_replay_remote_no_mem_limit_4jobs_v1/evaluation_report.json`。

| variant | raw_recall@50 | raw_recall@100 | raw_recall@500 | in_universe_recall@500 | hit_user_rate@500 | sparse hit@500 | medium hit@500 | candidate p50/p90/max | 解释 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `rpa_v5_index_observed_p300` | `0.023367` | `0.026997` | `0.034682` | `0.054866` | `0.042663` | `0.031896` | `0.070511` | `194/300/300` | Top300 不足以覆盖 v4 Top500 后段命中，候选预算下降但 Recall@500 明显回落 |
| `rpa_v5_index_observed_p500` | `0.023367` | `0.026997` | `0.038312` | `0.057111` | `0.046893` | `0.034595` | `0.078700` | `194/500/500` | 在 v4 observed baseline 上因更大的 candidate score cache/top-neighbor index 产生极小提升 |
| `rpa_v5_index_path_support_log_p500` | `0.024012` | `0.027734` | `0.038644` | `0.057662` | `0.047158` | `0.034562` | `0.079735` | `194/500/500` | 当前 v5 最优；path support log 重排改善 top50/top100，并在 Top500 增加 23 个 raw hits |
| `rpa_v5_index_min_support2_fallback_p500` | `0.023367` | `0.026997` | `0.038459` | `0.057382` | `0.047038` | `0.034629` | `0.079131` | `194/500/500` | φ-like path support gate 有小幅收益，但弱于 path support log |
| `rpa_v5_index_recursive_expand_lambda05_obs400_rec100_p500` | `0.023459` | `0.027310` | `0.037888` | `0.057499` | `0.046485` | `0.034829` | `0.076631` | `209/400/500` | observed 400 + recursive 100 降低 p90 候选量，但 Recall@500 低于 v4/v5 observed p500，说明当前递归扩展还未转化为有效新增命中 |

相对 v4 best（`rpa_v4_paper_binary_sum_similarity_p500`，`raw_recall@500=0.038220`、raw hits `2074`、hit users `1948`），v5 best `rpa_v5_index_path_support_log_p500` 提升：`raw_recall@500 +0.000424`、`raw_recall@100 +0.000774`、raw hits `+23`、hit users `+14`、medium hit `+0.001121`，candidate p50/p90/max 仍为 `194/500/500`。代价是峰值 RSS 从 `12.5566GB` 增加到 `14.9178GB`，总 shard runtime 从 `27813.51s` 增加到 `38585.69s`。结论：index-backed + path-support 重排是当前最优诊断，但增益很小；recursive expansion 本身未胜出，后续若继续贴近论文，应优先补真正的 user-user co-rated overlap 阈值 `φ`、显式拆分 `K/K′` 和受控 `ζ=2` scoring，而不是直接把 recursive expansion 晋升为 source。

## 资源画像

本轮 formal strict 在本地 `.venv` 下完成，输出 8 shard source edge index。当前规模较小，未触发 server 远程迁移；如果后续尝试 coverage profile（如扩展到 `sequence_sufficient`、`cf_ready/embedding_ready` 或更宽 hot item 控制），应按重资源任务处理：server 优先、分 shard、记录 manifest/stats/eval report 后再本地复核。

## 当前 blocker

1. matrix 已 READY，但还缺少正式 source adapter / route replay 入口。
2. 还缺少与 READY sources 的 source overlap、marginal Recall 和 route gate 证据。
3. candidate generation、ranking input replacement、pool1000、promotion 仍未打开。

## 当前路线更新：舍弃 RPA/生成增强方向，回到传统 ItemCF

用户已决定舍弃当前 `strongRPA`/RPA-lite/RPA-index 以及此前 AugCF-lite/生成增强类方法，后续改回传统 ItemCF 路线。这里保留最终诊断结果作为历史证据：

- `itemcf_weak` RPA-index best 为 `rpa_v5_index_path_support_log_p500`，`raw_recall@500=0.038644`、`raw_recall@100=0.027734`、`hit_user_rate@500=0.047158`、raw hits `2097`。
- 它相对 v4 best 只提升 `raw_recall@500 +0.000424`、raw hits `+23`，但峰值 RSS 从 `12.5566GB` 增加到 `14.9178GB`，总 shard runtime 从 `27813.51s` 增加到 `38585.69s`。
- recursive expansion variant `raw_recall@500=0.037888`，没有超过 observed/path-support p500，说明当前收益主要来自 path-support 重排，而不是 RPA 递归扩展本身。
- 这些结果继续保留为 `DIAGNOSTIC_ONLY`：不更新 registry READY，不打开 candidate generation / ranking input replacement / promotion，不把 eval-only replay 当正式候选源。

后续 `itemcf_weak` 主线改为传统 ItemCF：优先围绕 train-only 的 item-item 共现、weighted cooc / cosine normalization、active-user penalty、support/热度治理、per-seed topK 与 route-level source budget 做可解释优化；RPA/递归预测和 AugCF/GAN 方向仅作为历史消融记录。

## 历史传统 ItemCF 矩阵与当前 source adapter

按“舍弃 RPA/生成增强、回到传统 ItemCF”的路线，曾构建过 **filter-before-build** 的 `keep_hot_src2_dst3_user2` compact grouped item-to-neighbors 矩阵，用于验证“先筛 item，再筛 user”的口径是否有效。该矩阵不是当前 latest artifact；当前 latest artifact 已收口到 `src3_dst3_user2_keep_hot_cosine_v1` sharded source adapter。

历史 `src2/dst3/user2` 矩阵关键信息：

- 历史 dataset variant：`itemcf_weak_keep_hot_src2_dst3_filter_before_build_v1`
- 历史 matrix manifest：`outputs/recall/itemcf_matrices/recent_2y/itemcf_weak_keep_hot_src2_dst3_filter_before_build_traditional_matrix_v1/matrix_manifest.json`
- 历史矩阵规模：`src_item_count=421,365`、`edge_count=17,141,611`、`max_neighbors_per_src=200`、`shard_count=64`、`matrix_size_bytes=1,200,540,496`。
- 历史 valid 证据：`src2_dst3_user2` 的 `valid_raw_recall@500=0.034512`、`candidate_user_rate=0.963519`。

当前正式保留的 artifact 是：

- source manifest：`outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/src3_dst3_user2_keep_hot_cosine_v1/source_index_manifest.json`
- 口径：`src>=3,dst>=3,user_after_item_filter>=2,keep_hot,cosine`
- row/edge count：`16,454,229`
- shard count：`64`

本轮已按用户要求清理非最佳实践残留：旧 strict source、旧 src2/dst3 矩阵、旧 route smoke、远程非最佳 grid rows 和旧 weak_denoised source 均记录在 `dic/recall_methods/itemcf_weak/CLEANUP_RECORD_2026_06_07.md`。当前 readiness 只依赖 `src3_dst3_user2_keep_hot_cosine_v1` source adapter，不再依赖已删除的旧矩阵 artifact。

### valid 一个月冷 item 剪枝效果验证

按用户要求，使用 recent-2y 数据集中间的 valid 一个月作为 post-hoc 效果验证集：`data/processed/amazon_2023_recall_recent_2y_1m_3m/canonical_interactions.valid.jsonl`。该 valid label 只用于评价，不参与矩阵构建、边过滤规则生成、score 计算、candidate generation 或 final promotion。本次 `MATRIX_READY` 的依据是 train-only filter-before-build 矩阵 artifact 构建完成；valid 结果只作为后验方案对比证据。

诊断报告：`outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/cold_item_pruning_valid_eval_20260606/evaluation_report.json`

评估范围：`valid_label_rows=154,867`、`valid_users_with_labels=127,171`、`evaluated_users_with_train_sequence=24,862`、`eval_seed_item_count=36,841`。

| variant | src min user | dst min user | cut hot dst | valid Recall@500 | valid HitUser@500 | candidate user rate | candidate p50/p90/max | hot share | 结论 |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | --- |
| `baseline_keep_hot_src2_dst2_current_top200` | 2 | 2 | false | `0.030251` | `0.037246` | `0.951693` | `200/432/500` | `0.892315` | 当前基线，覆盖最高 |
| `keep_hot_src2_dst3` | 2 | 3 | false | `0.030373` | `0.037246` | `0.951573` | `172/392/500` | `1.0` | 当前 best，轻砍冷 dst 后 Recall 微升、候选量下降 |
| `keep_hot_src2_dst5` | 2 | 5 | false | `0.030099` | `0.036843` | `0.951130` | `142/355/500` | `1.0` | Top50/100 有提升，但 Recall@500 略降 |
| `keep_hot_src2_dst10` | 2 | 10 | false | `0.029034` | `0.035355` | `0.949843` | `102/287/500` | `1.0` | 冷剪过强，覆盖和 Recall 下降 |
| `keep_hot_src3_dst3` | 3 | 3 | false | `0.030251` | `0.037205` | `0.943247` | `172/391/500` | `1.0` | src 也剪冷会损失覆盖，收益不明显 |
| `keep_hot_src5_dst5` | 5 | 5 | false | `0.029947` | `0.036642` | `0.922854` | `142/354/500` | `1.0` | 更强剪枝导致覆盖下降 |
| `keep_hot_src10_dst10` | 10 | 10 | false | `0.028243` | `0.034470` | `0.874749` | `101/281/500` | `1.0` | 过窄，不适合作为当前主路 |
| `cut_hot_dst_control_src2_dst2` | 2 | 2 | true | `0.000517` | `0.000684` | `0.841405` | `8/65/500` | `0.0` | 砍 hot dst 直接摧毁 ItemCF 效果 |

结论：当前治理里的 `hotness_bucket=hot` 很宽，不能理解成“少数极热门商品”。对 `itemcf_weak` 传统矩阵来说，硬砍 hot dst 会把有效共现桥接一起砍掉，valid Recall@500 从 `0.030251` 掉到 `0.000517`。更合理的方向是 **保留热门/中高频 item，只轻度剪掉极冷 dst**；当前 valid 一个月诊断里，`src>=2, dst>=3, keep hot` 是最优折中。该结论仍为 diagnostic-only，不能仅凭 valid 单月结果打开 candidate generation / promotion。

### item/user/dst 联合剪枝 quick 对比

用户进一步要求验证“先筛 item，再筛 user，同时观察 dst 是否需要单独加严”。该实验在远程 `server:/home/luo/RS_agent_remote` 上运行，仍只使用 train-only 序列和 item quality profile 构建共现，valid 一个月只做 post-hoc evaluation，不写正式 candidates，不打开 promotion。

诊断报告：`outputs/recall/pool500_method_diagnostics/recent_2y/itemcf_weak/quick_dst_user_pruning_valid_eval_20260606/evaluation_report.json`

| variant | item src | item dst | user after item filter | valid Recall@500 | candidate user rate | 结论 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `src2_dst3_user2` | 2 | 3 | 2 | `0.034512` | `0.963519` | 当前 best |
| `src2_dst2_user2` | 2 | 2 | 2 | `0.033873` | `0.963840` | 放宽 dst 后 Recall 下降 |
| `src2_dst1_user2` | 2 | 1 | 2 | `0.033082` | `0.964564` | 基本取消 dst 后更差 |
| `src2_dst3_user3` | 2 | 3 | 3 | `0.030769` | `0.950084` | user 加严后覆盖和 Recall 下降 |
| `src2_dst2_user3` | 2 | 2 | 3 | `0.030221` | `0.950125` | 弱于 current |
| `src2_dst1_user3` | 2 | 1 | 3 | `0.029399` | `0.951814` | 最差 |

结论：`dst` 仍有候选质量门槛作用，不能取消；user 筛选也不应从筛后 `>=2` 加严到 `>=3`，否则会损失覆盖和 Recall。当前正式 filter-before-build 口径固定为 `src>=2,dst>=3,user_after_item_filter>=2,keep_hot`。

## 下一步

- 以 `src3_dst3_user2_keep_hot_cosine_v1` sharded source adapter 作为当前 ItemCF weak 默认 source manifest。
- 后续如需进一步晋升，先补完整 route replay，并计算与 READY sources 的 overlap、marginal Recall 和预算占用。
- 在 route gate 全部通过前，不打开 candidate generation / ranking replacement / pool1000 / final promotion。
- RPA-lite、RPA-index、AugCF-lite 相关结论只保留为历史诊断，不再作为当前优化主线。

## 历史说明

旧 `outputs/recall/pool500_sidecar_fix/...`、旧 full-data clean manifest 和 2026-05-25 三档旧体系记录仅保留为历史参考，不再作为 current recent-2y 结论、latest artifact 或晋升依据。

## 后续可回看论文参考

- **AugCF / 生成增强方向**：Wang et al., *Enhancing Collaborative Filtering with Generative Augmentation*, KDD 2019. 该方向对应 weak 侧历史 AugCF-lite 诊断，核心思想是为 inactive/sparse users 做生成式交互增强，而不是直接替换 item-item similarity 公式。
- **RPA / RPA-index 递归协同过滤方向**：Zhang and Pu, *A Recursive Prediction Algorithm for Collaborative Filtering Recommender Systems*, RecSys 2007. 该方向对应 weak 侧历史 RPA-lite、paper-binary Top500、RPA-index / index-backed replay 诊断；核心思想是通过相似用户、邻域递归预测和 path-support 证据补全 sparse/medium 用户的 missing preference。
