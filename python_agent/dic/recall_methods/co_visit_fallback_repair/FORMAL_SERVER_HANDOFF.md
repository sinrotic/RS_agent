# co_visit_fallback_repair formal server handoff

日期：2026-06-06

## 背景

`co_visit_fallback_repair` 已有 recent-2y smoke dataset、formal dataset manifest 和 smoke source 七件套；缺失的是 formal source artifact 与 evaluation-only 报告。formal dataset 覆盖约 1,558,964 eligible users，本地 full formal 可能达到亿级候选行，不允许在交互本机盲跑。当前可执行的正式收口方案是先在 server 上跑受控 50k formal shard diagnostic，再根据资源审计决定是否继续分片扩展。

已确认存在的输入 / smoke 产物：

- smoke dataset manifest：`outputs/recall/pool500_method_sources_newdata/co_visit_recent2y_smoke_dataset_v1/manifest.json`
- smoke eligible manifest：`outputs/recall/pool500_method_sources_newdata/co_visit_recent2y_smoke_dataset_v1/eligible_user_manifest.json`
- formal eligible manifest：`outputs/recall/pool500_method_sources_newdata/co_visit_recent2y_formal_dataset_v1/eligible_user_manifest.json`
- smoke source manifest：`outputs/recall/pool500_method_sources_newdata/co_visit_fallback_repair/co_visit_recent2y_smoke_dataset_20260602/source_index_manifest.json`

缺失的 formal source 产物：

- `outputs/recall/pool500_method_sources_newdata/co_visit_fallback_repair/co_visit_recent2y_formal_shard50k_20260603/source_index_manifest.json`
- 同目录下 `method_dataset_manifest.json`、`candidates.jsonl`、`coverage_audit.json`、`undercoverage_audit.json`、`resource_audit.json`、`no_holdout_audit.json`
- evaluation-only 报告目录：`outputs/eval/pool500_method_sources_newdata/co_visit_fallback_repair/co_visit_recent2y_formal_shard50k_20260603/`

## 本地允许的有限检查

只允许 dry-run / 小规模 smoke，不启动本地 50k 或 155.9 万 formal。

### formal shard50k dry-run

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source co_visit_fallback_repair --config configs/recall/full_data_pool500/co_visit_fallback_repair/source_config_newdata_formal_shard50k.yaml --tier formal_shard50k --run-id co_visit_recent2y_formal_shard50k_20260603 --dry-run
```

期望 dry-run 重点字段：

- `tier=formal_shard50k`
- `target_user_limit=50000`
- `resource_guard.heavy_job=true`
- `resource_guard.execution_preference=server`
- `complete_co_visit_graph_claimed=false`
- `candidate_generation_allowed=false`
- `ranking_input_replacement_allowed=false`

### smoke dry-run（仅 schema / contract 复核）

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source co_visit_fallback_repair --config configs/recall/full_data_pool500/co_visit_fallback_repair/source_config_newdata_smoke.yaml --tier smoke --dry-run
```

## 远程 formal shard50k 构建命令

在授权远程服务器的项目根目录执行，Python 环境需等价于本项目 `.venv`。若服务器路径不同，只替换解释器路径和项目根路径，不改 source/tier/config/run-id 语义。

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source co_visit_fallback_repair --config configs/recall/full_data_pool500/co_visit_fallback_repair/source_config_newdata_formal_shard50k.yaml --tier formal_shard50k --run-id co_visit_recent2y_formal_shard50k_20260603 --overwrite
```

资源约束：

- 仅运行 `target_user_limit=50000` 的受控 shard，不直接运行 1,558,964 用户 full formal。
- 保持 `batch_size=1000`、`checkpoint_every_users=1000`。
- 运行中监控 CPU、内存、磁盘和 `candidates.jsonl` 增长；如资源接近服务器上限，保留 checkpoint/resource audit 并停止，不做强行 full formal。

## formal shard50k evaluation-only 命令

source artifact 七件套完成后执行：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/evaluate_method_source_artifact.py --source-index-manifest outputs/recall/pool500_method_sources_newdata/co_visit_fallback_repair/co_visit_recent2y_formal_shard50k_20260603/source_index_manifest.json --eligible-user-manifest outputs/recall/pool500_method_sources_newdata/co_visit_recent2y_formal_dataset_v1/eligible_user_manifest.json --output-dir outputs/eval/pool500_method_sources_newdata/co_visit_fallback_repair/co_visit_recent2y_formal_shard50k_20260603 --overwrite
```

valid/test label 只允许作为 evaluation-only 输入，不得影响候选生成、筛边、metadata bucket 或用户选择。

## 必须回传 / 复核的文件

source artifact 七件套：

- `outputs/recall/pool500_method_sources_newdata/co_visit_fallback_repair/co_visit_recent2y_formal_shard50k_20260603/method_dataset_manifest.json`
- `outputs/recall/pool500_method_sources_newdata/co_visit_fallback_repair/co_visit_recent2y_formal_shard50k_20260603/source_index_manifest.json`
- `outputs/recall/pool500_method_sources_newdata/co_visit_fallback_repair/co_visit_recent2y_formal_shard50k_20260603/candidates.jsonl`
- `outputs/recall/pool500_method_sources_newdata/co_visit_fallback_repair/co_visit_recent2y_formal_shard50k_20260603/coverage_audit.json`
- `outputs/recall/pool500_method_sources_newdata/co_visit_fallback_repair/co_visit_recent2y_formal_shard50k_20260603/undercoverage_audit.json`
- `outputs/recall/pool500_method_sources_newdata/co_visit_fallback_repair/co_visit_recent2y_formal_shard50k_20260603/resource_audit.json`
- `outputs/recall/pool500_method_sources_newdata/co_visit_fallback_repair/co_visit_recent2y_formal_shard50k_20260603/no_holdout_audit.json`

评估报告：

- `outputs/eval/pool500_method_sources_newdata/co_visit_fallback_repair/co_visit_recent2y_formal_shard50k_20260603/method_source_eval_report.json`
- `outputs/eval/pool500_method_sources_newdata/co_visit_fallback_repair/co_visit_recent2y_formal_shard50k_20260603/metrics.json`
- `outputs/eval/pool500_method_sources_newdata/co_visit_fallback_repair/co_visit_recent2y_formal_shard50k_20260603/segment_metrics.json`
- `outputs/eval/pool500_method_sources_newdata/co_visit_fallback_repair/co_visit_recent2y_formal_shard50k_20260603/source_audit.json`

## 验收清单

- `source=co_visit_fallback_repair`
- `canonical_source=co_visit_fallback_repair`
- `source_status=TARGET_SLICE_DIAGNOSTIC`
- `algorithm_scope=train_transition_metadata_repair_v0`
- `complete_co_visit_graph_claimed=false`
- `no_holdout_audit.status=PASS`
- `candidate_generation_allowed=false`
- `ranking_input_replacement_allowed=false`
- `pool1000_allowed=false`
- `promotion_allowed=false`
- `target_user_limit=50000` 的 shard 范围清晰记录，不能包装成 155.9 万 full formal 完成。
- 报告至少覆盖 Recall@K、user coverage、candidate count stats、user bucket breakdown、underfilled repair delta、source overlap 和 no-holdout audit；缺项需列为 route gate blocker。

## 晋升边界

formal shard50k 完成后仍不自动 READY。只有后续全局 route gate 证明 fallback repair 对 underfilled users 有边际补足价值，且与 popular/category/ItemCF/Swing/semantic 等 source overlap 可接受、资源成本可控，才可讨论从 `DEFERRED` 进入更高 readiness。否则继续作为 diagnostic shadow / fallback research source。