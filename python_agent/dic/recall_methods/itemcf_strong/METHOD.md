# itemcf_strong

## 方法定位

`itemcf_strong` 是 pool500 recent-2y 下的高置信 ItemCF 补充召回源。它基于 train-only 用户强正反馈序列构造 item-item 共现边，适合提供可解释的邻居候选；这次 relaxed 版本放宽了种子侧覆盖，但仍然只允许 train-only 构建、eval-only 评估，不允许把 valid/test label 回流到候选生成。

当前结论：**升级为 `READY_CANDIDATE` / `SUPPLEMENTAL_READY_CANDIDATE` 候选**。相较 strict 版本，这个 relaxed supplemental 版本恢复了足够的 source 覆盖和候选贡献，但仍然不把自己描述成主路 ready，也不替代 `itemcf_weak`、`swing_recall` 或 ranking input。

## SciOMC 文献与最佳实践依据

详见 `dic/recall_methods/itemcf_strong/RECENT2Y_SCIOMC_RESEARCH.md`。本轮调研纳入：

- Sarwar et al., *Item-Based Collaborative Filtering Recommendation Algorithms*, WWW 2001：离线构建 item-item similarity matrix，并评估覆盖、效率和可扩展性。
- Linden / Smith / York, *Amazon.com Recommendations: Item-to-Item Collaborative Filtering*, IEEE Internet Computing 2003：大规模线上推荐适合离线 item-item 表 + 在线按历史 seed 查询邻居。
- Hu / Koren / Volinsky, *Collaborative Filtering for Implicit Feedback Datasets*, ICDM 2008：implicit feedback 中未观测不等于负样本，行为强度和训练/评估分离很重要。
- Rendle et al., *BPR*, UAI 2009 / arXiv 2012：implicit 推荐的评估目标与训练信号不能混淆，eval label 不得反向参与候选生成。

## 当前 readiness

- `source_status`: `READY_CANDIDATE`
- `candidate_generation_allowed`: `true`（仅 route-gate candidate source 范围）
- `ranking_input_replacement_allowed`: `false`
- `promotion_allowed`: `false`
- `pool1000_allowed`: `false`
- `final_pool500_ready_claimed`: `false`

## recent-2y train-only / eval-only 边界

正式输入只允许来自：

- `data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json`
- `user_quality_profile.jsonl`
- `item_quality_profile.jsonl`
- `item_frequency_train.jsonl`
- `user_sequences.train.jsonl`

禁止将以下内容用于 method dataset、source artifact 或候选生成：holdout、valid、test、LOPO、oracle、eval label、clean_10000、pool1000、旧 full-data-derived method dataset。valid/test 只允许在评估脚本中作为 evaluation-only label 使用。

## 本轮 smoke/formal method dataset

### smoke

- 路径：`outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong_relaxed_supplemental_v1/smoke/itemcf_strong/method_dataset_manifest.json`
- 用途：program/schema validation only
- `status=PASS`
- `row_count=30466`
- `user_count=5000`
- `item_count=24576`
- `forbidden_scope_audit.status=PASS`

### formal

- 路径：`outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong_relaxed_supplemental_v1/formal/itemcf_strong/method_dataset_manifest.json`
- 用途：official method logic dataset under recent-2y train-only governance
- `status=PASS`
- `row_count=514216`
- `unique_pair_count=514216`
- `edge_count=514216`
- `user_count=82838`
- `item_count=215713`
- `weighted_cooc_sum_after_topk=237134.151762`
- `forbidden_scope_audit.status=PASS`

relaxed formal 口径：`sequence_sufficient_or_collaborative_rich` 用户、src 侧允许 hot seed、dst 侧限制 non-hot candidate、`min_pair_support=1`、active-user penalty、`weighted_cooc_cosine_normalized_v1`。这个口径比 strict 版更宽，恢复了覆盖，但仍然维持高置信 ItemCF 的方向性和 train-only 约束。

## source artifact

- source manifest：`outputs/recall/pool500_method_sources_newdata/itemcf_strong_relaxed_supplemental_v1/itemcf_strong/formal_relaxed_from_recent2y/source_index_manifest.json`
- `status=PASS`
- adapter manifest 内部仍保持 `source_status=DIAGNOSTIC_ONLY` / `diagnostic_only=true`，作为防误晋升边界
- config / registry 层将其标记为 `READY_CANDIDATE` / `SUPPLEMENTAL_READY_CANDIDATE`，仅允许进入 route-gate candidate source 验证
- `row_count=514216`
- `edge_count=514216`
- `train_only=true`
- `candidate_generation_allowed=true`（config/registry route-gate 范围）
- `ranking_input_replacement_allowed=false`
- `promotion_allowed=false`

## 验证结果

### method dataset audit

命令：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.validate_pool500_method_dataset_audit_evidence \
  --governance-manifest data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json \
  --method-dataset outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong_relaxed_supplemental_v1/smoke/itemcf_strong/method_dataset_manifest.json \
  --method-dataset outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong_relaxed_supplemental_v1/formal/itemcf_strong/method_dataset_manifest.json \
  --output outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong_relaxed_supplemental_v1/audit_evidence.json
```

结果：`status=PASS`，`blocker_count=0`。

### 单方法 source-level sanity eval

- 报告：`outputs/recall/pool500_method_sources_newdata/itemcf_strong_relaxed_supplemental_v1/itemcf_strong/formal_relaxed_from_recent2y_eval/single_source_eval_10000.json`
- target：前 10000 个拥有 recent-2y valid/test 正样本的 train 用户
- 候选生成输入：train user sequences + relaxed source edges
- evaluation label：recent-2y valid/test，仅 evaluation-only
- `source_edge_count=514216`
- `seed_hit_user_count=6141`
- `user_coverage_count=6128`
- `candidate_row_count=188494`
- `Recall@500=0.000151`
- `HitRate@500=0.0002`
- `candidate_hot_share=0`
- `strong_unique_share_vs_weak=0.999867`

### 购买 / 强正反馈导向远程 eval

- 报告：`outputs/recall/pool500_method_sources_newdata/itemcf_strong_relaxed_supplemental_v1/itemcf_strong/formal_relaxed_from_recent2y_eval/purchase_label_eval_remote_full.json`
- 运行位置：`server:/home/luo/RS_agent_remote`，使用远程 `.venv/bin/python`
- 候选生成输入：train `user_sequences.train.jsonl` + relaxed source edges；valid/test 只作为 evaluation-only label
- target：拥有 purchase/strong/all-positive label 且存在 train sequence 的用户并集 `53653`
- source：`edge_count=514216`、`src_item_count=159923`、`dst_item_count=72536`
- `purchase_positive`（`verified_purchase=true and label_binary>0`）：`target_user_count=40043`、`seed_hit_rate=0.666409`、`user_coverage_rate=0.665410`、`label_in_dst_universe_ratio=0.016898`、`Recall@500=0.000211`、`HitRate@500=0.000275`、`in_universe_Recall@500=0.012514`
- `strong_positive`（`label_strong>0`）：与 `purchase_positive` 在当前 label schema 下相同，`Recall@500=0.000211`、`HitRate@500=0.000275`、`in_universe_Recall@500=0.012514`
- `all_positive`（`label_binary>0`）：`target_user_count=42394`、`user_coverage_rate=0.659905`、`Recall@500=0.000194`、`HitRate@500=0.000259`、`in_universe_Recall@500=0.010628`
- `candidate_hot_share=0.0`

结论：按“strong 方法应看购买/强正反馈目标”的口径复测后，覆盖仍能维持在约 66%，但 raw `Recall@500` 仍很低；主要受目标商品落在当前 non-hot dst universe 的比例很低影响（purchase/strong 的 `label_in_dst_universe_ratio=0.016898`）。因此该方法仍可作为高置信、长尾、低重复的 supplemental candidate source 保留，但不能单凭该报告宣称主路效果好，下一步必须在 route-level 验证它对购买目标的边际增益。

### AugCF-lite 远程实验（KDD'19 AugCF 思路的轻量复刻）

AugCF 原论文是 Conditional GAN / 生成式交互增强，并不是传统 `sim(item_i,item_j)` 显式公式。本阶段没有直接复刻完整 GAN，而是新增独立实验源 `itemcf_strong_augcf_lite_v1`：用 train-only 强正反馈共现、类目/主类目/store、train-only 强正/正反馈频次、item quality/hotness 等特征构造 `augcf_lite_score`，再输出兼容 ItemCF source adapter 的 `src_item_id -> dst_item_id` observed/pseudo edge rows。valid/test 仍只用于 evaluation-only。

- 实现：`rs_lab/experiments/recall/pool500/methods/itemcf_strong/augcf_lite_builder.py`、`scripts/experiments/recall/pool500/build_itemcf_strong_augcf_lite_method_dataset.py`
- source adapter 修正：`rs_lab/experiments/recall/pool500/method_dataset_to_itemcf_source.py` 对 `train_only=false` fail-closed，并从 manifest lineage 推导 `RECENT_2Y_DERIVED_INDEX`，避免 recent-2y artifact 被误写为 `FULL_DERIVED_INDEX`。
- 远程运行：`server:/home/luo/RS_agent_remote`，重 artifact 写入 `/tmp/rs_agent_spill/...`，本地只拉回 manifest/audit/eval JSON。
- 本地验证：`.venv/Scripts/python.exe -m py_compile ...` 通过；100-user smoke build/source/eval 链路通过；manifest/leakage/index_scope assertions 通过。

结果对比：

| variant | rows | observed / pseudo | purchase Recall@500 | HitRate@500 | in-universe Recall@500 | label_in_dst_universe | user_coverage | candidate_hot_share |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| relaxed baseline(non-hot dst) | 514216 | 514216 / 0 | 0.000211 | 0.000275 | 0.012514 | 0.016898 | 0.665410 | 0.0 |
| AugCF-lite formal_50k hot-dst | 6174682 | 5010969 / 1163713 | 0.025721 | 0.031416 | 0.031212 | 0.824084 | 0.598706 | 0.960442 |
| AugCF-lite formal_50k no-hot-dst | 2308758 | 311844 / 1996914 | 0.000192 | 0.000250 | 0.009921 | 0.019378 | 0.585471 | 0.0 |

证据路径：

- hot-dst method manifest：`outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong_augcf_lite/v1/formal_50k/method_dataset_manifest.json`
- hot-dst eval：`outputs/recall/pool500_method_sources_newdata/itemcf_strong_augcf_lite_v1/itemcf_strong/formal_50k_augcf_lite_recent2y_eval/purchase_label_eval_remote_full.json`
- no-hot method manifest：`outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong_augcf_lite/v1/formal_50k_nohot/method_dataset_manifest.json`
- no-hot eval：`outputs/recall/pool500_method_sources_newdata/itemcf_strong_augcf_lite_v1/itemcf_strong/formal_50k_nohot_augcf_lite_recent2y_eval/purchase_label_eval_remote_full.json`

结论：AugCF-lite 证明“扩大 dst universe + 生成式/学习式补边”确实能显著提高购买目标 raw recall，但收益主要来自允许 hot dst 后目标覆盖率从 `0.016898` 提升到 `0.824084`；一旦恢复 no-hot 控制，Recall@500 反而略低于 relaxed baseline。因此它目前只能作为 **experimental / diagnostic** 证据，不能替代现有 supplemental baseline，也不能直接并入主路。下一步如果继续这条路，应做 hotness 分桶预算、与 popular/category 的 overlap/marginal gain gate，以及 pseudo-only / observed-only 消融，避免把热门商品覆盖误判成 `itemcf_strong` 本身的可解释相似度提升。

### AugCF-controlled v2：hotness 预算对照

在确认 unrestricted hot-dst 增益主要来自热门商品覆盖后，新增 controlled v2 对照：在 source 边构建阶段启用 `--controlled-hot-budget` 和 `--max-hot-share-per-src`，对每个 `src_item` 的 hot dst 边数做上限约束；controlled 模式下不再用超预算 hot dst 回填空位。该实验仍然只读取 train-only 输入，valid/test 只用于 purchase/strong-positive evaluation-only。

结果对比（remote formal_50k，`candidate_limit=500`）：

| variant | rows | observed / pseudo | selected hot edges | purchase Recall@500 | HitRate@500 | in-universe Recall@500 | label_in_dst_universe | user_coverage | candidate_hot_share |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| controlled q10 | 1096254 | 1032205 / 64049 | 750000 | 0.005037 | 0.006418 | 0.006993 | 0.720237 | 0.598706 | 0.440016 |
| controlled q20 | 1845069 | 1733341 / 111728 | 1499996 | 0.010688 | 0.013510 | 0.013633 | 0.784021 | 0.598706 | 0.618814 |
| controlled q30 | 2592359 | 2374633 / 217726 | 2248768 | 0.015129 | 0.018755 | 0.018825 | 0.803687 | 0.598706 | 0.717320 |
| controlled q50 | 3995662 | 3454114 / 541548 | 3656705 | 0.019608 | 0.024124 | 0.023948 | 0.818797 | 0.598706 | 0.823463 |

证据路径：

- q10 manifest/eval：`outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong_augcf_controlled_v2/q10/formal_50k/method_dataset_manifest.json`、`outputs/recall/pool500_method_sources_newdata/itemcf_strong_augcf_controlled_v2/itemcf_strong/q10_formal_50k_recent2y_eval/purchase_label_eval_remote_full.json`
- q20 manifest/eval：`outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong_augcf_controlled_v2/q20/formal_50k/method_dataset_manifest.json`、`outputs/recall/pool500_method_sources_newdata/itemcf_strong_augcf_controlled_v2/itemcf_strong/q20_formal_50k_recent2y_eval/purchase_label_eval_remote_full.json`
- q30 manifest/eval：`outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong_augcf_controlled_v2/q30/formal_50k/method_dataset_manifest.json`、`outputs/recall/pool500_method_sources_newdata/itemcf_strong_augcf_controlled_v2/itemcf_strong/q30_formal_50k_recent2y_eval/purchase_label_eval_remote_full.json`
- q50 manifest/eval：`outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong_augcf_controlled_v2/q50/formal_50k/method_dataset_manifest.json`、`outputs/recall/pool500_method_sources_newdata/itemcf_strong_augcf_controlled_v2/itemcf_strong/q50_formal_50k_recent2y_eval/purchase_label_eval_remote_full.json`

结论：controlled v2 证明 AugCF-lite 路线可以在 purchase Recall 与热门候选占比之间形成连续 tradeoff：q10 到 q50 的 `Recall@500` 从 `0.005037` 增至 `0.019608`，`candidate_hot_share` 从 `0.440016` 增至 `0.823463`。但 per-src hot quota 不等同于最终 user-level candidate hot share，因为候选生成会聚合多个 seed，热门 dst 在多条边中重复出现后仍会被放大。当前更合理的下一步是把 q20/q30 作为 route-gate 诊断候选，继续测 popular/category overlap、边际 Recall、source share cap 和分桶预算，而不是直接替换 relaxed baseline 或自动并入主路。

### Route-level AugCF 预算门控实现

为避免 controlled v2 只在 source 边阶段控制 per-src hot quota、但最终用户候选池仍被多 seed 聚合放大，本轮在 pool500 recall route 增加诊断级 user-level hot/pseudo cap：

- 实现：`rs_lab/experiments/recall/run_full_data_pool500_recall_only.py`
- 触发条件：仅当 `itemcf_strong` source manifest 同时满足 `diagnostic_only=true`，且 `source_variant` / `diagnostic_policy` 中包含 `augcf_lite` 或 `augcf_controlled`。
- 生效位置：`_enforce_popular_category_cap(...)` 之后、fallback completion 之前，避免 cap 后缺口被误写成方法本身覆盖。
- 预算：读取 `max_final_hot_share_per_user`（缺省 `0.3`）和 `max_pseudo_per_user`（缺省 `100`）。
- 删除优先级：只删除 AugCF diagnostic `itemcf_strong` 候选，优先删 pseudo、hot、单源 `itemcf_strong`、低分候选；不删除 relaxed baseline `itemcf_strong` 或非 AugCF 候选。
- 审计输出：`diagnostic_hot_budget_audit.json`，记录 before/after hot share、pseudo count、`itemcf_strong` row count、removed hot/pseudo count、cap 后 underfill，并在 route manifest 的 required artifacts 中挂载。
- offline route eval 入口：`rs_lab/experiments/recall/run_pool500_offline_eval_baseline.py` 新增通用 `--source-manifest itemcf_strong=/path/to/source_index_manifest.json`，用于 q20/q30/no-hot 在固定 eval users 上复跑 route-level evidence。

本地验证：`.venv/Scripts/python.exe -m py_compile` 覆盖两个 route 脚本和相关测试；`pytest tests/test_full_data_pool500_recall_only.py tests/test_pool500_offline_eval_baseline.py -q` 结果为 `26 passed`。该实现只补齐 route-gate 能力，不改变 relaxed baseline latest artifact，也不授权 AugCF-lite/controlled 晋升。

### 晋升判断

这个版本不再是 strict diagnostic：它已经是可用的 supplemental candidate source。与此同时，它也还不是 main-route READY，原因不是覆盖不足，而是它仍然需要在 pool500 route 级别上完成边际贡献、source overlap 和编排收口后，才能决定是否进入更高层级的主路结论。

当前判断：`READY_CANDIDATE` / `SUPPLEMENTAL_READY_CANDIDATE`。

## 当前路线更新：记录 strong/RPA-like 结果并舍弃增强方向

用户已决定舍弃当前 `strongRPA`/strong 侧 RPA-like、AugCF-lite/controlled 等生成增强或递归增强方向，后续回到传统 ItemCF。当前 strong 侧结果保留如下，作为历史消融与路线取舍证据：

- relaxed strong baseline（non-hot dst，train-only strong seed → positive dst）：purchase/strong-positive `Recall@500=0.000211`、`HitRate@500=0.000275`、`in_universe_Recall@500=0.012514`、`user_coverage_rate=0.665410`、`label_in_dst_universe_ratio=0.016898`、`candidate_hot_share=0.0`。结论是覆盖尚可，但由于 dst universe 对 purchase/strong labels 覆盖很低，raw recall 很弱。
- AugCF-lite formal_50k hot-dst：purchase `Recall@500=0.025721`、`HitRate@500=0.031416`、`in_universe_Recall@500=0.031212`，但 `candidate_hot_share=0.960442`、`label_in_dst_universe_ratio=0.824084`。收益主要来自 hot dst universe 扩张，不应归因于纯 ItemCF 相似度，也不适合作为传统 ItemCF 晋升依据。
- AugCF-lite formal_50k no-hot-dst：purchase `Recall@500=0.000192`、`HitRate@500=0.000250`、`in_universe_Recall@500=0.009921`，低于 relaxed baseline，说明去掉热门扩张后增强信号没有胜出。
- AugCF-controlled v2 quota 曲线：q10/q20/q30/q50 的 purchase `Recall@500` 分别为 `0.005037` / `0.010688` / `0.015129` / `0.019608`，但 `candidate_hot_share` 同步从 `0.440016` 升到 `0.823463`。这是一条“召回提升—热门偏置上升”的预算曲线，不是可直接沉淀的 strong ItemCF 主路。

结论：strong 侧增强方向仅保留历史记录，不进入继续优化、不打开 candidate generation / ranking input replacement / promotion、不据此更新 registry READY。后续如果保留 strong 信号，只按传统 ItemCF 的 train-only 共现/weighted cooc cosine、src/dst 热度边界和 route-level source budget 重新设计。对应 AugCF-lite / AugCF-controlled 生成产物已清理，清理审计见 `outputs/cleanup_records/itemcf_strong_augcf_cleanup_20260606.json`。

## 下一步

1. 不再继续 strongRPA / AugCF-lite / controlled hot quota 方向；相关产物只作为历史诊断与消融记录。
2. 回到传统 ItemCF：重新梳理 strong seed、positive dst、support、weighted cooc cosine、active-user penalty、src/dst hotness boundary 与 per-seed topK。
3. 继续保持 valid/test 只做 evaluation-only，不进入训练、候选生成、scoring rule selection、variant selection 或 promotion。
4. 等传统 ItemCF 重新跑出同口径 source/eval/overlap 证据后，再决定是否把 strong 作为 supplemental source 纳入 pool500 route 的正式候选编排。

## 后续可回看论文参考

- **AugCF / 生成增强方向**：Wang et al., *Enhancing Collaborative Filtering with Generative Augmentation*, KDD 2019. 该方向对应 strong 侧 `itemcf_strong_augcf_lite_v1` 与 controlled v2 诊断，核心思想是为 inactive/sparse users 做生成式交互增强；本项目实验显示 hot-dst 扩张会显著提高 purchase Recall，但也同步放大热门偏置。
- **strongRPA / RPA-index 递归协同过滤方向**：Zhang and Pu, *A Recursive Prediction Algorithm for Collaborative Filtering Recommender Systems*, RecSys 2007. 该方向对应后续跑过的 strongRPA / paper-binary Top500 / index-backed replay 思路，核心思想是通过相似用户、邻域递归预测和 path-support 证据补全 sparse/medium 用户的 missing preference。
