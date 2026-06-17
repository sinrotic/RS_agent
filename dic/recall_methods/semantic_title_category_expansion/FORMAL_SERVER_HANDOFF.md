# semantic_title_category_expansion formal server handoff

日期：2026-06-06

## 背景

本方法 recent-2y smoke 已在本地完成并通过 no-holdout audit；formal 目标为 50000 eligible users。由于 smoke 200 用户耗时约 149.7 秒，formal 本地构建已有本地 checkpoint（当前复核到 `semantic_index_loaded`，`user_count=50000`），但未产出七件套，仍按资源门禁停止在本地继续构建。后续应迁移 server 执行，完成后拉回 manifest、stats、评估报告和必要 artifact 本地复核。

## 本地允许的有限检查

只允许 dry-run / 小规模 smoke，不启动本地 50k formal。

### formal dry-run

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic_title_category_expansion --tier recent2y_formal --run-id semantic_title_category_recent2y_formal_v1 --dry-run
```

期望 dry-run 重点字段：

- `tier=recent2y_formal`
- `target_user_limit=50000`
- `eligible_user_manifest=outputs/recall/pool500_method_sources_newdata/eligible_users_semantic_recent2y_formal_v1/eligible_user_manifest.json`
- `formal_source_index_manifest=null`
- `formal_status=blocked_local_resource_requires_server`
- `candidate_generation_allowed=false`
- `ranking_input_replacement_allowed=false`

### smoke dry-run（仅 schema / contract 复核）

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic_title_category_expansion --tier recent2y_smoke --run-id recent2y_smoke_dry --dry-run
```

## 远程 formal 构建命令

在项目根目录执行：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source semantic_title_category_expansion --tier recent2y_formal --run-id semantic_title_category_recent2y_formal_v1 --overwrite
```

如远程服务器路径不同，保持 Python 解释器使用该项目 `.venv` 等价环境，并保证输入路径指向同一 recent-2y artifact：

- `data/processed/amazon_2023_recall_recent_2y_1m_3m/manifest.json`
- `data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/manifest.json`
- `outputs/recall/pool500_method_sources_newdata/eligible_users_semantic_recent2y_formal_v1/eligible_user_manifest.json`

## 评估命令

formal 构建完成后执行：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/evaluate_method_source_artifact.py --source-index-manifest outputs/recall/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_formal_v1/source_index_manifest.json --eligible-user-manifest outputs/recall/pool500_method_sources_newdata/eligible_users_semantic_recent2y_formal_v1/eligible_user_manifest.json --output-dir outputs/eval/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_formal_v1 --overwrite
```

## 必须回传/复核的文件

source artifact 七件套：

- `outputs/recall/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_formal_v1/method_dataset_manifest.json`
- `outputs/recall/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_formal_v1/source_index_manifest.json`
- `outputs/recall/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_formal_v1/candidates.jsonl`
- `outputs/recall/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_formal_v1/coverage_audit.json`
- `outputs/recall/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_formal_v1/undercoverage_audit.json`
- `outputs/recall/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_formal_v1/resource_audit.json`
- `outputs/recall/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_formal_v1/no_holdout_audit.json`

评估报告：

- `outputs/eval/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_formal_v1/method_source_eval_report.json`
- `outputs/eval/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_formal_v1/metrics.json`
- `outputs/eval/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_formal_v1/segment_metrics.json`
- `outputs/eval/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_formal_v1/source_audit.json`

## 验收清单

- `source=semantic_title_category_expansion`
- `canonical_source=semantic_title_category_expansion`
- `source_status=TARGET_SLICE_DIAGNOSTIC`
- `no_holdout_audit.status=PASS`
- `candidate_generation_allowed=false`
- `ranking_input_replacement_allowed=false`
- `pool1000_allowed=false`
- `promotion_allowed=false`
- `target_user_limit=50000`，不能把本地 `checkpoint.json` 包装成 formal 七件套完成。
- formal metrics 只用 valid/test label 做 evaluation-only，不参与候选生成、token/category 选择或候选过滤。
- 报告至少覆盖 Recall@K、user coverage、candidate count stats、source overlap、segment metrics 和 no-holdout audit；缺项需列为 route gate blocker。

## 晋升边界

formal 完成后也不自动 READY。只有在后续全局 route gate 中证明：

1. Recall@K/HitRate@K 有可解释收益；
2. 与 category/semantic/popular/CF source overlap 可接受或有边际补充；
3. source loader、candidate merge、route gate regression 通过；
4. 资源成本可控；

才可建议进入 pool500 主路。否则继续保持 `DEFERRED` / diagnostic shadow source。
