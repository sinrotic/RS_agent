# category recent-2y RALPLAN 重建计划

日期：2026-06-03

## 1. 决策摘要

**决策**：`category` 不再从旧 `pool500_sidecar_fix` / promoted candidates 派生当前结论，而是直接从 recent-2y train-visible 输入构建：

- `canonical_items.jsonl`
- `user_sequences.train.jsonl`
- `train_only_governance/user_quality_profile.jsonl`
- `train_only_governance/item_frequency_train.jsonl`
- `recall_views/category_top_items.jsonl`
- `recall_views/category_recall_items.jsonl`

`category` 是轻量统计召回，不需要 GPU、ANN 或大图构建；可本地 `.venv` 执行。但 formal 全量 route artifact 可能产生很大 candidates 文件，应留给后续 global route gate / server batch，而不是在本单方法窗口硬并主路。

## 2. 现状与缺口

### 旧现状

- `METHOD.md` 旧版本把 `category` 记为 READY，但 artifact 指向旧 `outputs/recall/pool500_sidecar_fix/...`。
- 旧 `source_config.yaml` 的 builder 逻辑通过 `promoted_dir` 读取已有候选，存在旧 artifact 回流风险。
- registry 旧 latest artifact 不是 recent-2y 单方法重建产物。

### 新基础

- recent-2y 主 manifest：`data/processed/amazon_2023_recall_recent_2y_1m_3m/manifest.json`
- train-only governance：`data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json`
- governance 状态：PASS，`train_only=true`，`valid/test/holdout/lopo_used=false`
- lightweight recall views：已有 `category_top_items` 与 `category_recall_items`

## 3. 可选方案与取舍

### 方案 A：沿用旧 lightweight_source_builder 包装 promoted candidates

- 优点：代码已有，运行快。
- 缺点：读取旧 promoted_dir 候选，无法证明当前 artifact 直接来自 recent-2y train-only 输入。
- 结论：不采用，最多作为历史参考。

### 方案 B：新建 recent-2y direct category builder

- 优点：lineage 清晰；可记录 user category profile；符合 train-only governance；可直接产生 smoke/formal manifest。
- 缺点：需要新增代码和评估脚本；formal 全量输出可能较大。
- 结论：采用。

### 方案 C：把 category 升级为复杂模型或 embedding source

- 优点：可能提高 Recall。
- 缺点：偏离 category 轻量 fallback 定位；与 semantic/two_tower 边界重叠；资源和解释成本变高。
- 结论：不采用。

## 4. Smoke contract

- run id：`category_recent2y_smoke_v1`
- 用户：500 个 train-only eligible 用户。
- 候选：每用户最多 40。
- profile：最近 20 个 seed item，最多 4 个 profile buckets。
- bucket cap：每类目最多 12 个候选。
- 目的：程序与 schema 验证。
- 禁止：用于正式效果、promotion、ranking replacement、pool1000。

交付路径：

```text
outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_smoke_v1/method_dataset_manifest.json
outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_smoke_v1/source_index_manifest.json
outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_smoke_v1/candidates.jsonl
outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_smoke_v1/user_category_profile.jsonl
```

## 5. Formal contract

- run id：`category_recent2y_formal_50k_v1`
- 用户：50,000 个 train-only eligible 用户。
- 候选：每用户最多 80。
- profile：最近 20 个 seed item，最多 6 个 profile buckets。
- bucket cap：每类目最多 20 个候选。
- 类目桶过滤：`category_min_item_count=5`。
- 目的：本地 formal 方法逻辑 artifact、coverage 和 eval-only Recall 证据。
- 限制：不是全量 1.56M eligible route artifact；全量并入需后续 global route gate / server batch。

交付路径：

```text
outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_formal_50k_v1/method_dataset_manifest.json
outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_formal_50k_v1/source_index_manifest.json
outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_formal_50k_v1/evaluation_report.json
```

## 6. 实施步骤

1. 新建 direct builder：`rs_lab/experiments/recall/pool500/methods/category/builder.py`。
2. 修改 `rs_lab/experiments/recall/pool500/methods/category/__init__.py`，导出 direct builder。
3. 更新 `source_config.yaml` 为 recent-2y input contract 和 smoke/formal tiers。
4. 更新 `dataset_policy.yaml`，明确 train-only、smoke/formal、禁止输入和 outputs。
5. 用 `.venv` 运行 smoke。
6. 用 `.venv` 运行 formal 50k。
7. 用 eval-only label 计算 Recall@20/50/80，不让 eval label 进入 candidate generation。
8. 更新 METHOD、registry、runtime source registry、工程叙事日志。
9. 运行 py_compile 和相关 pytest / import smoke 验证。

## 7. 命令

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m py_compile rs_lab/experiments/recall/pool500/methods/category/builder.py scripts/experiments/recall/pool500/run_pool500_method_source.py

D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source category --tier smoke --run-id category_recent2y_smoke_v1 --overwrite

D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source category --tier formal --run-id category_recent2y_formal_50k_v1 --overwrite
```

## 8. 验证指标

必须检查：

- `source_index_manifest.status == PASS`
- `no_holdout_audit.status == PASS`
- `candidate_generation_allowed=false`
- `ranking_input_replacement_allowed=false`
- `promotion_allowed=false`
- `candidate_row_count > 0`
- `user_coverage_ratio`、per-user candidate distribution、user bucket breakdown
- eval-only Recall@20/50/80
- category diversity 和 top category share

## 9. 完成条件

单方法完成条件：

1. SciOMC 调研文档存在。
2. RALPLAN 执行计划存在。
3. smoke artifact 构建成功。
4. formal 50k artifact 构建成功并记录 blocker：全量 route artifact 留给 global route gate / server batch。
5. evaluation report 存在，并明确 eval label 只用于评估。
6. METHOD、source_config、dataset_policy、registry、runtime registry 已更新。
7. 工程叙事日志更新。
8. 验证命令通过。

## 10. 停止 / blocker 条件

如果出现以下情况，不允许硬并主路：

- no-holdout audit 不通过。
- formal candidate row 为 0 或大量用户无候选。
- Recall@K 很弱且无互补性证据。
- 与 popular overlap 未经全局 route gate 评估。
- 只完成 smoke，没有 formal。
- 使用了旧 full-data artifact 或 eval label 构建候选。

本轮结论：formal 50k 显示 category coverage 强、Recall 弱，因此可作为 recent-2y train-only category source artifact；是否进入 pool500 主路留给全局 route gate。
