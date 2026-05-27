# co_visit_fallback_repair

## 方法定位

`co_visit_fallback_repair` 是 pool500 的 fallback repair source，用于在行为召回覆盖不足时，从 train-only 用户序列 transition 与静态 metadata neighbor 中生成补充候选。当前实现语义是 `algorithm_scope=train_transition_metadata_repair_v0`，不是完整 co-visit graph；`complete_co_visit_graph_claimed=false`。

当前定位是 `deferred_evidence_policy` / `TARGET_SLICE_DIAGNOSTIC`：可以产出诊断 source artifacts，但不得宣称 READY，不替换 ranking input，不进入 pool1000。

## 统一配置与 runner

- 配置路径：`configs/recall/full_data_pool500/co_visit_fallback_repair/source_config.yaml`
- smoke / dry-run / source dispatch 统一入口：`scripts/experiments/recall/pool500/run_pool500_method_source.py`
- 档位：`smoke`、`dam(diagnostic)`、`最终数据集(local_formal)`

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source co_visit_fallback_repair --tier smoke --dry-run
```

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source co_visit_fallback_repair --tier smoke --overwrite
```

显式 config smoke：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source co_visit_fallback_repair --config configs/recall/full_data_pool500/co_visit_fallback_repair/source_config.yaml --tier smoke --dry-run
```

## 输出契约

必须生成七件套 source artifacts：

- `method_dataset_manifest.json`
- `source_index_manifest.json`
- `candidates.jsonl`
- `coverage_audit.json`
- `undercoverage_audit.json`
- `resource_audit.json`
- `no_holdout_audit.json`

核心 identity / governance 字段：

- `source=co_visit_fallback_repair`
- `canonical_source=co_visit_fallback_repair`
- `source_status=TARGET_SLICE_DIAGNOSTIC`
- `algorithm_scope=train_transition_metadata_repair_v0`
- `complete_co_visit_graph_claimed=false`
- `candidate_generation_allowed=false`
- `ranking_input_replacement_allowed=false`
- `pool1000_allowed=false`
- `promotion_allowed=false`
- `full_pool500_ready_declared=false`
- `final_pool500_ready_claimed=false`

## v0 语义边界

本轮 v0 只声明 train transition + metadata repair 能力：

- train-only seed item 触发 bounded transition neighbor。
- metadata neighbor 作为 fallback repair，不等价于完整共访图。
- `pair_support` 是 follow-up 统计，不是 gate。
- `distinct_user_support` 是 follow-up 统计，不是 gate。
- 后续若要声明完整 co-visit graph，需要另起计划补 pair 支撑、distinct user 支撑、时间窗、去噪、热门 item 上限和 full-run gate。

## 输入 artifact

- full clean manifest：`data/processed/amazon_2023_recall_clean_full/manifest.json`
- full lightweight views manifest：`data/processed/amazon_2023_recall_views_full_lightweight/manifest.json`
- eligible user manifest：`outputs/recall/pool500_main_route_direct_recall_full_promoted/eligible_user_manifest.json`
- train-only user sequences、train interactions、semantic recall inputs / static metadata

## 治理边界

- 只使用 train-only 用户历史、train-only transition 与静态 item metadata。
- 不使用 holdout、valid、test、LOPO、clean_10000、youtube_dnn、pool1000 证据。
- 不用评估命中、label、oracle 反向筛边或筛候选。
- 不宣称 full pool500 READY；不得宣称 READY。
- 不替换 ranking input。
- 不进入 pool1000。
- 不把 metadata-neighbor diagnostic evidence 包装成完整 co-visit graph 或 READY 主召回源。

## 后续优化方向

后续优化应单独建设或验证真实 train-only co-visit graph，并把 `pair_support`、`distinct_user_support`、时间窗、热门 item 上限、去噪策略和 underfill 改善变成可审计 manifest 与测试。在 source gate 通过前，仍必须保持 diagnostic-only、no promotion、no ranking replacement、no pool1000 的治理边界。
