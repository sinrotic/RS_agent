# usercf_recall recent-2y RALPLAN 执行计划

日期：2026-06-03

状态：pending execution / 单方法窗口执行计划

## 1. 原则

1. **train-only 优先**：构建 method dataset、source index 和候选时只读取 recent-2y train-visible 输入，不读取 holdout/valid/test/LOPO/eval label/oracle。
2. **smoke/formal 分层**：smoke 只验证程序、schema、路径和 no-holdout gate；formal 才能作为方法效果和 route gate 判断依据。
3. **不复用旧结论**：旧 full-data、heavy28、`usercf_v1_formal_route_ready` 等产物只能作为历史参考，不作为本轮 current artifact 或晋升证据。
4. **UserCF 方法特化**：只面向 `heavy_cf_eligible` / `collaborative_rich` 用户构建可靠邻居，不强行覆盖 cold/fallback 用户。
5. **证据不足不晋升**：formal 跑通不等于 READY；如果 Recall、覆盖、互补性、资源成本或 route gate 证据不足，保持 `DIAGNOSTIC_ONLY` 并写清 blocker。

## 2. 决策驱动

1. **治理一致性**：`METHOD.md`、`dataset_policy.yaml`、`source_config.yaml`、registry 和 manifest 必须指向同一套 recent-2y 产物。
2. **可复核 source artifact**：必须产生 `source_index_manifest.json`、`readiness_contract.json`、`coverage_audit.json`、`undercoverage_audit.json`、`resource_audit.json`、`no_holdout_audit.json`。
3. **资源可控**：UserCF formal 是大图/邻居构建任务，必须分批、shard、内存 guard；如超出本地安全范围，转 server 运行并拉回证据。

## 3. 可选方案与取舍

### 方案 A：只修配置，复用旧 `usercf_v1_formal_route_ready`

- 优点：最快。
- 缺点：违反 recent-2y 重建目标；旧 route-ready 命名容易误晋升；无法证明 train-only recent-2y 当前效果。
- 结论：放弃。

### 方案 B：复用已存在 recent-2y smoke/formal method dataset，重新构建 source artifact

- 优点：已有 method dataset manifest 记录 train-only lineage、input hash、过滤规则和 dropped reason；能直接补齐 source artifact、评估和配置一致性。
- 缺点：formal source 构建仍需资源控制；如果 formal 评估不足，不能晋升。
- 结论：采用。

### 方案 C：从 governance 重新生成 method dataset，再构建 source artifact

- 优点：从最上游完全复跑，证据最完整。
- 缺点：当前 smoke/formal method dataset 已存在且 manifest 完整，重复重建会增加耗时和产物漂移风险。
- 结论：作为 fallback；仅当现有 manifest 校验失败或路径缺失时执行。

## 4. 已确认输入

- governance manifest：`data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json`，状态 `PASS`。
- smoke method dataset：`outputs/recall/pool500_method_datasets/recent_2y/usercf_sciomc_v1/smoke/usercf_method_dataset/method_dataset_manifest.json`
  - `row_count=995`，`user_count=995`，`item_count=1364`
- formal method dataset：`outputs/recall/pool500_method_datasets/recent_2y/usercf_sciomc_v1/formal/usercf_method_dataset/method_dataset_manifest.json`
  - `row_count=15884`，`user_count=15884`，`item_count=19595`
- source builder：`rs_lab/experiments/recall/pool500/methods/usercf_recall/builder.py`
- loader/test：`rs_core/recsys/candidate_merge.py`、`tests/test_pool500_usercf_method_source.py`

## 5. 执行步骤

### Step 1：固化调研与计划文档

- 写入 `dic/recall_methods/usercf_recall/RECENT2Y_SCIOMC_RESEARCH.md`。
- 写入本文件 `dic/recall_methods/usercf_recall/RECENT2Y_REBUILD_PLAN.md`。

### Step 2：修正 source config 的 current input

将 `configs/recall/full_data_pool500/usercf_recall/source_config.yaml` 对齐到：

- `output_root: outputs/recall/pool500_method_sources/recent_2y`
- `run_id: usercf_recent_2y_sciomc_formal_v1`
- `method_dataset_manifest: outputs/recall/pool500_method_datasets/recent_2y/usercf_sciomc_v1/formal/usercf_method_dataset/method_dataset_manifest.json`
- `source_index_manifest: outputs/recall/pool500_method_sources/recent_2y/usercf_recall/usercf_recent_2y_sciomc_formal_v1/source_index_manifest.json`
- `readiness_contract: outputs/recall/pool500_method_sources/recent_2y/usercf_recall/usercf_recent_2y_sciomc_formal_v1/readiness_contract.json`
- 保持 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`、`pool1000_allowed=false`。

说明：当前 builder 要求 `max_items_per_user`、`max_item_user_freq`、`similar_users_top_k` 为正数，因此 formal 配置使用已在 method dataset manifest 中记录的工程值：`max_items_per_user=80`、`max_item_user_freq=5000`、`similar_users_top_k=200`。

### Step 3：本地 smoke source 构建

使用项目默认 `.venv`：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.pool500.methods.usercf_recall.builder \
  --method-dataset-manifest outputs/recall/pool500_method_datasets/recent_2y/usercf_sciomc_v1/smoke/usercf_method_dataset/method_dataset_manifest.json \
  --output-root outputs/recall/pool500_method_sources/recent_2y_smoke \
  --run-id usercf_recent_2y_sciomc_smoke_v1 \
  --source-config configs/recall/full_data_pool500/usercf_recall/source_config.yaml \
  --dataset-policy configs/recall/full_data_pool500/usercf_recall/dataset_policy.yaml \
  --target-user-limit 0 \
  --candidate-top-k-per-user 100 \
  --generation-usercf-per-user 100 \
  --similar-users-top-k 50 \
  --target-batch-size 200 \
  --overwrite
```

验收：source manifest 可加载，candidate 非零或 undercoverage reason 完整，no-holdout audit PASS。

### Step 4：formal source 构建

优先按资源控制运行；若本地内存/耗时不可控，迁移到 server。可先本地启动：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.pool500.methods.usercf_recall.builder \
  --method-dataset-manifest outputs/recall/pool500_method_datasets/recent_2y/usercf_sciomc_v1/formal/usercf_method_dataset/method_dataset_manifest.json \
  --output-root outputs/recall/pool500_method_sources/recent_2y \
  --run-id usercf_recent_2y_sciomc_formal_v1 \
  --source-config configs/recall/full_data_pool500/usercf_recall/source_config.yaml \
  --dataset-policy configs/recall/full_data_pool500/usercf_recall/dataset_policy.yaml \
  --target-user-limit 0 \
  --candidate-top-k-per-user 500 \
  --generation-usercf-per-user 500 \
  --similar-users-top-k 200 \
  --target-batch-size 2000 \
  --overwrite
```

资源门禁：

- `max_rss_mb=4096`，如实际峰值接近上限或触发 guard，停止本地 formal，转 server。
- 使用 shard/checkpoint 输出；失败时用 `--resume` 继续，而不是删除重跑。
- 不加 `--route-ready`，除非 formal 评估和全局 route gate 后单独批准。

### Step 5：评估与审计

至少复核：

- `source_index_manifest.json`
- `readiness_contract.json`
- `coverage_audit.json`
- `undercoverage_audit.json`
- `resource_audit.json`
- `no_holdout_audit.json`
- `candidates.jsonl`

必要指标：

- target_user_count、candidate_user_count、candidate_total_count、candidate_count_stats。
- underfilled_user_coverage / undercoverage reason。
- peak_rss_mb、runtime_seconds。
- no-holdout audit 的 forbidden scope 标志全部为 false。

如有可用 recall-only 评估入口，再运行正式 Recall@K / source overlap / 用户桶分层评估；若没有本窗口可复用评估入口，则文档中把“缺少 route gate / overlap / Recall@K 评估”列为不晋升 blocker。

### Step 6：更新文档与配置

更新：

- `dic/recall_methods/usercf_recall/METHOD.md`
- `configs/recall/full_data_pool500/usercf_recall/source_config.yaml`
- `configs/recall/full_data_pool500/usercf_recall/dataset_policy.yaml`
- `configs/recall/pool500_method_registry.json` 的 `usercf_recall` 条目
- 如产生重要工程结论，追加 `dic/ENGINEERING_NARRATIVE_LOG.md`

### Step 7：验证

建议命令：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_usercf_method_source.py -q
```

再用轻量脚本检查 manifest 路径存在、governance 开关为 false、no-holdout audit PASS、registry/source_config/dataset_policy 指向一致。

## 6. 完成条件

单方法完成需要同时满足：

1. SciOMC 调研文档已存在。
2. RALPLAN 执行计划已存在。
3. smoke method dataset 和 smoke source artifact 可复核。
4. formal method dataset 和 formal source artifact 可复核，或 formal 因资源/指标明确停止并写清 blocker。
5. 文档和配置已更新到 recent-2y 当前事实。
6. 测试和 manifest 校验通过。
7. 明确 readiness：默认保持 `DIAGNOSTIC_ONLY`；只有证据充分才建议进入后续全局 route gate。

## 7. 停止条件

遇到以下情况不得硬并主路：

- formal 构建资源超限且未完成 server 回传证据。
- source candidate coverage 或 Recall@K 证据不足。
- source overlap 高、边际新增候选低，无法证明互补性。
- no-holdout audit 或 forbidden input 校验失败。
- 文档/配置/registry 路径无法对齐。
- 只跑通 smoke，没有 formal 证据。

## 8. ADR

- **Decision**：采用“复用 recent-2y `usercf_sciomc_v1` smoke/formal method dataset，重新构建 source artifact，并保持 DIAGNOSTIC_ONLY 直到 formal/route gate 证据充分”的方案。
- **Drivers**：train-only 合规、产物可复核、资源可控、避免旧 artifact 回流。
- **Alternatives**：复用旧 route-ready artifact（放弃）；完全重建 method dataset（作为 fallback）。
- **Consequences**：本窗口可以交付单方法 recent-2y 当前事实，但不自动并入 pool500 主路；主路并入留给全局 route gate。
- **Follow-ups**：如果 formal 指标显示 UserCF 对 heavy 用户有边际价值，再做 source overlap / route gate / supplemental ready 晋升评审。
