# Popular recent-2y 重建 RALPLAN

日期：2026-06-03
状态：approved-for-current-goal-execution（用户 goal 已授权执行）

## RALPLAN-DR 摘要

### Principles

1. **Train-only 优先**：source 构建只读取 recent-2y train-only governance 输入。
2. **轻量可复核**：popular 不训练模型，不引入 GPU/ANN；通过 manifest、hash、audit 和 deterministic 排序保证可复核。
3. **Smoke/Formal 分离**：smoke 只验 schema/path/gate；formal 才用于正式效果和 readiness 证据。
4. **兜底不越权**：popular 可作为候选生成 fallback，但不允许 ranking replacement、pool1000 或自动 promotion。
5. **主路收口后置**：单方法窗口只给出并入建议和证据，最终 route gate 留给全局主路收口。

### Decision Drivers

1. 避免旧 full-data/sidecar artifact 回流。
2. 保证 valid/test label 只用于评估，不参与构建。
3. 控制 popular 对个性化 source 和长尾覆盖的挤占风险。

### Viable Options

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 基于 `item_frequency_train.jsonl` 构建全局热门 source | 最符合 train-only governance，轻量、可复核、无训练资源压力 | 个性化弱，长尾覆盖差 | 采用 |
| B. 复用旧 promoted/source sidecar 后做 governance transform | 现有 builder 可用 | 旧 artifact 路径容易回流，不满足 recent-2y 单方法重建目标 | 不采用 |
| C. 同时上短期/时间衰减/类目热门复杂融合 | 可能提高短期或类目覆盖 | 本轮证据不足，容易增加不可解释变量 | 暂不采用，留作后续对照 |

## ADR

### Decision

为 `popular` 新增/使用 recent-2y train-only 直接构建流程：从 `train_only_governance/item_frequency_train.jsonl` 生成 smoke/formal `method_dataset_manifest.json`、`candidates.jsonl`、`source_index_manifest.json` 和评估报告。

### Drivers

- `POOL500_RECENT2Y_METHOD_REBUILD_GUIDE.md` 要求旧 full-data artifact 只能参考。
- Popular 的方法归纳偏置是全局 train 热度，最适合从 `item_frequency_train.jsonl` 直接构建。
- 当前用户桶中 cold_start + fallback_only 占比高，popular fallback 仍有工程价值。

### Alternatives considered

- 继续使用 `pool500_sidecar_fix` 历史产物：拒绝，因为不能代表 recent-2y 重建结论。
- 直接复用 `recall_views/popular_recall.jsonl`：可参考，但该视图不是完整 smoke/formal method dataset/source manifest contract。
- 引入时间衰减热门：暂缓；先保留全局热门 baseline，后续用 formal 对照评估再决定。

### Consequences

- 构建资源低，本地 `.venv` 可完成，不需要远程 server。
- `popular` 的 formal 指标可能不高，但它的价值主要是 coverage/backfill，不应按个性化 source 标准强行比较。
- 若 route gate 要求 source overlap/主路 share，需要后续全局收口阶段补充跨 source 证据。

### Follow-ups

- 全局主路收口时，对 popular 设置 source budget 和 fill order cap。
- 如 popular share 过高，应优先补强非 popular sources，而不是提高 popular 权重。
- 后续可做 category-popular 或 recent-popularity challenger，但必须保持 train-only。

## 执行计划

### 1. 固化 dataset contract

- smoke 输出：`outputs/recall/pool500_method_datasets/recent_2y/popular/smoke/<run_id>/method_dataset_manifest.json`
- formal 输出：`outputs/recall/pool500_method_datasets/recent_2y/popular/formal/<run_id>/method_dataset_manifest.json`
- 共同输入：`train_only_governance/item_frequency_train.jsonl`
- smoke purpose：`program_and_schema_validation_only`
- formal purpose：`official_method_logic_dataset_under_recent_2y_train_only_governance`

### 2. 构建 source artifact

- 输出目录：`outputs/recall/pool500_method_sources/recent_2y/popular/<scale>/<run_id>/`
- 必需文件：
  - `source_index_manifest.json`
  - `candidates.jsonl`
  - `coverage_audit.json`
  - `undercoverage_audit.json`
  - `resource_audit.json`
  - `no_holdout_audit.json`
  - `evaluation_report.json`

### 3. 资源策略

- Popular 是非训练型轻量统计方法，formal 本地运行可接受。
- 本地命令必须使用：`D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe`。
- 不运行 GPU/ANN/embedding/大图训练。

### 4. 验证命令

- smoke 构建：
  `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.build_pool500_popular_recent2y --scale-tier smoke --overwrite`
- formal 构建：
  `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.build_pool500_popular_recent2y --scale-tier formal --overwrite`
- 配置/文档更新后，运行轻量检查：
  `D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_lightweight_source_governance.py -q`

### 5. 验收标准

1. smoke/formal method dataset manifest 均存在且 `train_only=true`。
2. source index manifest 指向 recent-2y 输出路径，不引用旧 full-data artifact。
3. no_holdout_audit PASS，构建输入不含 valid/test/holdout/LOPO/oracle/eval label。
4. formal evaluation report 给出 Recall@K、hit rate、覆盖、候选数、用户桶、train-universe 和长尾指标。
5. `candidate_generation_allowed=true` 仅表示该 source artifact 可作为候选源；`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`promotion_allowed=false`。
6. 更新 `METHOD.md`、`source_config.yaml`、`dataset_policy.yaml`、`pool500_method_registry.json`。

### 6. 停止条件

- 如果 formal manifest 缺失、no_holdout_audit BLOCKED 或 source artifact 仍引用旧 full-data 路径，则不得宣称完成。
- 如果 formal 指标/coverage 或 route gate 证据不足，则只保留 READY fallback / candidate-source 建议，不强行声明主路已并入。
