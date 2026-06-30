# category

## 方法定位

`category` 是基于用户 train 历史 item 类目画像的轻量召回源，服务于 pool500 的稳定覆盖、可解释 fallback 和类目多样性补位。它不是强个性化主力召回，也不替代 ranking input。

当前 recent-2y 重建后，`category` 不再从旧 `pool500_sidecar_fix` / full-data promoted candidates 派生当前结论，而是直接从 recent-2y train-visible 输入构建：

- `data/processed/amazon_2023_recall_recent_2y_1m_3m/canonical_items.jsonl`
- `data/processed/amazon_2023_recall_recent_2y_1m_3m/user_sequences.train.jsonl`
- `data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/user_quality_profile.jsonl`
- `data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/item_frequency_train.jsonl`
- `data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/category_top_items.jsonl`
- `data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/category_recall_items.jsonl`

## 当前 readiness

- 单方法状态：`READY`
- 语义：recent-2y train-only category source artifact 已构建并通过本地 formal 50k 验证。
- 限制：单方法 READY 不等于 pool500 主路已并入；是否进入主路必须经过全局 route gate、source overlap、candidate merge 和回归测试。
- 默认权限：
  - `candidate_generation_allowed=false`
  - `ranking_input_replacement_allowed=false`
  - `promotion_allowed=false`
  - `pool1000_allowed=false`

## SciOMC 调研结论

详见：`dic/recall_methods/category/RECENT2Y_SCIOMC_RESEARCH.md`

核心结论：

1. Category / taxonomy 适合作为可解释、低资源的 metadata recall source。
2. 用户类目画像应从 train 历史 item 聚合，不读取 eval label。
3. 类目内热门可提升覆盖，但容易放大热门偏置，必须监控 top category share、category diversity 和 popular overlap。
4. Category 的价值主要是 fallback coverage，不应因 coverage 高就宣称排序效果或主路晋升。

## RALPLAN 执行计划

详见：`dic/recall_methods/category/RECENT2Y_REBUILD_PLAN.md`

最终采用 direct recent-2y builder：

- 新增：`rs_lab/experiments/recall/pool500/methods/category/builder.py`
- 更新：`rs_lab/experiments/recall/pool500/methods/category/__init__.py`
- 复用 runner：`scripts/experiments/recall/pool500/run_pool500_method_source.py`

## 数据集策略

### Smoke

- run id：`category_recent2y_smoke_v1`
- 目标：程序和 schema 验证。
- 用户：500 个 train-only eligible 用户。
- 候选：每用户最多 40。
- 结果路径：
  - `outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_smoke_v1/method_dataset_manifest.json`
  - `outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_smoke_v1/source_index_manifest.json`
  - `outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_smoke_v1/candidates.jsonl`

Smoke 结果：

- `candidate_row_count=19,840`
- `target_user_count=500`
- `user_coverage_count=500`
- `user_coverage_ratio=1.0`
- per-user candidates：min 12 / p50 40 / p90 40 / max 40
- `no_holdout_audit.status=PASS`

### Formal

- run id：`category_recent2y_formal_50k_v1`
- 目标：本地 formal 方法逻辑 artifact、coverage 与 eval-only Recall 证据。
- 用户：50,000 个 train-only eligible 用户。
- 候选：每用户最多 80。
- 注意：这是 local-formal 50k 物化候选切片，服务 eval-only Recall 评估；正式全量 eligible route-formal 采用索引型 artifact，不默认物化全量 user-item candidates。

结果路径：

- `outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_formal_50k_v1/method_dataset_manifest.json`
- `outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_formal_50k_v1/source_index_manifest.json`
- `outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_formal_50k_v1/candidates.jsonl`
- `outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_formal_50k_v1/evaluation_report.json`

Formal 结果：

- `candidate_row_count=3,976,451`
- `target_user_count=50,000`
- `user_coverage_count=50,000`
- `user_coverage_ratio=1.0`
- `unique_item_count=7,944`
- per-user candidates：min 20 / p50 80 / p90 80 / max 80
- category buckets in candidates：410
- top category bucket share：0.190255
- `no_holdout_audit.status=PASS`
- runtime：110.15s

### All-eligible route-formal index

- run id：`category_recent2y_all_eligible_index_v1`
- 目标：recent-2y 全量 category eligible 用户的 route-formal 索引型 artifact。
- 执行位置：`server:/home/luo/RS_agent_remote`
- 用户：1,558,964 个 train-only eligible 用户。
- 产物形态：不物化全量 `candidates.jsonl`，只保存索引与画像；route merge 或评估需要候选时再按需展开。

远端完整产物路径：

- `server:/home/luo/RS_agent_remote/outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_all_eligible_index_v1/`

本地已拉回复核的轻量证据路径：

- `outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_all_eligible_index_v1/source_index_manifest.json`
- `outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_all_eligible_index_v1/method_dataset_manifest.json`
- `outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_all_eligible_index_v1/coverage_audit.json`
- `outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_all_eligible_index_v1/resource_audit.json`
- `outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_all_eligible_index_v1/no_holdout_audit.json`
- `outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_all_eligible_index_v1/remote_provenance.json`

All-eligible 结果：

- `candidate_materialization=none`
- `target_user_count=1,558,964`
- `user_coverage_count=1,558,964`
- `user_coverage_ratio=1.0`
- `profile_row_count=1,558,964`
- `candidate_row_count=0`（设计上不物化候选）
- `empty_profile_user_count=0`
- profile bucket count：min 1 / p50 6 / p90 6 / max 6
- 远端 runtime：213.18248s
- `no_holdout_audit.status=PASS`
- 本地 manifest/audit revalidation：PASS

全量远端文件规模：

- `eligible_users.jsonl`：约 329MB
- `user_category_profile.jsonl`：约 1.3GB
- `category_top_items_index.jsonl`：约 7.1MB

## 构建方法

1. 读取 train-only governance manifest，并强校验 `train_only=true`、`valid/test/holdout/lopo_used=false`。
2. 从 `recall_views/category_top_items` 读取 train popularity 的类目内 top items。
3. 从 `recall_views/category_recall_items` 读取轻量 item → category buckets 视图，避免解析 `canonical_items` 中的大文本字段。
4. 从 `user_quality_profile` 选取 eligible 用户桶：`fallback_only`、`medium_behavior`、`sequence_sufficient`、`collaborative_rich`。
5. 从 `user_sequences.train` 读取目标用户序列，构建用户类目画像。
6. `formal_50k` 为评估方便会物化 `candidates.jsonl`；`all_eligible` 只输出 `eligible_users.jsonl`、`user_category_profile.jsonl`、`category_top_items_index.jsonl`，候选在 route merge / eval 时按需展开。
7. 输出 manifest、coverage / undercoverage / resource / no-holdout audit。

关键参数：

- `seed_window=20`
- formal `max_profile_buckets=6`
- formal `category_bucket_cap_per_user=20`
- formal `category_min_item_count=5`
- formal `per_user=80`

## 评估结果

评估脚本只在评估阶段读取 `valid/test` label，候选生成过程没有读取 eval label。

Formal 50k eval-only 指标：

| split | eval positive pairs in candidate users | Recall@20 | Recall@50 | Recall@80 | Hit users @80 |
|---|---:|---:|---:|---:|---:|
| valid | 409 | 0.004890 | 0.007335 | 0.012225 | 5 |
| test | 182 | 0.005495 | 0.010989 | 0.010989 | 2 |

解释：

- Category source 的 coverage 很稳，适合 fallback / coverage。
- 纯 category Recall@K 较弱，不足以作为强召回主力或 ranking replacement。
- 是否并入 pool500 主路需要全局 route gate 结合 popular overlap、source contribution、underfill 和 merge 后效果判断。

## 治理契约

- 构建输入仅限 train-visible 数据。
- 禁止读取或注入：holdout、valid、test、LOPO、oracle、eval label、clean_10000、pool1000、旧 full-data method dataset。
- `smoke` 不作为正式效果。
- `formal_50k` 可以作为单方法 eval-only 效果证据，但不自动晋升主路。
- `all_eligible` 是全量 eligible 索引型 route-formal artifact，不物化全量候选；真正进入主路前仍需 route merge gate。
- 当前 artifact 中权限位保持 false：candidate generation、promotion、ranking replacement、pool1000。

## 当前 blocker 与下一步

Blocker：

1. 全量 eligible 索引 artifact 已完成，但还没有把它接入 pool500 route merge 的按需候选展开器。
2. Pure category Recall@80 仍以 50k 物化切片为证据，指标较弱，不能单独证明主路提升。
3. 与 popular 的 overlap / route merge contribution 需要在全局收口中重算。

下一步：

1. 在全局 pool500 route closeout 中，为 category all-eligible index 增加按需候选展开逻辑。
2. 将 category index 与 popular、CF、semantic 等 source 统一做 overlap / contribution / underfill gate。
3. 若需要离线大规模评估，不直接写单个全量 `candidates.jsonl`，而是按 shard / parquet / stream 方式从 index 展开。
4. 优化方向优先是降低热门类目占比、调整 `main::` 与 `path::` 权重、增强 fallback_only 用户覆盖解释，而不是把 category 升级成复杂模型。

## 面试可讲点

这次重建把 category 从“旧 full-data sidecar 中的现成 source”改造成了可复核的 recent-2y train-only source：先用论文与工业实践确认它的定位是轻量 fallback retrieval，再用 manifest lineage、input hash、no-holdout audit、smoke/formal 双层验证和 eval-only 指标防止数据泄漏与旧 artifact 回流。最终结论没有硬吹 Recall，而是把它准确定位为覆盖稳定、可解释但弱召回的候选源，体现了推荐系统召回层的工程治理和门禁意识。
