# pool500 用户质量分层

用户质量分层不是召回 source，而是重召回矩阵的调度策略。目标是把 UserCF、ItemCF、Swing 等资源更重的计算优先分配给信息密度更高的用户。

## 建议分层

- `heavy_cf_eligible`：正反馈多、unique item 多、共享 item 邻居充足，适合 UserCF / ItemCF / Swing。
- `medium_behavior`：行为中等，适合 ItemCF / category / semantic 扩展。
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

## 下一步

先在 target500 用户上构建 batch-scoped quality manifest，再用 bucket 控制 UserCF / ItemCF 的目标用户集合，避免把重矩阵资源浪费在低信息密度用户上。
