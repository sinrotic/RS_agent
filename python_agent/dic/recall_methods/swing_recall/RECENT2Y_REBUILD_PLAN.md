# swing_recall recent-2y 重建 RALPLAN 执行计划

## ADR

**Decision：**
采用“recent-2y train-only SciOMC 预处理 + smoke/formal method dataset + formal full-train Swing sidecar + raw source eval + guarded readiness”的路线。`swing_recall` 可保留为 formal evidence ready 的行为协同 source，但本单方法窗口不直接开启主路 candidate generation、ranking replacement、pool1000 或 promotion。

**Drivers：**
1. 数据基础已切换到 `recent_2y_1m_3m`，旧 full-data artifact 不能作为当前结论。
2. Swing 的方法价值来自 train 行为共现图，必须控制热门 item、高活跃用户和低 support 噪声边。
3. 单方法 raw eval 不能证明 route-level marginal lift，主路并入必须留给全局 route gate。

**Alternatives considered：**
- 直接复用旧 `pool500_sidecar_fix/swing_recall_v2`：拒绝。旧 artifact 只能历史参考，不能代表 recent-2y。
- 只跑 smoke：拒绝。smoke 只能验证程序和 schema，不能作为 formal 效果依据。
- formal 后直接开启 `candidate_generation_allowed=true`：拒绝。缺少 source overlap、route gate 和边际贡献证据。

**Consequences：**
- 产出 recent-2y formal source artifact 和评估报告。
- 配置中可以把 `swing_recall` 表达为 `READY_GUARDED` / registry `READY`，但权限位仍保持 false。
- 下一步由全局 pool500 主路收口决定是否启用该 source。

## 1. 当前现状与缺口

- 旧 `METHOD.md` 和 registry 仍混有旧 sidecar 路径。
- `source_config.yaml` 已有 recent-2y v2 结构，但 `source_status=FORMAL_PENDING`。
- recent-2y 预处理脚本与 full-train sidecar 构建脚本已存在，测试覆盖 train-only 与 forbidden input。
- 缺口：需要正式跑出 smoke/formal method dataset、formal source artifact、raw eval，并把文档配置同步为当前事实。

## 2. smoke dataset contract

- 路径：`outputs/recall/pool500_method_datasets/recent_2y/swing_recall/smoke/swing_method_dataset/method_dataset_manifest.json`
- 输入：recent-2y train-only governance。
- 规模：`max_graph_users=2000`、`max_items_per_user=50`、`max_item_user_freq=1000`、`min_pair_support=1`。
- 作用：验证 schema、路径、forbidden scope audit、最小 pair support 是否非零。
- 禁止：不用于 formal 效果结论，不用于 promotion。

## 3. formal dataset contract

- 路径：`outputs/recall/pool500_method_datasets/recent_2y/swing_recall/formal/swing_method_dataset/method_dataset_manifest.json`
- 输入：recent-2y train-only governance。
- 规模：不使用固定小 cap，`min_pair_support=2`，eligible users 为 `medium_behavior + collaborative_rich`，item 侧使用 `cf_ready` 并剔除 over-hot。
- 输出：`method_dataset_rows.jsonl` 与 `method_dataset_manifest.json`。
- 作用：作为方法数据治理证据；source artifact 仍以 formal train sequence 构图为准。

## 4. source artifact 构建步骤

1. 复核/重建 SciOMC recent-2y 预处理：
   ```bash
   D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe rs_lab/experiments/recall/build_sciomc_swing_recent2y_preprocess.py --overwrite
   ```
2. 构建 smoke source：
   ```bash
   D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe rs_lab/experiments/recall/build_full_train_swing_sidecar.py \
     --clean-manifest data/processed/amazon_2023_sciomc_swing_recent2y/smoke/swing_builder_train_manifest.json \
     --output-dir outputs/recall/pool500_method_sources/recent_2y/swing_recall/smoke/run_20260603_smoke_train_only_v1 \
     --max-item-user-freq 1000 --max-user-items 50 --min-pair-support 1 --per-seed-top-k 40 --min-free-bytes 0
   ```
3. 构建 formal source：
   ```bash
   D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe rs_lab/experiments/recall/build_full_train_swing_sidecar.py \
     --clean-manifest data/processed/amazon_2023_sciomc_swing_recent2y/formal/swing_builder_train_manifest.json \
     --output-dir outputs/recall/pool500_method_sources/recent_2y/swing_recall/formal/run_20260603_formal_train_only_v1 \
     --max-item-user-freq 100 --max-user-items 50 --min-pair-support 2 --per-seed-top-k 100 --min-free-bytes 0
   ```

## 5. 资源控制策略

- 本地仅执行可控的 source sidecar 构建和 raw eval；全局 route gate 或更大规模并入实验若耗时/耗内存，应迁移 server。
- formal 构图控制项：`max_user_items=50`、`max_item_user_freq=100`、`min_pair_support=2`、`per_seed_top_k=100`。
- 输出必须包含 `resource_audit.json`、`no_holdout_audit.json`、`source_index_manifest.json`。

## 6. 验证命令与指标

测试：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_sciomc_swing_recent2y_preprocess.py tests/test_full_train_swing_sidecar.py tests/test_pool500_swing_recall_enhanced_source.py -q
```

formal raw eval 报告：

- `outputs/recall/pool500_method_sources/recent_2y/swing_recall/formal/run_20260603_formal_train_only_v1/eval/swing_recent2y_formal_eval_report.json`

预期验证项：

- source artifact `status=PASS`。
- no-holdout audit `valid_test_holdout_usage=not_read`。
- formal source 有非零 `edge_count` 与 `seed_count`。
- eval 报告给出 Recall@K、HitRate@K、candidate coverage、用户桶分层。

## 7. 需要更新的文件

- `dic/recall_methods/swing_recall/RECENT2Y_SCIOMC_RESEARCH.md`
- `dic/recall_methods/swing_recall/RECENT2Y_REBUILD_PLAN.md`
- `dic/recall_methods/swing_recall/METHOD.md`
- `configs/recall/full_data_pool500/swing_recall/source_config.yaml`
- `configs/recall/full_data_pool500/swing_recall/dataset_policy.yaml`
- `configs/recall/pool500_method_registry.json`
- `dic/ENGINEERING_NARRATIVE_LOG.md`

## 8. 不允许做的事情

- 不得用旧 full-data artifact 作为当前结论。
- 不得把 valid/test/holdout/LOPO/oracle/eval label 作为构图或候选生成输入。
- 不得用 smoke 指标声明 formal ready。
- 不得在本单方法窗口开启 ranking input replacement 或 pool1000。
- 不得绕过全局 route gate 直接声明 pool500 主路合入完成。

## 9. 完成条件与停止条件

**完成条件：**

- smoke/formal method dataset PASS。
- smoke/formal source artifact PASS。
- formal raw eval 报告 PASS。
- 文档与配置同步到 recent-2y 当前事实。
- 明确 readiness 与主路 blocker。

**停止条件：**

- no-holdout audit 失败。
- formal source edge/candidate 覆盖为零。
- route gate / overlap / marginal lift 证据不足时，不开启主路权限位，只保留 `READY_GUARDED` 或 diagnostic blocker。

## 10. 当前执行结论

本轮已完成 smoke/formal 数据、formal source artifact、raw eval 与 baseline funnel diagnostic。formal source：`edge_count=237681`、`seed_count=46788`；valid `HitRate@500=0.002295`、test `HitRate@500=0.000508`。该结果说明 Swing 对 medium/collaborative 用户有补充价值，但整体 raw hit 很低，且缺少 route-level overlap / marginal lift，因此保持 guarded，不直接并入主路。

新增漏斗诊断脚本：`rs_lab/experiments/recall/diagnose_swing_recent2y_funnel.py`；报告：`outputs/recall/pool500_method_sources/recent_2y/swing_recall/formal/run_20260603_formal_train_only_v1/eval/swing_recent2y_funnel_diagnostic.json`。诊断显示 test `missing_train_sequence_users=115624`、`generated_candidate_user_count=3973`、`users_without_graph_seed_but_hot_dropped_seed=3806`。因此下一阶段的优先实验不是修改 recent-2y 预处理，而是受控 sweep `max_item_user_freq=300/600/1000`，并评估 hot-aware seed/target 策略与 eligible-user route。