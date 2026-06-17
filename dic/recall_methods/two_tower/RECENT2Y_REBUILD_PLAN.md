# two_tower recent-2y 重建 RALPLAN 执行计划

日期：2026-06-02
状态：executed through bounded formal preflight / full remote formal source still blocked

## 1. RALPLAN-DR 摘要

### 原则

1. **train-only first**：训练、负采样、item universe、source index 只读 recent-2y train-visible 输入。
2. **smoke/formal 分层**：smoke 只验程序和 schema；formal 才能作为正式方法数据集与训练依据。
3. **source artifact 可审计**：模型、embedding、index、candidate source 必须有 manifest、hash、权限位和 no-holdout audit。
4. **不硬晋升**：缺少 formal Recall@K、覆盖、overlap、资源和 route gate 时保持 diagnostic/deferred。
5. **重资源远程**：formal 全量训练、ANN 构建和大规模评估优先 server 执行，本地只做 smoke/复核。

### 决策驱动

1. 防止旧 full-data artifact 回流。
2. 防止 valid/test/LOPO/oracle/eval label 泄漏到候选生成或训练输入。
3. 在资源可控前提下尽快拿到可复核的 two_tower recent-2y 证据链。

### 备选方案

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 直接沿用旧 `pool500_full_sources/two_tower` | 最快、已有训练产物 | 来自旧 full/full-clean 路径，不满足 current recent-2y 结论 | 否决 |
| B. 本地跑 full formal 训练 | 产物完整 | 训练/embedding/index 是重资源任务，违背优先 server 约束，可能打满本机 | 否决为默认路径 |
| C. 本地构建 smoke+formal dataset，本地跑 smoke source，formal 训练转 server | 满足治理、资源和证据分层；能先验证链路 | formal source/eval 需后续远程完成 | 采用 |

## 2. 当前现状和缺口

- registry 当前把 `two_tower` 标为 `DEFERRED`。
- 旧 METHOD 中存在 `MAIN_ROUTE_ARTIFACT_ONLY` 和 full-clean/full-data 路径，只能作为历史参考。
- recent-2y governance 已 PASS：`data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json`。
- 已有 SciOMC 预处理 manifest：`data/processed/amazon_2023_sciomc_twotower_recent2y/manifest.json`。
- 缺口：formal source artifact、formal Recall@K/overlap/route gate 仍未完成；不得晋升 READY。

## 3. smoke dataset contract

目标路径：

`outputs/recall/pool500_method_datasets/recent_2y/two_tower/smoke/method_dataset_manifest.json`

合同：

- scale tier：`smoke`。
- 输入：recent-2y manifest、train-only governance、`user_sequences.train.jsonl`、`canonical_items.jsonl`、`item_quality_profile.jsonl`、`item_frequency_train.jsonl`。
- 用户：默认 500 eligible users。
- 样本：`history_before_target_time -> target_item`，max 20000。
- 负采样：3 negatives/sample，来自 train-only embedding_ready universe，排除用户历史和 target。
- 输出：`two_tower_train_samples.jsonl`、`negative_item_universe.jsonl`、`training_item_universe.jsonl`、`leakage_audit.json`。
- 权限位：`candidate_generation_allowed=false`、`promotion_allowed=false`、`ranking_input_replacement_allowed=false`。

## 4. formal dataset contract

目标路径：

`outputs/recall/pool500_method_datasets/recent_2y/two_tower/formal/method_dataset_manifest.json`

合同：

- scale tier：`formal`。
- 不使用方法侧小 cap：`limit_users=0`、`max_samples=0`。
- 目标用户桶：`sequence_sufficient`、`collaborative_rich`、`medium_behavior`。
- 负采样：5 negatives/sample，记录负样本覆盖、top1/top10 集中度。
- training item universe：`negative_universe + sampled_train_sequence_targets`。
- 明确 eval/retrieval universe 仍需 source artifact 阶段冻结。

## 5. source artifact 构建步骤

### 本地 smoke

1. 用 SciOMC smoke 数据训练 YouTubeDNN 1 epoch。
2. 构建 smoke source index manifest。
3. 跑 20 用户 target-slice candidate check，验证 VectorIndex 可加载、查询能返回候选、no_holdout_audit PASS。

### formal / remote

formal source artifact 必须走 server：

1. 同步 recent-2y train-only 数据、formal method dataset、训练配置到 server。
2. 使用 train-only item vocab / training item universe 训练 YouTubeDNN。
3. 构建 item/user embeddings 与 recall index。
4. 拉回 `artifact_manifest.json`、`train_metrics.json`、`source_index_manifest.json`、必要 embedding/index artifact、评估报告。
5. 本地运行 manifest guard、source loader、direct eval、route gate 回归。

建议远程资源策略：

- batch size 从 4096/8192/16384 梯度累积试探。
- 1-3 epoch，记录 loss history 与 training seconds。
- progress log JSONL。
- 若训练时间、显存或磁盘超过预算，停止并保留 partial manifest，不声明 READY。

## 6. 验证命令

本地命令统一使用：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m ...
```

已执行/计划执行：

```bash
# smoke method dataset
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.build_pool500_two_tower_method_dataset \
  --clean-manifest data/processed/amazon_2023_recall_recent_2y_1m_3m/manifest.json \
  --governance-manifest data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json \
  --output-dir outputs/recall/pool500_method_datasets/recent_2y/two_tower/smoke \
  --scale-tier smoke --overwrite

# formal method dataset
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.build_pool500_two_tower_method_dataset \
  --clean-manifest data/processed/amazon_2023_recall_recent_2y_1m_3m/manifest.json \
  --governance-manifest data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json \
  --output-dir outputs/recall/pool500_method_datasets/recent_2y/two_tower/formal \
  --scale-tier formal --overwrite

# smoke training
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m scripts.training.train_two_tower \
  --config outputs/recall/pool500_method_sources/recent_2y/two_tower/smoke_training_config.yaml \
  --output-dir outputs/recall/pool500_method_sources/recent_2y/two_tower/smoke_training_run \
  --variant youtube_dnn --compact-inputs --epochs 1

# smoke source manifest
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m scripts.recall.build_two_tower_source_index \
  --training-run-dir outputs/recall/pool500_method_sources/recent_2y/two_tower/smoke_training_run \
  --item-vocab-manifest data/processed/amazon_2023_sciomc_twotower_recent2y/smoke/two_tower_item_vocab_minfreq1_manifest.json \
  --output-dir outputs/recall/pool500_method_sources/recent_2y/two_tower/smoke_source \
  --output-source-manifest outputs/recall/pool500_method_sources/recent_2y/two_tower/smoke_source/source_index_manifest.json \
  --config outputs/recall/pool500_method_sources/recent_2y/two_tower/smoke_training_config.yaml \
  --clean-manifest data/processed/amazon_2023_sciomc_twotower_recent2y/smoke/manifest.json \
  --train-sequence data/processed/amazon_2023_sciomc_twotower_recent2y/smoke/user_sequences.train.jsonl \
  --overwrite
```

后续测试：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest \
  tests/test_sciomc_twotower_recent2y_preprocess.py \
  tests/test_pool500_two_tower_method_dataset.py \
  tests/test_pool500_two_tower_method_source.py \
  tests/test_two_tower_source_manifest_guard.py \
  tests/test_pool500_method_registry_drift.py -q
```

## 7. 需要更新的文件

- `dic/recall_methods/two_tower/RECENT2Y_SCIOMC_RESEARCH.md`
- `dic/recall_methods/two_tower/RECENT2Y_REBUILD_PLAN.md`
- `dic/recall_methods/two_tower/METHOD.md`
- `configs/recall/full_data_pool500/two_tower/dataset_policy.yaml`
- `configs/recall/full_data_pool500/two_tower/source_config.yaml`
- `configs/recall/pool500_method_registry.json`
- `dic/ENGINEERING_NARRATIVE_LOG.md`

## 8. 不允许做的事情

- 不使用旧 full-data artifact 作为 current recent-2y 结论。
- 不把 valid/test/holdout/LOPO/oracle/eval label 用于训练、负采样、item vocab 或 source index。
- 不把 smoke 指标写成正式效果。
- 不在缺少 formal source/eval/overlap/route gate 前晋升 READY。
- 不允许 ranking input replacement，不允许 pool1000 自动晋升。

## 9. 完成条件 / 停止条件

### 单方法阶段性完成

- SciOMC research 完成。
- RALPLAN 计划完成。
- smoke/formal method dataset 均 PASS。
- smoke source artifact 与 candidate check PASS。
- METHOD/config/registry 更新为 current recent-2y 事实。
- 明确 formal source/eval blocker，不误宣称 READY。

### READY 晋升条件

仅当后续远程 formal source 训练完成，并通过：

- formal Recall@K / hit-rate。
- 用户桶分层。
- in-universe denominator。
- source overlap / 独有命中。
- route gate / regression tests。

才可从 `DEFERRED` 或 `DIAGNOSTIC_ONLY` 晋升为 READY。

## 10. ADR

**Decision**：采用“recent-2y train-only formal dataset + 本地 smoke source + 远程 formal source blocker”的路线。

**Drivers**：数据治理、资源控制、可复核证据链。

**Alternatives considered**：沿用旧 artifact、本地 full formal 训练、只做 smoke。旧 artifact 不合规；本地 full formal 训练资源风险高；只做 smoke 不能形成 formal dataset 证据。

**Why chosen**：该路线最大限度推进 two_tower 单方法重建，同时不突破 train-only 和重资源约束。

**Consequences**：本轮不宣称 two_tower READY，只给出 formal source 的明确远程执行下一步。

**Follow-ups**：server 远程训练、formal eval、source overlap、route gate，全局主路收口再决定是否并入 pool500。
