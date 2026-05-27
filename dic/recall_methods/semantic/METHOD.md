# semantic

## 方法定位

`semantic` 是 pool500 的 canonical 语义召回 source，用于基于 train-only 用户历史 seed item 与静态 item metadata 的语义相似性补充候选覆盖。当前定位是 `deferred_evidence_policy` / `TARGET_SLICE_DIAGNOSTIC`：可以生成受控诊断证据，但不得宣称 READY，不替换 ranking input，不进入 pool1000。

`semantic` 与 `semantic_title_category_expansion` 是两个独立 source。实现上可以复用 metadata/token 处理逻辑，但 manifest 与候选行中的 `source`、`canonical_source` 必须保持为 `semantic`，不能由 `semantic_title_category_expansion`、`semantic_title` 或 `full_metadata_overlap` 冒充。

## 统一配置与 runner

- 配置路径：`configs/recall/full_data_pool500/semantic/source_config.yaml`
- smoke / dry-run / source dispatch 统一入口：`scripts/experiments/recall/pool500/run_pool500_method_source.py`
- 档位：`smoke`、`dam(diagnostic)`、`最终数据集(local_formal)`

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic --tier smoke --dry-run
```

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic --tier smoke --overwrite
```

显式 config smoke：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic --config configs/recall/full_data_pool500/semantic/source_config.yaml --tier smoke --dry-run
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

- `source=semantic`
- `canonical_source=semantic`
- `source_status=TARGET_SLICE_DIAGNOSTIC`
- `candidate_generation_allowed=false`
- `ranking_input_replacement_allowed=false`
- `pool1000_allowed=false`
- `promotion_allowed=false`
- `full_pool500_ready_declared=false`
- `final_pool500_ready_claimed=false`

## 输入 artifact

- full clean manifest：`data/processed/amazon_2023_recall_clean_full/manifest.json`
- full lightweight views manifest：`data/processed/amazon_2023_recall_views_full_lightweight/manifest.json`
- eligible user manifest：`outputs/recall/pool500_main_route_direct_recall_full_promoted/eligible_user_manifest.json`
- train-only user sequences、canonical item metadata、semantic recall inputs、semantic inverted index

## 治理边界

- 只使用 train-only 用户历史与静态 item metadata。
- 不使用 holdout、valid、test、LOPO、clean_10000、youtube_dnn、pool1000 证据。
- 不用评估命中、label、oracle 反向筛选 metadata 或候选。
- 不宣称 full pool500 READY；不得宣称 READY。
- 不替换 ranking input。
- 不进入 pool1000。
- 如需晋升，后续必须另起 full-clean-safe readiness / ranking input / pool1000 计划并显式验证。

## 后续优化方向

后续优化应围绕 metadata 覆盖、语义 token 质量、去重后边际贡献、underfill 改善和资源边界展开。任何 token/category 扩展策略调整都要同步更新 config、METHOD、registry、manifest 与测试，且在通过 source gate 前不得包装为 READY 或正式 ranking 输入。
