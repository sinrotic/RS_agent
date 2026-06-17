# co_visit_fallback_repair recent-2y 重建 RALPLAN

日期：2026-06-03  
状态：pending approval for promotion；执行层面允许继续 smoke / preflight / 文档收口；不允许 READY 晋升。

## RALPLAN-DR Summary

### Principles

1. **train-only 优先**：候选生成和 source index 构建只读 recent-2y train-visible 输入。
2. **修复定位优先**：`co_visit_fallback_repair` 是缺口补洞 source，不冒充主力召回。
3. **证据分层**：smoke 验证程序与 schema；formal 才能作为效果和 route gate 依据。
4. **不夸大算法语义**：当前 v0 是 `train_transition_metadata_repair_v0`，不是完整 co-visit graph。
5. **资源受控**：formal 全量构建必须先 preflight，必要时远程或分片执行。

### Decision Drivers

1. formal target users 达 1,558,964，本地直接构建可能产生亿级候选行与高内存压力。
2. 旧 full-data artifact 仍在 registry 中残留，必须防止被当作 current conclusion。
3. 当前 builder 已能生成七件套，但尚未具备 formal 可恢复分片与完整 route gate 评估证据。

### Viable Options

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 直接把 v0 晋升 READY | 快速进入主路 | 缺 formal 互补性、route gate、完整 co-visit graph 证据；高泄漏/误报风险 | 否决 |
| B. 完成 smoke + formal dry-run/preflight，保持 diagnostic/deferred | 符合治理；可沉淀可复核证据；避免硬并 | 暂不能进入主路 | 采用 |
| C. 立即本地 full formal 构建 | 有机会拿 formal source artifact | 约 155.9 万用户，builder 内存累积 rows/per_user，本地风险过高 | 暂缓 |
| D. 先改造成 shard writer 再远程 formal | 最稳妥，可恢复、可审计 | 需要额外开发与远程资源 | 下一步 |

## ADR

**Decision**：本轮将 `co_visit_fallback_repair` 收口为 recent-2y train-only diagnostic repair source：完成 SciOMC 论文/实践调研、smoke/formal method dataset manifest、smoke source artifact 七件套、formal dry-run contract、评估/资源 blocker 文档与配置更新；不晋升 READY。

**Drivers**：

- 当前算法不等于完整 co-visit graph。
- smoke 不能作为正式效果依据。
- formal 全量构建资源风险高，需要 remote/sharded execution。
- pool500 主路并入需要 source overlap、coverage、Recall@K、用户桶分层和 route gate 证据。

**Alternatives considered**：

- 直接 READY：证据不足，否决。
- 只写调研不构建：不满足方法窗口交付，否决。
- 本地 full formal：资源风险高，暂缓。

**Consequences**：

- registry 与 config 必须明确旧 artifact archived/current artifact diagnostic。
- candidate_generation_allowed / promotion_allowed / ranking_input_replacement_allowed 维持 false。
- 后续可基于本次 smoke 和 preflight 继续开发 shard formal builder。

**Follow-ups**：

1. 将 builder 改造成 candidates 分片写入、per-user audit 分片聚合、checkpoint 可恢复。
2. 在远程服务器运行 formal diagnostic/local_formal 构建。
3. 拉回 manifest、stats、评估报告和必要 artifact 本地复核。
4. 补 route gate：source overlap、underfilled repair delta、Recall@K、用户桶分层。

## 当前现状与缺口

### 已具备

- recent-2y train-only governance manifest：`data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json`，状态 PASS。
- smoke dataset manifest：`outputs/recall/pool500_method_sources_newdata/co_visit_recent2y_smoke_dataset_v1/manifest.json`。
- formal dataset manifest：`outputs/recall/pool500_method_sources_newdata/co_visit_recent2y_formal_dataset_v1/manifest.json`。
- train-only source manifest：`outputs/recall/pool500_method_sources_newdata/co_visit_recent2y_train_only_source_v1/manifest.json`。
- runner 接入：`scripts/experiments/recall/pool500/run_pool500_method_source.py --source co_visit_fallback_repair`。
- builder 接入：`rs_lab/experiments/recall/pool500/methods/co_visit_fallback_repair/builder.py`。

### 缺口

- formal source artifact 未构建。
- formal Recall@K / overlap / route gate 评估证据不足。
- builder 当前内存累积 rows/per_user，formal 全量需要分片或远程资源。
- registry 旧 `latest_artifact` 仍需替换为 recent-2y diagnostic 证据路径。

## smoke dataset contract

- role：program_and_schema_validation_only。
- target users：10,000。
- buckets：fallback_only 5,542；medium_behavior 90；sequence_sufficient 4,052；collaborative_rich 316。
- required outputs：七件套。
- promotion_allowed：false。
- ranking_input_replacement_allowed：false。
- complete_co_visit_graph_claimed：false。

## formal dataset contract

- role：official_method_logic_dataset_under_recent_2y_train_only_governance。
- target users：1,558,964。
- buckets：fallback_only 871,817；medium_behavior 90；sequence_sufficient 637,338；collaborative_rich 49,719。
- input_scope：recent-2y train-only governance + train split only。
- 构建策略：禁止方法侧无解释小 cap；如分片，仅作为资源执行方式，不改变 formal 口径。

## 执行步骤

1. **数据 manifest 重建**  
   命令：
   ```bash
   D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/recall/build_co_visit_recent2y_dataset_manifests.py
   ```
   预期：输出 train-only source、smoke/formal dataset manifest 和 newdata config。

2. **smoke dry-run**  
   命令：
   ```bash
   D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source co_visit_fallback_repair --config configs/recall/full_data_pool500/co_visit_fallback_repair/source_config_newdata_smoke.yaml --tier smoke --dry-run
   ```
   预期：输出七件套 contract；不写 artifact。

3. **smoke source artifact 构建**  
   命令：
   ```bash
   D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source co_visit_fallback_repair --config configs/recall/full_data_pool500/co_visit_fallback_repair/source_config_newdata_smoke.yaml --tier smoke --run-id co_visit_recent2y_smoke_20260603_verified --overwrite
   ```
   预期：写出七件套，no_holdout_audit PASS，candidate_row_count 非零。

4. **formal diagnostic dry-run**  
   命令：
   ```bash
   D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source co_visit_fallback_repair --config configs/recall/full_data_pool500/co_visit_fallback_repair/source_config_newdata_formal.yaml --tier diagnostic --dry-run
   ```
   预期：contract 指向 formal eligible user manifest；不写 artifact。

5. **formal preflight / 停止门禁**  
   如果 builder 未改造成分片/可恢复，且没有远程服务器执行授权与资源计划，则不在本地 full formal。

6. **文档与配置更新**  
   更新 `METHOD.md`、`dataset_policy.yaml`、`source_config.yaml`、registry 和工程叙事日志。

## 验证命令

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_co_visit_fallback_repair_source.py tests/test_pool500_method_source_runner.py -q
```

可选 registry 相关回归：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_recall_source_registry.py tests/test_full_data_pool500_recall_only.py -q
```

## 不允许做的事情

- 不使用 holdout/valid/test/LOPO/oracle/eval label 构建候选或筛边。
- 不把旧 full-data artifact 当作 current recent-2y 结论。
- 不把 smoke 结果写成正式效果。
- 不宣称完整 co-visit graph。
- 不允许 ranking input replacement。
- 不进入 pool1000。
- 不在本地盲跑 formal 亿级候选构建。

## 完成条件

本轮窗口可完成为“diagnostic/deferred with blocker”需要满足：

- SciOMC 调研文档存在。
- RALPLAN 计划文档存在。
- smoke/formal dataset manifest 存在且 lineage train-only。
- smoke source artifact 七件套可复核。
- formal dry-run contract 可复核。
- evaluation/preflight report 写清 formal blocker。
- METHOD/config/registry 更新为 recent-2y 当前事实。
- 回归测试通过或失败原因明确。

## 停止条件

若 formal 全量 source artifact、Recall@K、互补性或 route gate 证据不足，则保持 `DEFERRED` / `TARGET_SLICE_DIAGNOSTIC`，不晋升 READY。当前即采用该停止条件。
