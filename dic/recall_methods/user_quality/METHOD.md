# user_quality

## 方法定位
用户质量分层不是召回 source，而是调度 / eligibility policy。它决定哪些用户进入重召回矩阵或 sidecar，不承担召回本身。

## 当前 readiness
- 状态：`DIAGNOSTIC_POLICY_READY`
- 已实现 batch-scoped train-only profiling：`rs_lab/experiments/recall/build_pool500_user_quality_profile.py`。
- 产物只作为 UserCF / ItemCF / Swing 等重资源召回的 eligibility policy 输入，不代表 pool500 final recall ready。

## 分层建议
- `heavy_cf_eligible`：正反馈多、unique item 多、共享 item 邻居充足，适合 UserCF / ItemCF / Swing。
- `medium_behavior`：行为中等，适合 ItemCF / category / semantic。
- `fallback_only`：行为少或 metadata 缺失，优先 category / popular / semantic fallback。

## 建议字段
- `user_id`
- `positive_count`
- `unique_item_count`
- `category_count`
- `shared_item_neighbor_count`
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

## 专项优化 Agent 调用说明
后续单独调用 Agent 优化本策略时，目标应是产出 `eligible_user_quality_manifest.json` 和 bucket summary，用于调度重资源召回方法，而不是新增召回 source。Agent 应统计 positive_count、unique_item_count、category_count、shared_item_neighbor_count 等字段，划分 `heavy_cf_eligible`、`medium_behavior`、`fallback_only`，并明确哪些 bucket 允许进入 UserCF / ItemCF / Swing；不得把 user_quality 写入 candidate source 或 READY source 列表。
