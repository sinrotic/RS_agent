# user_quality

## 方法定位
用户质量分层不是召回 source，而是调度 / eligibility policy。它决定哪些用户进入重召回矩阵或 sidecar，不承担召回本身。

## 当前 readiness
- 状态：`DIAGNOSTIC_POLICY_READY`
- 已实现 batch-scoped train-only profiling：`rs_lab/experiments/recall/build_pool500_user_quality_profile.py`。
- 产物只作为 UserCF / ItemCF / Swing 等重资源召回的 eligibility policy 输入，不代表 pool500 final recall ready。

## 分层建议
- `heavy_cf_eligible`：`positive_count>=10`、`unique_item_count>=5`、`shared_item_neighbor_count>=1`，适合 UserCF / ItemCF / Swing。
- `medium_behavior`：`positive_count>=4`、`unique_item_count>=2`，适合 ItemCF / category / semantic。
- `fallback_only`：行为少，优先 category / popular / semantic fallback。

`category_count` 保留为诊断字段，不参与 eligibility 分层门槛。

## 建议字段
- `user_id`
- `positive_count`
- `unique_item_count`
- `category_count`
- `shared_item_neighbor_count`（first-N train profiled users 内的 capped train-only 共享信号：任一 unique positive item 被多个 profiled user 使用则为 1，否则为 0）
- `quality_bucket`
- `eligible_for_usercf`
- `eligible_for_itemcf`
- `eligible_for_swing`
- `fallback_only`

## 输出 artifact 规划
默认 batch 输出目录：`outputs/recall/pool500_user_quality/target500_train_only/`。

- `eligible_user_quality_manifest.json`
- `quality_bucket_summary.json`
- `resource_audit.json`

manifest 会记录 first-N train profiling 边界：`profiled_user_count`、`profile_source_rows_scanned`、`first_profiled_user_id`、`last_profiled_user_id`、`profiled_user_ids_sha256`、`profile_universe_scope=first_n_train_users`。`resource_audit.json` 同步记录 runtime 与 RSS memory 采样字段。

关键约束：
- 只读取 `user_sequences.train.jsonl` 和 `canonical_items.jsonl`。
- 不读取 holdout / valid / test / clean_10000 / pool1000 作为训练或 readiness 证据。
- `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`final_pool500_ready_claimed=false`。

## 当前问题
当前 target20/100/500 是按前 N 个 train users 诊断，不是按用户质量筛选；后续扩大前应先引入质量分层，避免把重矩阵资源浪费在低信息密度用户上。

## 使用方式

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m rs_lab.experiments.recall.build_pool500_user_quality_profile --limit-users 500 --overwrite
```

该命令只生成用户质量 policy artifact，不启动最终 full 500pool run，不做 promotion，不替换 ranking input。

## 下一步
将 `eligible_user_quality_manifest.json` 作为 UserCF / ItemCF / Swing 的 batch target 过滤输入，优先让 `heavy_cf_eligible` 用户进入 UserCF / strong ItemCF，让 `heavy_cf_eligible_or_medium_behavior` 用户进入 weak ItemCF / Swing，并把 `fallback_only` 用户留给 category / popular / semantic fallback。

## 统一 train-only governance 层

新增统一治理底座脚本：`rs_lab/experiments/recall/build_train_only_data_governance.py`。它以 clean full manifest 为唯一事实源，只解析 `canonical_interactions.train.jsonl` 和 `user_sequences.train.jsonl`，派生 `outputs/recall/data_governance/train_only_v1/` 下的治理产物，不修改 clean full 原始文件。

核心产物：
- `user_quality_profile.jsonl`：用户行为质量画像，包含 `cold_start`、`fallback_only`、`medium_behavior`、`heavy_cf_eligible`、`two_tower_train_eligible` 等互斥 bucket 和方法 eligibility flags。
- `item_frequency_train.jsonl`：train 正样本 item 频次、用户数和可用 category / brand / store 字段。
- `item_universe_summary.json`：`min_freq>=2/3/5/10` 与 `top50k/100k/200k` universe 覆盖摘要。
- `cold_start_user_profile.jsonl` / `long_tail_item_profile.jsonl`：冷启动用户与长尾 item 标记；只标记，不从 clean full 删除。
- `leakage_audit.json` / `manifest.json`：记录 train-only、防泄漏、lineage、输入 hash、阈值和后续派生策略。

后续方法消费边界：
- `itemcf_strong`：只消费 `heavy_cf_eligible` 用户。
- `itemcf_weak`：消费 `heavy_cf_eligible + medium_behavior` 用户。
- `two_tower`：消费 `two_tower_train_eligible` 及更高行为质量用户，并结合 train frequency 派生 hot item universe。

这层 governance 是方法数据集的上游，不直接生成候选、不替换 ranking input、不读取 valid/test/holdout/lopo。

## 专项优化 Agent 调用说明
后续单独调用 Agent 优化本策略时，目标应是产出 `eligible_user_quality_manifest.json` 和 bucket summary，用于调度重资源召回方法，而不是新增召回 source。Agent 应统计 positive_count、unique_item_count、category_count、shared_item_neighbor_count 等字段，按当前门槛划分 `heavy_cf_eligible`、`medium_behavior`、`fallback_only`，并明确哪些 bucket 允许进入 UserCF / ItemCF / Swing；不得把 user_quality 写入 candidate source 或 READY source 列表。
