# swing_recall

## 方法定位

`swing_recall` 是基于 item-item 共现图的行为协同召回 source，用于把用户 train 历史中的 seed item 扩展到相似 item。它更适合有一定近期正反馈历史的用户，不适合作为冷启动主力。

本轮 recent-2y 重建后，`swing_recall` 的状态定义为 **READY_GUARDED**：formal source artifact 已构建并完成 raw source eval，但仍必须受 audited manifest、no-holdout audit、resource audit、source overlap、route gate 和预算护栏约束。单方法 ready 不等于 pool500 主路并入完成，也不授权 ranking input replacement 或 pool1000。

## 当前 readiness

- 方法状态：`READY_GUARDED`
- registry 对外状态：`READY`，但 notes 必须说明 guarded。
- index：`FORMAL_SOURCE_INDEX_READY`
- source artifact：`PASS`
- candidate generation：`false`（等待全局 route gate）
- ranking input replacement：`false`
- pool1000：`false`
- promotion：`false`

## recent-2y 数据与治理边界

- 当前正式数据基础：`data/processed/amazon_2023_recall_recent_2y_1m_3m/manifest.json`
- train-only governance：`data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json`
- SciOMC 预处理根目录：`data/processed/amazon_2023_sciomc_swing_recent2y/`
- 禁止输入：holdout / valid / test / LOPO / oracle / eval label / clean_10000 / pool1000 / 旧 full-data-derived artifact。
- valid/test 只在 evaluation-only 阶段用于 Recall@K / HitRate@K，不参与构图、边过滤或候选生成。

## SciOMC 与论文依据

详见：`dic/recall_methods/swing_recall/RECENT2Y_SCIOMC_RESEARCH.md`。

本轮补充的主要依据包括：

- Sarwar et al. 2001 item-based collaborative filtering：item-item 相似度可离线预计算，并通过 neighborhood pruning 控制成本。
- Amazon item-to-item CF 2003：大规模推荐系统把 item similarity 重计算前置到离线，线上按用户历史 item 扩展候选。
- BPR implicit feedback：训练可见行为与 evaluation label 必须严格隔离。
- NCF / Wide&Deep / SASRec：协同召回、记忆型共现和序列/泛化召回应分工评估。

## smoke/formal 方法数据集

### smoke method dataset

- manifest：`outputs/recall/pool500_method_datasets/recent_2y/swing_recall/smoke/swing_method_dataset/method_dataset_manifest.json`
- 状态：`PASS`
- row_count：`4205`
- user_count：`2000`
- item_count：`4738`
- 用途：程序、schema、路径和 forbidden scope audit 验证。
- 晋升：不允许。

### formal method dataset

- manifest：`outputs/recall/pool500_method_datasets/recent_2y/swing_recall/formal/swing_method_dataset/method_dataset_manifest.json`
- 状态：`PASS`
- row_count：`15`
- user_count：`4313`
- item_count：`16`
- 口径：`medium_behavior + collaborative_rich` 用户，`cf_ready` item，`min_pair_support=2`。
- 注意：该 method dataset 是治理证据；实际 source index 使用 formal train sequence 构建完整 item-item sidecar。

## source artifact

### smoke source

- manifest：`outputs/recall/pool500_method_sources/recent_2y/swing_recall/smoke/run_20260603_smoke_train_only_v1/source_index_manifest.json`
- 状态：`PASS`
- edge_count：`1082`
- seed_count：`232`
- 参数：`max_item_user_freq=1000`、`max_user_items=50`、`min_pair_support=1`、`per_seed_top_k=40`。

### historical baseline / hotcap sweep（已清理大型 artifact）

- 旧 baseline（`max_item_user_freq=100`）曾产出 `edge_count=237681`、`seed_count=46788`，但 seed 入口被热门 item hard drop 明显切断。
- hotcap1000 旧实验曾产出 `edge_count=457372`、`seed_count=65693`，证明放宽 hotcap 能修复覆盖，但它仍是旧公式/旧口径下的过渡实验。
- 这些旧大型 artifact 已在 F1 固定后清理；当前可用主路 artifact 只保留 F1，历史结论保留为文字和后续 Datawhale/F1 JSON evidence。

### Datawhale 标准公式实验（2026-06-06 guarded）

Datawhale Swing 页面给出的核心公式是：

```text
s(i,j) = sum over u,v in U_i ∩ U_j of w_u * w_v / (alpha + |I_u ∩ I_v|)
w_u = 1 / sqrt(|I_u|)
```

当前 builder 保留 `legacy_approx` 默认模式，同时新增 `datawhale_standard` 模式用于对齐该公式。工程口径如下：

- `I_u` 使用 train-only、positive-only、去重、`max_user_items` 截断且 hot-drop 后的 retained item set。
- `min_user_items=2` 表示只过滤无法贡献 item pair 的冷启动/单行为用户；不默认过滤 2~4 行为用户。
- `datawhale_standard` 对共同用户采用 `distinct_unordered` 用户对，避免双向重复计数；该口径写入 audit。
- valid/test label 只用于 evaluation-only raw eval / funnel diagnostic，不参与构图、边过滤或候选生成。

远程 formal sweep 输出目录：`outputs/recall/pool500_method_sources/recent_2y/swing_recall/formal_20260606_datawhale/`；汇总：`swing_datawhale_standard_ab_summary_20260606.json`。

| variant | score_mode | min_user_items | edge_count | seed_count | retained_user_count | valid HitRate@20 | valid HitRate@500 | test HitRate@20 | test HitRate@500 | test Recall@500 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | `legacy_approx` | 2 | 457372 | 65693 | 1558964 | 0.005815 | 0.008010 | 0.001601 | 0.002132 | 0.001860 |
| B | `datawhale_standard` | 2 | 457372 | 65693 | 1558964 | 0.006372 | 0.008055 | 0.001771 | 0.002156 | 0.001890 |
| C | `datawhale_standard` | 3 | 448504 | 61243 | 687556 | 0.005659 | 0.007364 | 0.001647 | 0.002025 | 0.001765 |

结论：

- B 只改变评分公式，不改变 edge/seed 覆盖，相比 A 在 top20 排序质量上更好：valid `HitRate@20` 从 `0.005815` 到 `0.006372`，test `HitRate@20` 从 `0.001601` 到 `0.001771`；`HitRate@500` / `Recall@500` 也有小幅提升。
- C 证明过度过滤低交互用户不合适：`min_user_items=3` 将 retained users 从 `1558964` 降到 `687556`，edge/seed 和 valid/test 指标均下降。
- 因此后续 guarded improved source 优先选择 `datawhale_standard + min_user_items=2 + max_item_user_freq=1000`，但仍不自动 promotion；需要等待全局 route overlap、marginal hit 和预算 gate。
- 对应 audit 均保持 `train_only=true`、`valid_test_holdout_usage=not_read`、`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

### src/dst item count filter-before-build 实验（2026-06-06 guarded）

根据 Datawhale Swing 对用户-物品二部图内部结构的依赖，本轮追加验证“先筛 item、再基于筛后 item sequence 筛 user”的构图策略，并把 item 过滤拆成两个方向口径：

- `src_item`：用户历史 seed item，要求 train-only positive user count 达到 `min_src_item_positive_user_count` 后才允许作为扩展入口。
- `dst_item`：被推荐/扩展出来的目标 item，要求 train-only positive user count 达到 `min_dst_item_positive_user_count` 后才允许写为候选目标。
- user 过滤后移到 item filter 之后：先按 hot drop + src/dst eligible union 清洗用户序列，再要求 retained item count `>= min_user_items`。
- 所有 count 均来自 `user_sequences.train.jsonl` 的 positive-only distinct users；valid/test label 仍只用于 evaluation-only raw eval / funnel diagnostic。

远程 formal sweep 输出目录：`outputs/recall/pool500_method_sources/recent_2y/swing_recall/formal_20260606_datawhale_item_filter/`；汇总文件：`swing_datawhale_item_filter_summary_20260606.json`，基线对比：`swing_datawhale_item_filter_baseline_comparison_20260606.json`。

| variant | src_min | dst_min | edge_count | seed_count | retained_user_count | valid HitRate@20 | valid HitRate@500 | test HitRate@20 | test HitRate@500 | test Recall@500 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B baseline | - | - | 457372 | 65693 | 1558964 | 0.006372 | 0.008055 | 0.001771 | 0.002156 | 0.001890 |
| D0 | 1 | 1 | 410692 | 63284 | 1328466 | 0.005225 | 0.006495 | 0.001540 | 0.001817 | 0.001568 |
| D1 | 2 | 2 | 410692 | 63284 | 1265201 | 0.005247 | 0.006495 | 0.001540 | 0.001817 | 0.001568 |
| D2 | 2 | 3 | 409451 | 63098 | 1265201 | 0.005236 | 0.006484 | 0.001540 | 0.001817 | 0.001568 |
| D3 | 2 | 5 | 406218 | 62585 | 1265201 | 0.005192 | 0.006439 | 0.001540 | 0.001809 | 0.001564 |
| D4 | 3 | 3 | 408278 | 62464 | 1218913 | 0.005258 | 0.006473 | 0.001540 | 0.001832 | 0.001578 |
| D5 | 3 | 5 | 405176 | 62014 | 1218913 | 0.005214 | 0.006439 | 0.001540 | 0.001824 | 0.001574 |

结论：

- 本轮 filter-before-build 的方向过滤实现可用，但 formal 指标不优于上一轮 B baseline。D4 是过滤组里 test `HitRate@500` 最高的点（`0.001832`），仍低于 B baseline 的 `0.002156`；所有 D0-D5 在 valid/test `HitRate@500` 与 `Recall@500` 上均低于 B。
- 主要损失来自“hot/item filter 后再筛 user”导致可服务协同用户减少：D0 retained users 从 B 的 `1558964` 降到 `1328466`，D4 进一步降到 `1218913`，edge/seed 覆盖同步下降。
- 因此当前不把 src/dst item count filter-before-build 变体提升为 guarded improved source；保留为诊断能力和后续分桶工具。现阶段仍优先沿用上一轮 B：`datawhale_standard + min_user_items=2 + max_item_user_freq=1000`。
- 所有 D0-D5 audit 均保持 train-only graph、no-holdout、candidate generation false、ranking input replacement false、pool1000 false、promotion false。

### pre-user-first src/dst item filter 实验（2026-06-06 guarded）

在 D0-D5 证明“先筛 item、再筛后重筛 user”会明显损失覆盖后，本轮按新的数据筛选假设改为：

1. 先过滤原始 retained unique positive items `<2` 的真冷用户；
2. 在 active-user universe 上统计 item train-only positive user count；
3. 再做 src/dst item count filter；
4. 同时对比是否继续 hard post-user filter。

远程采用 `PARALLEL_JOBS=3` 限流并行跑 E/F 两组，输出目录：`outputs/recall/pool500_method_sources/recent_2y/swing_recall/formal_20260606_datawhale_preuser_item_filter/`；汇总文件：`swing_datawhale_preuser_item_filter_summary_20260606.json`，基线对比：`swing_datawhale_preuser_item_filter_baseline_comparison_20260606.json`。

| variant | src_min | dst_min | post user filter | edge_count | seed_count | retained_user_count | valid HitRate@500 | test HitRate@500 | test Recall@500 |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B baseline | - | - | baseline | 457372 | 65693 | 1558964 | 0.008055 | 0.002156 | 0.001890 |
| E0 | 1 | 1 | on | 457372 | 65693 | 1426895 | 0.008055 | 0.002156 | 0.001890 |
| E1 | 2 | 2 | on | 457372 | 65693 | 1336092 | 0.008044 | 0.002163 | 0.001892 |
| E2 | 2 | 3 | on | 455718 | 65399 | 1336092 | 0.007921 | 0.002163 | 0.001892 |
| E3 | 3 | 3 | on | 454152 | 64455 | 1273216 | 0.007921 | 0.002156 | 0.001888 |
| E4 | 3 | 5 | on | 449811 | 63807 | 1273216 | 0.007854 | 0.002140 | 0.001877 |
| F0 | 1 | 1 | off | 457372 | 65693 | 1548770 | 0.008055 | 0.002156 | 0.001890 |
| F1 | 2 | 2 | off | 457372 | 65693 | 1538933 | 0.008044 | 0.002163 | 0.001892 |
| F2 | 2 | 3 | off | 455718 | 65399 | 1538933 | 0.007921 | 0.002163 | 0.001892 |
| F3 | 3 | 3 | off | 454152 | 64455 | 1527985 | 0.007921 | 0.002156 | 0.001888 |
| F4 | 3 | 5 | off | 449811 | 63807 | 1527985 | 0.007854 | 0.002140 | 0.001877 |

结论：

- 用户提出的“先筛冷用户，再筛 cold item”方向是对的：相较 D0-D5，E/F 组没有出现大幅覆盖坍塌，E0/F0 与 B baseline edge/seed 和指标完全一致。
- `src>=2,dst>=2`（E1/F1）和 `src>=2,dst>=3`（E2/F2）在 test 上有极小提升：`HitRate@500` 从 B 的 `0.002156` 到 `0.002163`，`Recall@500` 从 `0.001890` 到 `0.001892`；但 valid `HitRate@500` 从 `0.008055` 微降到 `0.008044` 或 `0.007921`。
- F 组关闭 hard post-user filter 能显著保留 retained users（F1 `1538933` vs E1 `1336092`），但 raw eval 指标与对应 E 组基本一致，说明 post-user hard filter 主要影响 audit/覆盖，不明显改变当前 edge 命中。
- 用户随后明确选择“固定 F1 并入主路”。因此当前 Swing 路线固定为 F1：`datawhale_standard + max_item_user_freq=1000 + min_user_items=2 + src>=2 + dst>=2 + pre-user-first + disable_post_item_user_filter`。
- 这里的“并入主路”是指主路默认 Swing sidecar artifact 切换到 F1；artifact 自身仍保持 `candidate_generation_allowed=false`、`promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`，避免把单 source raw eval 误写成自动全局 promotion。

### 当前固定的 F1 主路 artifact（2026-06-06）

- source manifest：`outputs/recall/pool500_method_sources/recent_2y/swing_recall/formal/run_20260606_datawhale_f1_main_route_v1/source_index_manifest.json`
- raw eval：`outputs/recall/pool500_method_sources/recent_2y/swing_recall/formal/run_20260606_datawhale_f1_main_route_v1/eval/swing_recent2y_f1_raw_eval_report.json`
- funnel diagnostic：`outputs/recall/pool500_method_sources/recent_2y/swing_recall/formal/run_20260606_datawhale_f1_main_route_v1/eval/swing_recent2y_f1_funnel_diagnostic.json`
- 关键参数：`score_mode=datawhale_standard`、`alpha=1.0`、`min_user_items=2`、`max_item_user_freq=1000`、`max_user_items=50`、`min_pair_support=2`、`per_seed_top_k=100`、`min_src_item_positive_user_count=2`、`min_dst_item_positive_user_count=2`、`pre_filter_users_before_item_count=true`、`disable_post_item_user_filter=true`。
- 关键证据：`edge_count=457372`、`seed_count=65693`、`retained_user_count=1538933`；valid `HitRate@500=0.008044` / `Recall@500=0.006821`，test `HitRate@500=0.002163` / `Recall@500=0.001892`。

## formal raw source eval

当前 F1 报告：`outputs/recall/pool500_method_sources/recent_2y/swing_recall/formal/run_20260606_datawhale_f1_main_route_v1/eval/swing_recent2y_f1_raw_eval_report.json`

| split | candidate_user_coverage_rate | HitRate@20 | HitRate@50 | HitRate@100 | HitRate@500 | Recall@500 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| valid | 0.139671 | 0.006350 | 0.007197 | 0.007654 | 0.008044 | 0.006821 |
| test | 0.063765 | 0.001771 | 0.002017 | 0.002132 | 0.002163 | 0.001892 |

历史 guarded baseline（大型 artifact 已清理）valid/test `HitRate@500` 分别为 `0.002295` / `0.000508`，主要被 `max_item_user_freq=100` 的 hot seed hard drop 限制。

分桶观察：

- valid `medium_behavior_4_9`：`HitRate@500=0.022533`，candidate coverage `0.72229`。
- test `medium_behavior_4_9`：`HitRate@500=0.022648`，candidate coverage `0.716028`。
- cold/single seed 桶覆盖很低，符合 Swing 对行为历史的依赖。

## formal 漏斗诊断

诊断脚本：`rs_lab/experiments/recall/diagnose_swing_recent2y_funnel.py`

当前 F1 报告：`outputs/recall/pool500_method_sources/recent_2y/swing_recall/formal/run_20260606_datawhale_f1_main_route_v1/eval/swing_recent2y_f1_funnel_diagnostic.json`

该诊断只用 train sequence、train-only Swing edges 和 dropped hot items 生成候选；valid/test label 只作为 evaluation-only hit 统计，不参与构图、边过滤或候选生成。

| split | missing_train_sequence_users | has_train_sequence_users | has_seed_in_graph_users | generated_candidate_user_count | users_without_graph_seed_but_hot_dropped_seed | target_exists_as_any_dst_rate | HitRate@500 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| valid | 70623 | 19138 | 12546 | 12537 | 732 | 0.620136 | 0.008044 |
| test | 115624 | 14275 | 8292 | 8283 | 522 | 0.637642 | 0.002163 |

结论：F1 通过 `max_item_user_freq=1000` 与 pre-user-first src/dst 过滤显著修复了旧版 `max_item_user_freq=100` 的 seed 入口切断问题；但 eval 用户中仍有大量用户没有 train sequence，因此 Swing 仍是行为协同补充源，不是冷启动主力。下一阶段重点应放在主路 source overlap / marginal lift / underfill gate，而不是继续单 source 内部微调。

## 当前问题与 blocker

当前已将 F1 固定为 Swing 默认主路 artifact，但仍保留以下 blocker：

1. raw source eval 只能证明单 source 可用，不能证明 route-level marginal lift。
2. 尚未与 popular/category/itemcf/two_tower/semantic 等 source 做 overlap 与新增命中用户对比。
3. `candidate_generation_allowed`、`promotion_allowed`、`ranking_input_replacement_allowed`、`pool1000_allowed` 仍保持 false；主路调用必须通过显式 artifact path 和 route gate 审计。
4. F1 相比 B baseline test 有极小提升，但 valid 有极小回落，因此后续需要 route-level 监控其真实边际贡献。

## 验证命令

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_diagnose_swing_recent2y_funnel.py tests/test_sciomc_swing_recent2y_preprocess.py tests/test_full_train_swing_sidecar.py tests/test_pool500_swing_recall_enhanced_source.py -q
```

结果：Datawhale 标准公式改造后 focused `tests/test_full_train_swing_sidecar.py` 为 `38 passed in 0.55s`，Swing 相关回归为 `44 passed in 0.66s`；src/dst item filter-before-build 改造后 focused 为 `43 passed in 0.67s`，Swing 相关回归为 `49 passed in 0.76s`；pre-user-first src/dst item filter 改造后 focused 为 `45 passed in 0.63s`，Swing 相关回归为 `51 passed in 0.82s`。远程服务器缺少 pytest（`No module named pytest`），已用 `.venv/bin/python -m py_compile` 校验 builder/eval/diagnostic 脚本语法，并完成 D0-D5 与 E/F formal sweep。

## 下一步

- 在全局 pool500 主路收口中，用 formal source manifest 参与 source overlap / marginal hit / underfill route gate。
- 若 route gate 证明有互补贡献，再由全局任务决定是否开启 candidate generation。
- 若 overlap 高或 marginal lift 不足，保持 `READY_GUARDED` 作为受控行为协同补充 source。