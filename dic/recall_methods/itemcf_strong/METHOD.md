# itemcf_strong

## 方法定位
强标签 ItemCF 召回，基于更可信的 item 共现边提供高精度补充候选。它属于 `custom_dataset_policy`，是重资源方法，当前只做诊断，不可替换 ranking。

## 当前 readiness
- 状态：`DIAGNOSTIC_ONLY`
- index：`INDEX_READY`
- 输出：`DIAGNOSTIC_OUTPUT_READY`
- 仅维持诊断态，不做状态升级或下游链路替换。

## 治理契约
- 只适用 `heavy_cf_eligible`。
- 必须 batch 化、带 guard、带 memory limit。
- builder 覆盖：`source_index_manifest` 以 `train_only` 的 source-positive 用户建边；本轮 `users_scanned=5992`、`users_with_source_items=5000`、`users_used=2133`，`target_user_limit_semantics=source_positive_builder_sequences_limit`。
- profiled 覆盖：`null` / `unprofiled`，没有单独的用户质量 profile 过滤；当前 artifact 是 legacy unfiltered sidecar coverage audit，不把高质量用户索引误当 consumer universe。
- consumer 覆盖：新增独立 `consumer_user_manifest.json` 和 `coverage_audit.json`；本轮 target500 train-only consumer 中 `consumer_users_with_edge_seed_hit=239`、`edge_item_out_of_universe_count=0`。

## 适用用户
- 有强正反馈或高置信行为序列。
- seed item 能命中 strong item-item 边。
- 适合作为高精度补充来源，不适合单独承担覆盖。

## 输入 artifact
- source signature：`data/processed/amazon_2023_recall_clean_full/user_sequences.train.jsonl`，`row_count=18103384`，`sha256=d47c9a3476f35f0c8bd88947b58f8a3f0ef83383f587d8d0e3102b6dbf1baf07`
- clean manifest：`data/processed/amazon_2023_recall_clean_full/manifest.json`

## 输出 artifact
- readiness contract：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/readiness_contract.json`
- source index manifest：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/source_index_manifest.json`
- resource audit：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/resource_audit.json`
- no-holdout audit：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/no_holdout_audit.json`
- per-source candidate manifest：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/per_source_candidate_manifest.json`
- weak/strong comparison：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/weak_strong_comparison.json`
- edge sidecar：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/itemcf_strong_edges.jsonl`
- consumer user manifest：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/consumer_user_manifest.json`
- coverage audit：`outputs/recall/pool500_sidecar_fix/itemcf_strong_target500_guarded/coverage_audit.json`
- custom dataset manifest：`configs/recall/full_data_pool500/itemcf_strong_custom_dataset_manifest.json`
- recall-only target500 per-source：`outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/sources/itemcf_strong/manifest.json`

## 资源画像
最近一次 target500 guarded diagnostic：
- `edge_count` / `rows_written`：68432
- `unique_pair_count`：34341
- `unique_item_count`：9939
- `candidate_user_count`：5000
- `users_scanned`：5992
- `users_used`：2133
- `consumer_users_with_edge_seed_hit`：239 / 500
- `edge_item_out_of_universe_count`：0
- `peak_rss_mb`：35.695
- `underfilled_user_coverage`：1.0

## 当前问题
已经从 500 个 source-positive 用户扩大到 5000 个 train-only source-positive 用户建边，并补齐 consumer coverage audit 与 registry custom dataset manifest；但 `status` 仍是 `DIAGNOSTIC_ONLY`，`custom_dataset_policy_satisfied=false`，仍只保留诊断用途。strong 更适合作为高置信补充源，不适合单独承担补量。

## 下一步
与 weak ItemCF 一起比较覆盖和边际贡献：本轮 guarded sidecar 中 strong `rows_written=68432`、target500 consumer seed-hit 用户 239；weak `rows_written=74662`、target500 consumer seed-hit 用户 250，weak 更适合补量，strong 更适合作为高置信补充。若治理上必须满足高质量 custom dataset policy，需要另跑 quality-builder sidecar，并继续用独立 consumer_user_manifest / coverage_audit 校验 pool500 consumer 覆盖。

## 专项优化 Agent 调用说明
后续单独调用 Agent 优化本方法时，目标应是围绕 `heavy_cf_eligible` 用户扩展 strong ItemCF 的高置信 item-pair 数据集，重点比较 strong/weak 的精度、覆盖、重复率和资源成本。Agent 必须保留 batch/guard/memory limit，并输出 source index manifest、resource audit 和诊断候选 manifest；不得因为 strong 边更可信就跳过诊断门槛或直接宣称可晋升状态。

## P2 method_dataset 数据清洗与筛选方案

- 数据来源：只读取 `governance_train_only` 的用户质量、item 质量、train item frequency 与 `user_sequences.train.jsonl`。
- 筛选单位：`user_positive_sequence_to_item_pairs`。先保留高质量用户序列，再构造高置信 item-pair。
- 适用桶：用户桶 `collaborative_rich`；item 侧使用 `cf_ready`。
- 清洗规则：过滤弱行为用户、非 `cf_ready` item、过热 item 的过量边；优先短窗口/强支持 pair，不让单次偶然共现进入 strong 主路。
- 规模参数：`max_output_users=200000`、`max_items_per_user=50`、`max_item_user_freq=3000`、`min_pair_support=2`。

## P2 method_dataset 特征与打分口径

- builder 新增 `weighted_cooc`、`supporting_user_count`、`score_policy`、`itemcf_score_formula`、`active_user_penalty_policy`。
- `itemcf_score = round(weighted_cooc / sqrt(src_user_count * dst_user_count), 6)`。
- `active_user_penalty_policy` 是效果导向抑制超活跃用户和长序列随机共现，不是流程优化。
- 这里记录的是 `method_dataset` / diagnostic evidence，不是 source/candidate/ranking/promotion 替换口径。

### 规模档位

| 档位 | max_output_users | max_items_per_user | max_item_user_freq | min_pair_support |
| --- | ---: | ---: | ---: | ---: |
| smoke | 1000 | 50 | 3000 | 2 |
| diagnostic | 80000 | 50 | 3000 | 2 |
| local_formal | 200000 | 50 | 3000 | 2 |

- 泄漏边界：不读取 valid/test/holdout/LOPO/eval_label/oracle，不用诊断命中结果反向筛边，不声明 READY、promotion、ranking input replacement 或 pool1000。
- 维护检查：strong 必须比 weak 更严格；修改后同步检查 registry、builder manifest、测试中的 `itemcf_strong_edges_v1`。

## P2 smoke / diagnostic / formal method_dataset 构建验证（2026-05-25）

- smoke 构建命令：`.venv/Scripts/python.exe -m rs_lab.experiments.recall.build_pool500_method_dataset --governance-manifest outputs/recall/data_governance/train_only_v1_smoke/manifest.json --source-method itemcf_strong --scale-tier smoke --output-root outputs/recall/pool500_method_datasets/itemcf_weighted_smoke_v1 --overwrite`
- smoke 输出目录：`outputs/recall/pool500_method_datasets/itemcf_weighted_smoke_v1/itemcf_strong/`；`status=PASS`，但 `row_count=0`、`unique_pair_count=0`，只能证明链路和 audit 边界。
- strict diagnostic 输出目录：`outputs/recall/pool500_method_datasets/itemcf_weighted_diagnostic_v1/itemcf_strong/`；`row_count=0`、`unique_pair_count=0`、`edge_count=0`、`user_count=28`、`pair_below_min_support=41`，audit PASS。
- strict local_formal 输出目录：`outputs/recall/pool500_method_datasets/itemcf_weighted_formal_v1/itemcf_strong/`；`row_count=208`、`unique_pair_count=104`、`edge_count=208`、`user_count=15511`、`item_count=71`、`weighted_cooc_sum_after_topk=212.532068`，audit PASS。
- strong 仍坚持高置信口径：`collaborative_rich` 用户、`cf_ready + non-over_hot` item、`max_item_user_freq=3000`、`min_pair_support=2`。这导致 formal 边数极少，但它的定位是高置信补充，不承担 weak coverage 的广覆盖职责。
- 与 weak coverage formal 的关系：coverage formal 只对 `itemcf_weak` 放宽用户桶和 item 桶，用于解决弱召回补量；strong 不跟随放宽，否则会破坏 strong 的 high-confidence 语义。
- 特征摘要：`weighted_cooc`、`supporting_user_count`、`score_policy=weighted_cooc_cosine_normalized_v1`、`active_user_penalty_policy=round(1 / log1p(filtered_sequence_len), 6)` 已进入 builder；`itemcf_score = round(weighted_cooc / sqrt(src_user_count * dst_user_count), 6)`；排序策略为 `source_method + src_item_id` 内按 `itemcf_score desc, cooc_cnt desc, dst_item_id asc`。
- 边界说明：这些输出仍是 `method_dataset` / diagnostic evidence，不是 source index、candidate、ranking input、promotion 或 final pool500 ready；audit validator 使用 method manifest 的 `upstream_governance_manifest_path`，不硬编码 default governance。

## relaxed seed-src v3 诊断口径（2026-05-26）

strict strong formal 只有 208 条方向边，初版 relaxed/support=1 虽增加到 56,518 条边，但前 100 用户 strong seed 与 source src 仍 0 命中。定位后发现 strong 查询 seed 大多是 `embedding_ready` 且 178/179 为 hot item；如果把 hot item 完全排除，strong seed 无法作为查询锚点。

v3 口径把 strong 的 seed 侧和 candidate 侧拆开：

- 用户桶：`sequence_sufficient`、`collaborative_rich`，不放开到 `medium_behavior`，仍比 weak coverage 严格。
- 构边方向：`recent_strong_positive_item_sequence -> recent_positive_item_sequence` 的有向边，只用 strong seed 发边。
- src 侧：允许 `cf_ready` / `embedding_ready`，且允许 hot，解决强交互热门 seed 无法查询的问题。
- dst 侧：允许 `cf_ready` / `embedding_ready`，但排除 hot，避免把热门 item 作为候选输出放大。
- 参数：`max_output_users=160000`、`max_items_per_user=60`、`max_item_user_freq=8000`、`min_pair_support=1`、`top_k_per_seed=150`。
- 边界：`train_only=true`、`DIAGNOSTIC_ONLY`、`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`、`pool1000_allowed=false`。

验证产物：

- method_dataset：`outputs/recall/pool500_method_datasets/itemcf_strong_relaxed_seedsrc_smoke_v3/itemcf_strong/method_dataset_manifest.json`，`row_count=1,536,320`、`directed_edge_count_after_topk=1,536,320`。
- source index：`outputs/recall/pool500_method_sources/itemcf_strong_relaxed_seedsrc_v3_from_method_dataset/itemcf_strong/smoke_sharded/source_index_manifest.json`，`shard_count=128`、`row_count=1,536,320`、`diagnostic_only=true`。
- 100 用户主路 smoke：`itemcf_strong.row_count=1,557`、`user_coverage_count=68/100`、`marginal_candidate_share=0.033384`。
- 500 用户受控验证：`itemcf_strong.row_count=8,198`、`user_coverage_count=369/500`、`marginal_candidate_share=0.03469`。

结论：v3 已把 strong 从 0 贡献恢复为可用的高置信补充源，但它仍是 diagnostic source，不得据此声明 READY、替换 ranking input 或进入 pool1000。

## relaxed seed-src v3 三档独立重建与 formal 分片主路验证（2026-05-26）

三档数据集不是从 formal 边表抽样得到，而是分别从 train-only 原始序列和 governance profile 独立重建；每档都会重新计算 pair support、`weighted_cooc`、`itemcf_score` 和 per-seed topK。这样避免“抽掉一个用户导致所有共现边统计失效”的问题。

| 档位 | 输出目录 | max_output_users | row_count | user_count | item_count |
| --- | --- | ---: | ---: | ---: | ---: |
| smoke | `outputs/recall/pool500_method_datasets/itemcf_strong_relaxed_seedsrc_smoke_v3_real/itemcf_strong/` | 5,000 | 47,615 | 5,000 | 36,068 |
| diagnostic | `outputs/recall/pool500_method_datasets/itemcf_strong_relaxed_seedsrc_diagnostic_v3/itemcf_strong/` | 80,000 | 784,463 | 80,000 | 317,624 |
| local_formal | `outputs/recall/pool500_method_datasets/itemcf_strong_relaxed_seedsrc_local_formal_v3/itemcf_strong/` | 160,000 | 1,536,320 | 160,000 | 494,449 |

formal source index：`outputs/recall/pool500_method_sources/itemcf_strong_relaxed_seedsrc_v3_from_method_dataset/itemcf_strong/formal_sharded/source_index_manifest.json`，`row_count=1,536,320`、`shard_count=128`、`sharded=true`、`diagnostic_only=true`；已作为 pool500 recall-only 主路默认 `itemcf_strong` source manifest。

formal 分片 source 主路验证：

- 100 用户 smoke：`outputs/recall/full_data_pool500_recall_only/itemcf_strong_relaxed_seedsrc_formal_sharded_smoke100/`，`itemcf_strong.row_count=1,557`、`user_coverage_count=68/100`、`marginal_candidate_share=0.033384`、`final_resource_audit.status=PASS`。
- 500 用户受控验证：`outputs/recall/full_data_pool500_recall_only/itemcf_strong_relaxed_seedsrc_formal_sharded_smoke500/`，`itemcf_strong.row_count=8,198`、`user_coverage_count=369/500`、`marginal_candidate_share=0.03469`、`final_resource_audit.status=PASS`。

边界保持：`train_only=true`、`readiness_status=DIAGNOSTIC_ONLY`、`promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。formal 分片 source 只证明 strong 可作为高置信补充源进入诊断主路，不声明 READY 或替换排序输入。

默认主路接入验证：`rs_lab/experiments/recall/run_full_data_pool500_recall_only.py` 的默认 `itemcf_strong` manifest 已切到上述 `formal_sharded/source_index_manifest.json`。不传 `--source-manifest itemcf_strong=...` 的 100 用户默认主路 smoke 输出 `outputs/recall/full_data_pool500_recall_only/itemcf_strong_formal_default_route_smoke100/`，其中 `itemcf_strong.row_count=941`、`user_coverage_count=68/100`、`marginal_candidate_share=0.019991`、`final_resource_audit.status=PASS`；`per_source_output_manifests.json` 记录的 `itemcf_strong.source_index_manifest_path` 指向 formal sharded source，且 `source_status=DIAGNOSTIC_ONLY`、`promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。
