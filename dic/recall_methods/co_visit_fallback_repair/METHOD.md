# co_visit_fallback_repair

## 方法定位

`co_visit_fallback_repair` 是 pool500 主路中的 fallback repair 证据源，用于补行为召回的连接缺口。当前实现是 metadata-neighbor-backed diagnostic repair：candidate merge 生成 `metadata_neighbor_recall`，runner 将其 canonicalize 为 `co_visit_fallback_repair`，并作为 `BATCH_SCOPED_DIAGNOSTIC` 证据源处理。

它不是独立 co-visit graph，也不是 READY 主召回源。

## 当前 readiness

- 状态：`DEFERRED`
- 本轮 evidence status：`BATCH_SCOPED_DIAGNOSTIC`
- probe 输出目录：`outputs/recall/full_data_pool500_recall_only_semantic_covisit_probe_50x200k`
- per-source manifest：`outputs/recall/full_data_pool500_recall_only_semantic_covisit_probe_50x200k/sources/co_visit_fallback_repair/manifest.json`
- 禁止授权：`promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`

## 输入 artifact

- full clean manifest：`data/processed/amazon_2023_recall_clean_full/manifest.json`
- full lightweight views manifest：`data/processed/amazon_2023_recall_views_full_lightweight/manifest.json`
- semantic recall inputs：`data/processed/amazon_2023_recall_views_full_lightweight/semantic_recall_inputs.jsonl`
- train-only user sequences / canonical item metadata

当前不使用 `user_quality` 作为 recall source；如引用用户质量，只能作为诊断切片解释，不能替代 recall source evidence 或 READY 晋升依据。

## Direct recall probe 证据

受控 probe 命令：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.run_full_data_pool500_recall_only \
  --output-dir outputs/recall/full_data_pool500_recall_only_semantic_covisit_probe_50x200k \
  --enable-semantic \
  --semantic-max-rows 200000 \
  --limit-users 50 \
  --overwrite
```

关键输出：

- `manifest.json.status=STOP`，原因是整体 readiness/underfill gate，符合“不做 READY 晋升”的预期。
- `pool500_candidates.jsonl` 总行数：6152。
- `pool500_candidates.jsonl.sources.co_visit_fallback_repair=1063`。
- `source_contribution_audit.sources.co_visit_fallback_repair.row_count=1063`。
- `source_contribution_audit.sources.co_visit_fallback_repair.user_coverage_count=47`，`user_coverage_ratio=0.94`。
- `source_contribution_audit.sources.co_visit_fallback_repair.marginal_candidate_share=0.172789`。
- `final_resource_audit.source_row_counts.co_visit_fallback_repair=1063`。
- per-source manifest：`sources/co_visit_fallback_repair/manifest.json.status=BATCH_SCOPED_DIAGNOSTIC`。
- per-source manifest：`final_sources=[]`，`batch_scoped_evidence_only=true`。
- `per_source_readiness_contracts.co_visit_fallback_repair.status=BATCH_SCOPED_DIAGNOSTIC`。

## 与 semantic source manifest 的关系

本轮 co_visit 证据依赖同一批 full lightweight semantic / metadata inputs。`outputs/recall/full_semantic_title_category_expansion/source_index_manifest.json` 已确认：

- `source=semantic_title_category_expansion`
- `index_scope=FULL_DERIVED_INDEX`
- `no_holdout_audit.status=PASS`
- `resource_audit.status=PASS`
- `semantic_recall_inputs.row_count=2320263`

这证明 metadata/title/category 输入足以支撑当前 metadata-neighbor-backed fallback repair，但不等价于独立 co-visit graph 已建设完成。

## 适用用户

- 有可通过 metadata neighbor 形成局部邻接的近期行为用户。
- CF 边不足但 metadata 近邻可提供 fallback repair 的用户。
- 适合作为 batch-scoped repair evidence，不作为当前正式 READY 主召回源。

## 治理边界

- 不宣称独立 co-visit graph 已建设完成。
- 不宣称 full pool500 READY。
- 不使用 holdout、valid、test、LOPO、clean_10000。
- 不把 `user_quality` 写入 `pool500_candidates.jsonl.sources`。
- 不设置 `ranking_input_replacement_allowed=true`、`pool1000_allowed=true`、`promotion_allowed=true`。
- 如需 READY 晋升，后续必须另建或确认真实 train-only co-visit graph、full-run coverage、underfill 改善、source overlap 与 ranking gate 验证。

## 专项优化 Agent 调用说明

后续单独调用 Agent 优化本方法时，目标应是建设或确认真实 train-only co-visit graph，并验证 fallback repair 是否能补 underfill，而不是把 metadata neighbor diagnostic evidence 包装成 READY。Agent 必须保持 `deferred_evidence_policy`，产出 train-only co-visit input、触发条件、repair boundary、resource audit 和诊断 manifest；未通过 source gate 前不得宣称 READY、ranking input replacement 或 pool1000。

## P2 method_dataset 数据清洗与筛选方案

- 数据来源：只读取 train-only 用户历史、train-only co-visit edges 与 train-only/static item metadata；不继承 Popular/Category 的 full-statistics no-input-cap 合同。
- 筛选单位：`user_seed_item_to_bounded_co_visit_edges`。从用户近期 train-only seed item 出发，保留有支撑的 bounded repair 边。
- 适用数据：seed 来自 train-only 用户历史；repair 可使用 `title_clean`、`main_category` 等静态字段做弱约束。
- 清洗规则：过滤缺失 user/item id、pair support 不足、distinct user support 不足、超过热度上限的高噪声 item、非 train-only universe item；用户内去重并保持确定性排序。
- 规模参数：`max_target_users=500`、`seed_window=80`、`max_seed_items_per_user=80`、`items_per_seed=100`、`items_per_user=500`、`max_bucket_items=5000`、`min_pair_support=2`、`min_distinct_user_support=2`、`max_item_user_frequency=3000`。

### 规模档位

| 档位 | max_target_users | seed_window | max_seed_items_per_user | items_per_seed | items_per_user | max_bucket_items | min_pair_support | min_distinct_user_support | max_item_user_frequency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| smoke | 500 | 20 | 20 | 40 | 120 | 1000 | 1 | 1 | 3000 |
| diagnostic | 500 | 50 | 50 | 80 | 300 | 3000 | 2 | 2 | 3000 |
| local_formal | 500 | 80 | 80 | 100 | 500 | 5000 | 2 | 2 | 3000 |

- 泄漏边界：不读取 valid/test/holdout/LOPO/clean_10000/eval_label/oracle，不用评估命中反向筛边，不声明 READY、promotion、ranking input replacement 或 pool1000。
- 维护检查：修改 repair 边策略时同步检查 `co_visit_fallback_repair_v1`、pair 支撑阈值、热门 item 上限和 registry/builder/test 一致性。
