# co_visit_fallback_repair

更新日期：2026-06-08

## 当前结论

`co_visit_fallback_repair` 是 pool500 recent-2y 的 fallback repair / 缺口补洞 source。当前实现语义是：

- `algorithm_scope=train_transition_metadata_repair_v2`
- `complete_co_visit_graph_claimed=false`
- `source_status=FALLBACK_REPAIR_GUARDED_CANDIDATE`（任务型 readiness）
- registry readiness：`DEFERRED`（不是 final READY）
- task role：`underfill_fallback_repair_not_single_source_recall`

它使用 train-only 用户序列 transition 与静态 metadata neighbor 生成补充候选，不是完整 co-visit graph；本轮不再用单方法 HitRate/Recall 作为 primary gate，而是用 fallback / underfill completion 任务审计判断它是否能在主路中承担兜底修复。通过任务门禁时可作为主路 fallback repair source 接入；仍不替换 ranking input，不进入 pool1000，不声明 full pool500 ready。

## recent-2y 数据基础

当前正式数据基础：

`data/processed/amazon_2023_recall_recent_2y_1m_3m/`

时间窗：

- train：2021-06-15 到 2023-05-15
- valid：2023-05-15 到 2023-06-15
- test：2023-06-15 到 2023-09-14

候选生成只读 train-visible 输入：

- `canonical_interactions.train.jsonl`
- `user_sequences.train.jsonl`
- `canonical_items.jsonl`
- `recall_views/semantic_recall_inputs.jsonl`
- `train_only_governance/user_quality_profile.jsonl`

valid/test/holdout/LOPO/oracle/eval label 只允许在 evaluation-only 阶段计算指标，不得进入候选生成、构建、筛边或候选过滤。

## SciOMC 调研结论

调研文档：

`dic/recall_methods/co_visit_fallback_repair/RECENT2Y_SCIOMC_RESEARCH.md`

核心结论：

- Amazon item-to-item CF 说明 item co-occurrence / neighbor lookup 是高可扩展 candidate source，但本项目当前 v2 仍未构建完整 item-item co-visit graph。
- GRU4Rec / session-based recommendation 说明 recent sequence 对缺少长期画像的用户有价值，因此 train-only sequence transition 可作为 fallback repair 信号。
- SR-GNN 等 session graph 方法说明完整 session graph 需要显式边、边权、多步转移和 support audit；当前 v2 引入 support gate，但仍不能宣称完整 graph。
- 推荐评估可复现性研究提示：简单 neighbor / graph baseline 常是强基线，但必须有严格 train-only lineage、baseline 对照和 route gate。

## RALPLAN 执行计划

计划文档：

`dic/recall_methods/co_visit_fallback_repair/RECENT2Y_REBUILD_PLAN.md`

本轮决策：完成 smoke/formal dataset manifest、smoke source artifact、formal dry-run/preflight、配置和文档收口；formal 全量 source artifact 与 route gate 证据不足前，不晋升 READY。

## 统一 runner 与配置

- 默认 runner 配置：`configs/recall/full_data_pool500/co_visit_fallback_repair/source_config.yaml`
- recent2y smoke config：`configs/recall/full_data_pool500/co_visit_fallback_repair/source_config_newdata_smoke.yaml`
- recent2y formal config：`configs/recall/full_data_pool500/co_visit_fallback_repair/source_config_newdata_formal.yaml`
- recent2y formal shard50k server config：`configs/recall/full_data_pool500/co_visit_fallback_repair/source_config_newdata_formal_shard50k.yaml`
- formal server handoff：`dic/recall_methods/co_visit_fallback_repair/FORMAL_SERVER_HANDOFF.md`
- 统一入口：`scripts/experiments/recall/pool500/run_pool500_method_source.py`
- runner tier：`smoke`、`dam(diagnostic)`、`最终数据集(local_formal)`、`formal_shard50k`

边界再次固定：不得宣称 READY；不替换 ranking input；不进入 pool1000；`ranking_input_replacement_allowed=false`；`pool1000_allowed=false`。

## smoke 数据集

用途：本地轻量验证 schema、manifest、builder contract、七件套输出和 no-holdout audit，不代表正式效果。

- dataset class：`co_visit_recent2y_smoke_dataset_v1`
- manifest：`outputs/recall/pool500_method_sources_newdata/co_visit_recent2y_smoke_dataset_v1/manifest.json`
- eligible manifest：`outputs/recall/pool500_method_sources_newdata/co_visit_recent2y_smoke_dataset_v1/eligible_user_manifest.json`
- config：`configs/recall/full_data_pool500/co_visit_fallback_repair/source_config_newdata_smoke.yaml`
- target users：10,000
- selection policy：train-only governance 分桶抽样，资源验证用途，不是旧 full-data cap 延续

当前 smoke bucket counts：

- `fallback_only=5542`
- `medium_behavior=90`
- `sequence_sufficient=4052`
- `collaborative_rich=316`

已有 smoke diagnostic artifact：

`outputs/recall/pool500_method_sources_newdata/co_visit_fallback_repair/co_visit_recent2y_smoke_dataset_20260602/source_index_manifest.json`

关键 smoke 指标：

- candidate rows：398,326
- user coverage：10,000 / 10,000
- unique items：27,854
- sequence transition coverage：9,914 / 10,000
- no_holdout_audit：PASS
- undercovered users：271（仍为 diagnostic undercoverage）

注意：smoke 结果只证明链路和七件套可运行，不能作为 formal 效果或 READY 依据。

## formal 数据集

用途：正式 diagnostic / route-gate 证据，不自动晋升主路。

- dataset class：`co_visit_recent2y_formal_dataset_v1`
- manifest：`outputs/recall/pool500_method_sources_newdata/co_visit_recent2y_formal_dataset_v1/manifest.json`
- eligible manifest：`outputs/recall/pool500_method_sources_newdata/co_visit_recent2y_formal_dataset_v1/eligible_user_manifest.json`
- config：`configs/recall/full_data_pool500/co_visit_fallback_repair/source_config_newdata_formal.yaml`
- target users：1,558,964
- selection policy：`max_users=null`、`sample_count_caps=none`

当前 formal bucket counts：

- `fallback_only=871817`
- `medium_behavior=90`
- `sequence_sufficient=637338`
- `collaborative_rich=49719`

formal source artifact 当前未构建。原因：formal 目标用户约 155.9 万，diagnostic 每用户 120 候选时可能达到亿级候选行；当前 builder 在内存中累积 `rows` / `per_user`，checkpoint 仅记录进度，不是可恢复 shard。必须先改成可恢复分片，或在授权远程服务器受控执行后拉回 manifest、stats、评估报告和必要 artifact 本地复核。

## train-only source manifest

smoke/formal 共同依赖：

`outputs/recall/pool500_method_sources_newdata/co_visit_recent2y_train_only_source_v1/manifest.json`

该 manifest 只声明 recent-window train split 相关输入，包括：

- `canonical_interactions.train.jsonl`
- `user_sequences.train.jsonl`
- `canonical_items.jsonl` / train item universe
- `recall_views/semantic_recall_inputs.jsonl`
- `train_only_governance/user_quality_profile.jsonl`

## 构建入口

### 重建 dataset manifest 与 newdata configs

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/recall/build_co_visit_recent2y_dataset_manifests.py
```

### smoke dry-run

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source co_visit_fallback_repair --config configs/recall/full_data_pool500/co_visit_fallback_repair/source_config_newdata_smoke.yaml --tier smoke --dry-run
```

### smoke source 构建

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source co_visit_fallback_repair --config configs/recall/full_data_pool500/co_visit_fallback_repair/source_config_newdata_smoke.yaml --tier smoke --run-id co_visit_recent2y_smoke_20260603_verified --overwrite
```

### formal diagnostic dry-run

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source co_visit_fallback_repair --config configs/recall/full_data_pool500/co_visit_fallback_repair/source_config_newdata_formal.yaml --tier diagnostic --dry-run
```

### formal shard50k server dry-run

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source co_visit_fallback_repair --config configs/recall/full_data_pool500/co_visit_fallback_repair/source_config_newdata_formal_shard50k.yaml --tier formal_shard50k --run-id co_visit_recent2y_formal_shard50k_20260603 --dry-run
```

### formal shard50k server 构建（远程执行，不在本机启动）

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe scripts/experiments/recall/pool500/run_pool500_method_source.py --source co_visit_fallback_repair --config configs/recall/full_data_pool500/co_visit_fallback_repair/source_config_newdata_formal_shard50k.yaml --tier formal_shard50k --run-id co_visit_recent2y_formal_shard50k_20260603 --overwrite
```

formal 全量构建前必须先做资源 preflight，不在本机盲跑；50k shard 也只作为 server-side diagnostic，不等于 155.9 万 full formal 完成。

## 输出契约

source artifact 必须生成七件套：

- `method_dataset_manifest.json`
- `source_index_manifest.json`
- `candidates.jsonl`
- `coverage_audit.json`
- `undercoverage_audit.json`
- `resource_audit.json`
- `no_holdout_audit.json`

核心 identity / governance 字段：

- `source=co_visit_fallback_repair`
- `canonical_source=co_visit_fallback_repair`
- `source_status=TARGET_SLICE_DIAGNOSTIC`
- `algorithm_scope=train_transition_metadata_repair_v2`
- `complete_co_visit_graph_claimed=false`
- `candidate_generation_allowed=false`
- `ranking_input_replacement_allowed=false`
- `pool1000_allowed=false`
- `promotion_allowed=false`
- `full_pool500_ready_declared=false`
- `final_pool500_ready_claimed=false`

## fallback repair 任务门禁

主路 runner 现在会输出任务型审计：

- 脚本：`scripts/experiments/recall/pool500/audit_co_visit_fallback_repair_task.py`
- 输出：`co_visit_fallback_repair_task_audit.json`
- canonical source：`co_visit_fallback_repair`
- fallback source：`fallback_seed_metadata_neighbor`
- primary acceptance metric：`fallback_underfill_repair_completion`
- not-primary metrics：`HitRate`、`Recall`

任务 gate 的核心判断：

1. `fallback_completion_validation.valid=true`，且 fallback 后没有 duplicate item、per-user over target 等硬错误。
2. `underfilled_user_count` / `remaining_underfilled_user_count` 能被 fallback repair 降低，guarded sample 中优先要求补满目标候选数。
3. `fallback_added_count > 0`，并且 `fallback_seed_metadata_neighbor` / canonical `co_visit_fallback_repair` 对最终候选有实际贡献；贡献为 0 时只能 `DIAGNOSTIC_ONLY`。
4. no-holdout / forbidden scope audit 不得发现 valid/test/holdout/LOPO/oracle/eval_label 进入候选生成。
5. `ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`promotion_allowed=false`、`final_pool500_ready_claimed=false` 必须保持为 false。

因此，`co_visit_fallback_repair` 的“并入主路”含义是：作为 underfill completion 的兜底修复 source 接入，而不是作为高命中主召回 source 或 READY 方法晋升。

## 评估口径

formal / guarded 评估必须优先度量“缺口修复”，而不是只看整体 Recall：

- fallback completion validation 是否 valid
- fallback 前后的 underfilled 用户数变化
- 用户覆盖率与候选数分布
- duplicate item / 历史 item 排除 / per-user cap
- `fallback_added_count` 与 co_visit canonical contribution
- fallback ratio / popular ratio 是否可解释，不能完全退化成 popular backfill
- 与主路其他 source 的 overlap / marginal repair delta
- no_holdout_audit / forbidden input audit

Recall@K、HitRate@K 可以作为 evaluation-only sanity，但不是本方法并入主路的 primary gate。当前 P3 denominator gate 仍需补齐 `full_recall_at_500`、`in_universe_recall_at_500`、`universe_positive_ratio`、`out_of_universe_miss_ratio` 等字段，因此不能把 co_visit 包装成正式效果提升 source。

## 当前阻塞与下一步

阻塞：

1. formal source artifact 未在可恢复分片或远程受控环境下完成。
2. formal source overlap、underfilled repair delta、route gate 大样本证据仍不足；当前只允许 guarded fallback repair task 接入。
3. `pair_support`、`distinct_user_support` 已作为 train-only sequence transition 的 support gate 生效，但仍不能宣称完整 co-visit graph。
4. 当前 v2 不是完整 co-visit graph，也不是 ranking input replacement source。

下一步：

1. 继续用 `co_visit_fallback_repair_task_audit.json` 作为主路兜底任务门禁，优先看 underfill completion、去重、历史排除、贡献和 no-holdout。
2. 若要扩大样本，迁移到远程服务器受控运行 limited guarded route，回收 manifest、fallback completion audit、source contribution/overlap audit 和 no-holdout audit。
3. formal 全量前再改造 builder：candidate shard writer、per-user audit shard、resource audit merge、resume checkpoint。
4. 只有 formal 与 route gate 证据充分时，才讨论是否从 task-level guarded source 推进到更高 readiness；当前不提升为 final READY。

## 面试可讲点

数据基础切换到 recent-2y 后，我没有把旧 full-data 召回产物直接复用，而是把 co-visit fallback repair 拆成“train-only 数据治理、smoke/formal 双层验证、七件套 artifact、no-leakage audit、formal route gate”几个层次。这样既能保留共访/序列转移对稀疏用户补洞的价值，又避免把 metadata neighbor 或 smoke 结果包装成正式主召回能力。
