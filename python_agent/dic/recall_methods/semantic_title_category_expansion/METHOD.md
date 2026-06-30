# semantic_title_category_expansion

## 方法定位

`semantic_title_category_expansion` 是 pool500 的标题 / 类目 metadata 扩展能力：基于 recent-2y train-only 商品 `title_clean`、`main_category`、`categories_flat` token overlap 和 category overlap 帮助识别商品类型与类目先验。

当前 recent-2y 结论：**保持 `DEFERRED` / `TARGET_SLICE_DIAGNOSTIC`，不作为独立 READY source 晋升**。在本轮 description-based 语义召回目标下，它已折叠为 canonical `semantic` 的 title/category channel，为 `semantic` guarded candidate source 提供标题词、品类词和商品类型约束；不单独替换 ranking input，不进入 pool1000，不独立作为 pool500 主路晋升结论。

它不是 canonical `semantic` 的别名，也不能替代 `semantic` source identity。若后续仍单独构建本 source artifact，manifest 必须保持：

- `source=semantic_title_category_expansion`
- `canonical_source=semantic_title_category_expansion`

## SciOMC 调研与 RALPLAN 计划

- SciOMC 调研文档：`dic/recall_methods/semantic_title_category_expansion/RECENT2Y_SCIOMC_RESEARCH.md`
- RALPLAN 执行计划：`dic/recall_methods/semantic_title_category_expansion/RECENT2Y_REBUILD_PLAN.md`

调研结论摘要：本方法更接近 lexical title/category overlap + category gate，而不是 dense semantic retrieval、two-tower 或 oracle repair。最佳实践是保留可解释、低成本、受控漂移的 source 定位：title token 扩展必须受 category overlap、token bucket cap、undercoverage audit 和 no-holdout audit 约束。论文侧参考了 Amazon item-to-item CF、BM25、Item2Vec、PinSage、Wide&Deep、NCF、BST 以及 neural recommendation reproducibility 相关工作；它们支持“候选生成先用强简单基线和可复核门禁”的取舍，但不支持本方法在缺少 formal/route gate 证据时直接 READY。

## 统一配置与 runner

- 配置路径：`configs/recall/full_data_pool500/semantic_title_category_expansion/source_config.yaml`
- dataset policy：`configs/recall/full_data_pool500/semantic_title_category_expansion/dataset_policy.yaml`
- smoke / dry-run / source dispatch 统一入口：`scripts/experiments/recall/pool500/run_pool500_method_source.py`
- 单 source evaluation-only 入口：`scripts/experiments/recall/pool500/evaluate_method_source_artifact.py`
- 档位：`smoke`、`dam(diagnostic)`、`最终数据集(local_formal)`；recent-2y 显式 alias 为 `recent2y_smoke`、`recent2y_formal`。

旧兼容 smoke dry-run：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic_title_category_expansion --tier smoke --dry-run
```

recent-2y smoke dry-run：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic_title_category_expansion --tier recent2y_smoke --run-id recent2y_smoke_dry --dry-run
```

recent-2y smoke 构建：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic_title_category_expansion --tier recent2y_smoke --run-id semantic_title_category_recent2y_smoke_v1 --overwrite
```

recent-2y formal 构建（需 server 优先）：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic_title_category_expansion --tier recent2y_formal --run-id semantic_title_category_recent2y_formal_v1 --overwrite
```

formal evaluation-only 报告：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/evaluate_method_source_artifact.py --source-index-manifest outputs/recall/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_formal_v1/source_index_manifest.json --eligible-user-manifest outputs/recall/pool500_method_sources_newdata/eligible_users_semantic_recent2y_formal_v1/eligible_user_manifest.json --output-dir outputs/eval/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_formal_v1 --overwrite
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

- `source=semantic_title_category_expansion`
- `canonical_source=semantic_title_category_expansion`
- `source_status=TARGET_SLICE_DIAGNOSTIC`
- `candidate_generation_allowed=false`
- `ranking_input_replacement_allowed=false`
- `pool1000_allowed=false`
- `promotion_allowed=false`
- `full_pool500_ready_declared=false`
- `final_pool500_ready_claimed=false`

## recent-2y 输入路径

- clean manifest：`data/processed/amazon_2023_recall_recent_2y_1m_3m/manifest.json`
- recall views manifest：`data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/manifest.json`
- smoke eligible manifest：`outputs/recall/pool500_method_sources_newdata/eligible_users_semantic_recent2y_smoke_v1/eligible_user_manifest.json`
- formal eligible manifest：`outputs/recall/pool500_method_sources_newdata/eligible_users_semantic_recent2y_formal_v1/eligible_user_manifest.json`
- 只使用既有 recent-2y `semantic_recall_inputs` 与 `semantic_inverted_index`，先做 audit/contract 检查；旧 full-data artifact 只能作为历史参考。

## 已完成验证证据

### smoke source artifact

- manifest：`outputs/recall/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_smoke_v1/source_index_manifest.json`
- method dataset manifest：`outputs/recall/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_smoke_v1/method_dataset_manifest.json`
- candidates：`outputs/recall/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_smoke_v1/candidates.jsonl`
- `candidate_row_count=15526`
- `user_coverage_count=200/200`
- `candidate_count_p50=80`，`candidate_count_p90=80`，`candidate_count_max=80`
- `title_coverage=1.0`，`category_coverage=1.0`，`seed_item_metadata_coverage=1.0`
- `no_holdout_audit.status=PASS`
- `promotion_allowed=false`，`ranking_input_replacement_allowed=false`，`pool1000_allowed=false`

### smoke evaluation-only 脚本验证

- 报告：`outputs/eval/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_smoke_v1/method_source_eval_report.json`
- `eval_scope=evaluation_only`
- `label_inputs_role=evaluation_only_not_candidate_generation_inputs`
- `scored_user_count=1`，`skipped_candidate_user_without_eval_label_count=199`
- Recall/HitRate 均为 0.0；由于 smoke 不是正式效果集，不能据此判断方法效果。

### 自动化测试

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_semantic_newdata_config.py tests/test_pool500_semantic_title_category_source.py tests/test_pool500_method_source_eval.py -q
```

结果：`21 passed`。

## 与描述式语义召回的关系

用户当前目标下，`semantic_title_category_expansion` 不再作为独立强召回方法硬冲 valid purchase Recall，而是作为 `semantic` 的 title/category channel：帮助描述式语义召回识别核心标题词、商品类型和类目先验，降低泛词 overlap 带来的误召回。

对应诊断脚本与 `semantic` 共用：

```bash
./.venv/Scripts/python.exe scripts/experiments/recall/pool500/diagnose_semantic_description_recall.py --output-dir outputs/diagnostics/semantic_description_recall_strict_v2_20260608
```

该诊断只使用 train-visible item metadata 与 inverted index，不读取 valid/test/holdout/oracle/eval_label。当前 random6 guarded evidence 已通过 `PASS_GUARDED_CANDIDATE`（`avg_strict_precision_at_10=0.9`、`avg_bad_intent_rate_at_10=0.1`），说明 title/category channel 对明确商品描述有实际帮助；strict stress 仍为 `DIAGNOSTIC_ONLY`（`avg_strict_precision_at_10=0.483`、`avg_bad_intent_rate_at_10=0.267`），显示弱词 query（如 `yoga_mat`、`baby_stroller_organizer`、`cat_litter_mat`）仍需更强 product-type gate、category prior 和 phrase/rerank 增强。

## formal 状态与 blocker

本轮 formal 目标为 50k eligible users：collaborative_rich 10000、sequence_sufficient 30000、fallback_only 10000。该构建在本地启动后已有 checkpoint（当前复核到 `semantic_index_loaded`，`user_count=50000`），但尚未产出七件套；由于 smoke 200 用户已耗时约 149.7 秒，按 50k formal 估算本地继续构建会显著超出交互窗口和资源边界；已按“重资源任务优先 server”原则停止本地 formal。

formal blocker：

- 本地 `semantic_title_category_recent2y_formal_v1` 仅有 `checkpoint.json`，没有七件套，不可作为 formal artifact；
- 需要迁移 server 运行 formal 构建，并回传 `source_index_manifest.json`、`method_dataset_manifest.json`、`coverage_audit.json`、`undercoverage_audit.json`、`resource_audit.json`、`no_holdout_audit.json`、`candidates.jsonl` 和 evaluation-only 报告；
- 在 formal 产物和 route gate/overlap 证据缺失前，不建议作为独立 source 并入 pool500 主路；其 title/category 能力通过 `semantic` guarded candidate source 间接进入主路。

## 治理边界

- 只使用 train-only 用户历史与静态 item metadata。
- 不使用 holdout、valid、test、LOPO、clean_10000、youtube_dnn、pool1000 证据作候选生成或训练/索引输入。
- 不用评估命中、label、oracle 反向选择 token、category 或 metadata bucket。
- 不宣称 full pool500 READY；不得宣称 READY。
- 不替换 ranking input。
- 不进入 pool1000。
- 如需晋升或替换 ranking 输入，后续必须另起全局收口/route gate 计划并重新验证 source quality、underfill 改善、overlap、Recall@K 和资源成本。

## 后续优化方向

1. 在 server 完成 formal 50k 构建与 evaluation-only 报告。
2. 报告与 category、semantic、popular、CF sources 的 source overlap 和边际 positive hits。
3. 对 token bucket truncation 做泛词过滤或 BM25 风格 IDF 权重实验，但不能使用 eval label 调参。
4. 若 formal 证明有互补价值，再进入全局 pool500 主路收口；否则保持 `DEFERRED` / diagnostic shadow source。
