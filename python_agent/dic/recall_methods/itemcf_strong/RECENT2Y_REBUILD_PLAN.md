# itemcf_strong recent-2y RALPLAN 执行计划

日期：2026-06-03
状态：approved for execution by active goal

## RALPLAN-DR 摘要

### Principles

1. train-only 优先：构建数据集和 source artifact 只读取 recent-2y train-visible 输入。
2. strong 语义优先：高置信 ItemCF 宁可覆盖少，也不把 weak coverage 口径伪装成 strong。
3. smoke/formal 分层：smoke 验证程序与 schema，formal 才能作为效果证据。
4. evidence-first：所有结论必须落到 manifest、audit、metrics 或测试输出。
5. 不自动晋升：单方法完成不等于进入 pool500 主路，READY 需全局 route gate。

### Decision Drivers

1. 文献依据要求 item-item 表离线构建、线上按用户历史 seed 查询并合并，因此本轮必须形成可复核 source artifact，而不是只停在算法说明。
2. implicit feedback 文献强调未观测不等于负样本、训练与评估分离，因此 eval label 只能用于评估，不能反向参与强边筛选。
3. 数据泄漏和旧 artifact 回流风险必须降到最低。
4. formal strict 边数可能极低，需要接受 DIAGNOSTIC_ONLY 结果。
5. 本地资源有限，重任务需限流；当前 strict ItemCF 可先本地 `.venv` 验证。

### Viable Options

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. strict strong formal | 最符合 high-confidence 语义，泄漏和噪声风险最低 | 边数和覆盖可能极低 | 本轮主方案 |
| B. relaxed strong supplemental | 可提升 seed 命中和覆盖 | 容易与 weak 口径混淆，晋升风险高 | 仅作为后续优化，不作为本轮 READY 依据 |
| C. 复用旧 full-data relaxed v3 | 产物现成、覆盖较好 | 与 recent-2y 当前数据基础冲突 | 明确禁止 |

### ADR

- **Decision**：本轮 `itemcf_strong` 按 recent-2y strict strong 口径重建 smoke/formal method dataset，并从 formal dataset 构建 diagnostic source artifact；若 formal 效果不足，保持 `DIAGNOSTIC_ONLY`。
- **Drivers**：遵守 train-only governance、保留 strong 高置信语义、避免旧 artifact 回流、形成可复核 evidence。
- **Alternatives considered**：relaxed seed-src、旧 full-data artifact、直接晋升 READY。
- **Why chosen**：strict strong 是唯一同时满足当前 guide、强边语义和安全治理的方案。
- **Consequences**：产物可能 row_count 很小；完成标准侧重合规与 blocker 清晰，而不是强行达成主路贡献。
- **Follow-ups**：若需要覆盖，应另开 relaxed strong vs weak overlap/quality 对照，而不是在本轮混入。

## 1. 当前现状和缺口

- 现状：registry 中 `itemcf_strong.status=DIAGNOSTIC_ONLY`，当前 latest artifact 仍指向旧路径，需要替换或归档说明。
- 已有 recent-2y strict smoke/formal 历史产物，但不在 guide 建议的标准路径下，且 formal 仅 22 条方向边。
- 缺口：标准路径 smoke/formal、source artifact、audit report、offline eval / route evidence、文档和配置一致性。

## 2. smoke dataset contract

- 路径：`outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong/smoke/itemcf_strong/`
- 输入：`data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json`
- 命令：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.build_pool500_method_dataset \
  --governance-manifest data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json \
  --source-method itemcf_strong \
  --scale-tier smoke \
  --output-root outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong/smoke \
  --overwrite
```

- 完成条件：manifest `status=PASS`、`train_only=true`、`forbidden_scope_audit.status=PASS`、guardrail flags 全为 false。

## 3. formal dataset contract

- 路径：`outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong/formal/itemcf_strong/`
- strict policy：`collaborative_rich` 用户、`cf_ready + non-over_hot` item、`min_pair_support=2`、formal 不写死小 cap。
- 命令：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.build_pool500_method_dataset \
  --governance-manifest data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json \
  --source-method itemcf_strong \
  --scale-tier formal \
  --output-root outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong/formal \
  --overwrite
```

- 完成条件：manifest 记录 lineage/hash/drop reasons；如 row_count 很低，作为 blocker，而不是放宽口径硬晋升。

## 4. source artifact 构建步骤

- 输入：formal `method_dataset_manifest.json`。
- 输出：`outputs/recall/pool500_method_sources_newdata/itemcf_strong/formal_strict_from_recent2y/source_index_manifest.json`
- 命令：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.pool500.method_dataset_to_itemcf_source \
  --source itemcf_strong \
  --method-dataset-manifest outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong/formal/itemcf_strong/method_dataset_manifest.json \
  --output-root outputs/recall/pool500_method_sources_newdata/itemcf_strong \
  --run-id formal_strict_from_recent2y \
  --shard-count 1 \
  --overwrite
```

## 5. 资源控制策略

- 本地命令必须使用 `.venv/Scripts/python.exe`。
- strict smoke/formal 预计轻量，可本地执行。
- 若后续改跑 relaxed/full graph/sharded high-cardinality variant，应迁移 server 远程并带资源监控。
- source artifact 保持 diagnostic boundary，不允许 ranking replacement。

## 6. 验证命令与预期指标

1. method dataset audit：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.validate_pool500_method_dataset_audit_evidence \
  --governance-manifest data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json \
  --method-dataset outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong/smoke/itemcf_strong/method_dataset_manifest.json \
  --method-dataset outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong/formal/itemcf_strong/method_dataset_manifest.json \
  --output outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong/audit_evidence.json
```

2. route smoke：用 current source manifest override 跑 100 用户候选生成，检查 source contribution、resource audit 和 route gate。
3. offline eval dry-run：在固定 eval manifest 前 100 用户上计算 Recall/HitRate，只作为 sanity check。
4. unit tests：`tests/test_pool500_method_dataset.py`、`tests/test_pool500_method_registry_drift.py`。

## 7. 需要更新的文件

- `dic/recall_methods/itemcf_strong/RECENT2Y_SCIOMC_RESEARCH.md`
- `dic/recall_methods/itemcf_strong/RECENT2Y_REBUILD_PLAN.md`
- `dic/recall_methods/itemcf_strong/METHOD.md`
- `configs/recall/full_data_pool500/itemcf_strong/source_config.yaml`
- `configs/recall/full_data_pool500/itemcf_strong/dataset_policy.yaml`
- `configs/recall/pool500_method_registry.json`
- `dic/ENGINEERING_NARRATIVE_LOG.md`

## 8. 不允许做的事情

- 不用旧 full-data artifact 作为当前效果结论。
- 不读取 holdout/valid/test/LOPO/oracle/eval label 作为构建或训练输入。
- 不把 smoke 指标作为 formal 效果。
- 不声明 ranking input replacement、pool1000 或 final pool500 ready。
- 不因 formal 边少而临时改成 weak 口径。

## 9. 完成条件和停止条件

### 单方法完成条件

- SciOMC 调研与 RALPLAN 计划已落盘。
- smoke/formal method dataset 已在标准路径构建并审计通过。
- source artifact 已构建并记录 manifest。
- route/eval 至少完成小规模 sanity evidence。
- 文档和配置更新为 recent-2y 当前事实。
- 明确 readiness 与是否建议晋升。

### 停止条件

如果 formal row_count、Recall@K、coverage、overlap 或 route gate 证据不足，则保持 `DIAGNOSTIC_ONLY`，记录 blocker：`strict_high_confidence_recent2y_edges_too_sparse_for_ready_promotion`，下一步转 relaxed strong supplemental 对照实验。
