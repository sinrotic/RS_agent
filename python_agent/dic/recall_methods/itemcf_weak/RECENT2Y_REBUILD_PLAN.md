# itemcf_weak recent-2y RALPLAN 执行计划

日期：2026-06-03
状态：pending approval for broader promotion；本窗口按 goal 授权继续执行单方法重建，但不自动晋升主路。

## 1. RALPLAN-DR 摘要

### 原则

1. **只用 train-visible 构建**：候选生成、边权、source index 不读取 valid/test/holdout/LOPO/oracle/eval label。
2. **smoke/formal 分层**：smoke 只验证程序和 schema；formal 才用于正式方法效果与晋升证据。
3. **弱召回要可控**：保留弱边以提升覆盖，同时用活跃用户惩罚、item 频次归一化、manifest stats 和 source overlap 控制噪声。
4. **配置必须反映事实**：旧 full-data/sidecar 只能写成 historical，不作为 current latest formal。
5. **单方法不自升主路**：READY/route gate 由全局主路收口决定；本窗口只给候选证据和 blocker。

### 决策驱动

1. `itemcf_weak` 的方法价值是 medium/heavy 行为用户的宽覆盖补充。
2. recent-2y 数据基础已替换旧 full-data，必须重建 lineage 与 artifact manifest。
3. formal 大图可能重资源，执行必须可中断、可复核、资源受控。

### 备选方案

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 继续用旧 `build_itemcf_weak_method_source.py` 从 clean manifest 直接建候选 | 已有 candidates/coverage audit 输出 | 默认 clean_full，未显式使用 user_quality/item_quality governance；target first-N 用户不符合方法定制 | 不作为 formal 主方案，仅作历史/测试参考 |
| B. `method_dataset` -> `itemcf source adapter` 两段式 | 明确 train-only governance、method dataset contract、edge feature schema；可 sharding | source adapter 只生成 edge index，候选评估需另跑报告 | 采用 |
| C. formal 直接跑全量 coverage profile 并尝试升 READY | 覆盖最大 | 资源和噪声风险高，且缺少全局 route gate | 不采用；formal 可以跑，但 readiness 仍保守 |

## 2. 当前现状和缺口

已确认：

- `dic/recall_methods/POOL500_RECENT2Y_METHOD_REBUILD_GUIDE.md` 将 `itemcf_weak` 标为 `DIAGNOSTIC_ONLY`。
- `configs/recall/full_data_pool500/itemcf_weak/source_config.yaml` 已有 recent-2y schema，但 `source_status=FORMAL_PENDING`，`candidate_generation_allowed=false`。
- `configs/recall/pool500_method_registry.json` 中 `itemcf_weak.latest_artifact` 仍指向旧 `outputs/recall/pool500_sidecar_fix/...`。
- 旧 `METHOD.md` 仍包含 full-data/target500/2026-05-25 旧三档记录，需要改写为 recent-2y 当前事实。

缺口：

1. 缺少 `RECENT2Y_SCIOMC_RESEARCH.md`。
2. 缺少本计划文档。
3. 缺少 recent-2y smoke/formal method dataset 与 source index 的当前 manifest。
4. 缺少 formal 评估报告：coverage、候选数、用户桶、in-universe recall、source overlap。
5. 配置和 registry 未指向 current recent-2y artifact。

## 3. smoke dataset contract

- 输出根：`outputs/recall/pool500_method_datasets/recent_2y/collab_v1_smoke/`
- source method：`itemcf_weak`
- scale tier：`smoke`
- coverage profile：`strict`
- 输入：`data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json`
- 目的：`program_and_schema_validation_only`
- 权限：`promotion_allowed=false`、`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`
- 验证：manifest `status=PASS`，`forbidden_scope_audit.status=PASS`，`row_count` 与 `directed_edge_count_after_topk` 记录清楚。

命令：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.build_pool500_method_dataset \
  --governance-manifest data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json \
  --source-method itemcf_weak \
  --scale-tier smoke \
  --itemcf-coverage-profile strict \
  --output-root outputs/recall/pool500_method_datasets/recent_2y/collab_v1_smoke \
  --overwrite
```

## 4. formal dataset contract

- 输出根：`outputs/recall/pool500_method_datasets/recent_2y/collab_v1/`
- source method：`itemcf_weak`
- scale tier：`formal`
- coverage profile：先用 `strict` 口径（medium + collaborative_rich，cf_ready，非 over-hot）作为 current formal baseline；如果边数不足，再记录 blocker 而不是临时放宽。
- 目的：`official_method_logic_dataset_under_recent_2y_train_only_governance`
- 资源：formal 是 ItemCF 大图构建，若本地运行超过可控时间/内存，应停止并迁移 server；本地命令必须使用 `.venv`。

命令：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.build_pool500_method_dataset \
  --governance-manifest data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json \
  --source-method itemcf_weak \
  --scale-tier formal \
  --itemcf-coverage-profile strict \
  --output-root outputs/recall/pool500_method_datasets/recent_2y/collab_v1 \
  --overwrite
```

## 5. source artifact 构建步骤

### smoke source

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.pool500.method_dataset_to_itemcf_source \
  --source itemcf_weak \
  --method-dataset-manifest outputs/recall/pool500_method_datasets/recent_2y/collab_v1_smoke/itemcf_weak/method_dataset_manifest.json \
  --output-root outputs/recall/pool500_method_sources/recent_2y \
  --run-id smoke_strict_v1 \
  --overwrite
```

### formal source

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.pool500.method_dataset_to_itemcf_source \
  --source itemcf_weak \
  --method-dataset-manifest outputs/recall/pool500_method_datasets/recent_2y/collab_v1/itemcf_weak/method_dataset_manifest.json \
  --output-root outputs/recall/pool500_method_sources/recent_2y \
  --run-id formal_strict_v1 \
  --shard-count 8 \
  --overwrite
```

source manifest 必须保持：`source_status=DIAGNOSTIC_ONLY`、`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`。

## 6. 评估与验证计划

### 必跑验证

1. method dataset audit：
   - manifest status、forbidden_scope_audit、train_only、input hashes。
2. source adapter tests：
   - `tests/test_pool500_itemcf_method_dataset_source_adapter.py`
   - `tests/test_pool500_method_dataset.py`
3. source loader smoke：
   - `load_itemcf_source_manifest` 可读取 sharded source index。
4. formal report：
   - artifact scale；
   - seed/candidate item 覆盖；
   - candidate coverage；
   - Recall@50/@100/@500；
   - in-universe recall；
   - source overlap（如有可比 source manifest）。

命令候选：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_method_dataset.py tests/test_pool500_itemcf_method_dataset_source_adapter.py tests/test_pool500_itemcf_weak_method_source.py
```

如现有评估脚本无法直接消费单方法 source，则补一个轻量、只读、评估专用 report 脚本或直接用一次性 Python 片段生成 JSON 报告；评估 label 只读 valid/test，不写回 method dataset/source。

## 7. 需要更新的文件

- `dic/recall_methods/itemcf_weak/RECENT2Y_SCIOMC_RESEARCH.md`
- `dic/recall_methods/itemcf_weak/RECENT2Y_REBUILD_PLAN.md`
- `dic/recall_methods/itemcf_weak/METHOD.md`
- `configs/recall/full_data_pool500/itemcf_weak/dataset_policy.yaml`
- `configs/recall/full_data_pool500/itemcf_weak/source_config.yaml`
- `configs/recall/pool500_method_registry.json` 中 `itemcf_weak` 条目
- `dic/ENGINEERING_NARRATIVE_LOG.md`

## 8. 不允许做的事情

- 不把旧 full-data/sidecar artifact 写成 current latest formal。
- 不用 holdout/valid/test/LOPO/oracle/eval label 构建边、训练或生成候选。
- 不把 smoke 结果作为 formal 效果。
- 不在单方法窗口直接声称 final pool500 ready。
- 不允许 ranking input replacement。
- 不因 edge_count 大就自动升级 READY。

## 9. 完成条件与停止条件

### 单方法完成条件

1. SciOMC 调研文档存在且覆盖方法适配。
2. RALPLAN 计划文档存在。
3. smoke dataset/source 构建成功，并通过 manifest/gate 验证。
4. formal dataset/source 构建成功，manifest 记录完整 lineage。
5. 评估报告输出 Recall@K、coverage、用户桶或 blocker。
6. METHOD/source_config/dataset_policy/registry 已更新为 recent-2y 当前事实。
7. 工程叙事日志已追加简短记录。

### 停止条件

- formal 构建资源不可控且未迁移 server：保持 `FORMAL_PENDING` 或 `DIAGNOSTIC_ONLY`，写清 server 下一步。
- formal Recall@K、in-universe recall、coverage 或 source overlap 不足：保持 `DIAGNOSTIC_ONLY`，不晋升 READY。
- 发现任何 forbidden input 命中：停止构建，标记 BLOCKED，不能发布 current artifact。

## 10. 预期 readiness

本窗口默认预期：**完成 recent-2y artifact 和诊断评估，但保持 `DIAGNOSTIC_ONLY`**。只有当 formal 指标、互补性、资源成本和 route gate 证据充分时，才建议进入全局主路收口评审；是否真正进入主路由后续全局 route gate 决定。
