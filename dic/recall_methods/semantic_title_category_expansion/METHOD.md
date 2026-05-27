# semantic_title_category_expansion

## 方法定位

`semantic_title_category_expansion` 是 pool500 的标题 / 类目 / metadata 扩展召回 source，基于用户近期 train-only seed item 的 title token、category 和静态 metadata overlap 生成补充候选。当前定位是 `deferred_evidence_policy` / `TARGET_SLICE_DIAGNOSTIC`：用于产出受控诊断 source artifacts，但不得宣称 READY，不替换 ranking input，不进入 pool1000。

它不是 canonical `semantic` 的别名，也不能替代 `semantic` source identity。若内部复用相同 metadata 输入，manifest 仍必须保持 `source=semantic_title_category_expansion`、`canonical_source=semantic_title_category_expansion`。

## 统一配置与 runner

- 配置路径：`configs/recall/full_data_pool500/semantic_title_category_expansion/source_config.yaml`
- smoke / dry-run / source dispatch 统一入口：`scripts/experiments/recall/pool500/run_pool500_method_source.py`
- 档位：`smoke`、`dam(diagnostic)`、`最终数据集(local_formal)`

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic_title_category_expansion --tier smoke --dry-run
```

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic_title_category_expansion --tier smoke --overwrite
```

显式 config smoke：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic_title_category_expansion --config configs/recall/full_data_pool500/semantic_title_category_expansion/source_config.yaml --tier smoke --dry-run
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

## 输入 artifact

- full clean manifest：`data/processed/amazon_2023_recall_clean_full/manifest.json`
- full lightweight views manifest：`data/processed/amazon_2023_recall_views_full_lightweight/manifest.json`
- eligible user manifest：`outputs/recall/pool500_main_route_direct_recall_full_promoted/eligible_user_manifest.json`
- train-only user sequences、canonical item metadata、semantic recall inputs、semantic inverted index

## 治理边界

- 只使用 train-only 用户历史与静态 item metadata。
- 不使用 holdout、valid、test、LOPO、clean_10000、youtube_dnn、pool1000 证据。
- 不用评估命中、label、oracle 反向选择 token、category 或 metadata bucket。
- 不宣称 full pool500 READY；不得宣称 READY。
- 不替换 ranking input。
- 不进入 pool1000。
- 如需晋升或替换 ranking 输入，后续必须另起计划并重新验证 source quality、underfill 改善、overlap 和 ranking gate。

## 后续优化方向

后续应围绕 title/category overlap 的覆盖率、泛词过滤、类目桶上限、去重后边际贡献和资源边界做诊断。修改 token/category 策略时必须同步 config、registry、METHOD、builder manifest 与测试，避免把 batch-scoped diagnostic evidence 包装成 READY。
