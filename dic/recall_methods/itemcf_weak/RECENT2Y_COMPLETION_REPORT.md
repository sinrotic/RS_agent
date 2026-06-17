# itemcf_weak recent-2y 单方法完成报告

日期：2026-06-03

## 1. 最终结论

`itemcf_weak` 已按 `POOL500_RECENT2Y_METHOD_REBUILD_GUIDE.md` 完成 recent-2y 单方法重建流程：SciOMC 调研、RALPLAN 计划、smoke/formal method dataset、source artifact、formal 后验评估、方法文档和配置更新均已完成。

但 formal strict 评估显示覆盖与 Recall@K 不足，且缺少与 READY source 的 source overlap / route gate 互补性证据，因此本窗口**不硬并 pool500 主路**，最终状态保持：

```text
DIAGNOSTIC_ONLY
```

这不是 READY 晋升完成，而是符合 guide 中“formal 效果、互补性、资源成本或 route gate 证据不足时，不要硬并，写清 blocker 和下一步”的停止条件。

## 2. 完成标准逐项对齐

| guide 完成项 | 状态 | 证据 |
|---|---:|---|
| SciOMC 调研文档 | 完成 | `dic/recall_methods/itemcf_weak/RECENT2Y_SCIOMC_RESEARCH.md`，已补论文/工业实践依据 |
| RALPLAN 执行计划 | 完成 | `dic/recall_methods/itemcf_weak/RECENT2Y_REBUILD_PLAN.md` |
| smoke dataset 构建成功 | 完成 | `outputs/recall/pool500_method_datasets/recent_2y/collab_v1_smoke/itemcf_weak/method_dataset_manifest.json` |
| smoke schema/path/gate 验证 | 完成 | smoke manifest `status=PASS`、`forbidden_scope_audit.status=PASS`、`row_count=4152` |
| formal dataset 构建成功 | 完成 | `outputs/recall/pool500_method_datasets/recent_2y/collab_v1/itemcf_weak/method_dataset_manifest.json` |
| formal manifest 记录 lineage | 完成 | formal manifest 记录 governance manifest、read_files、input_hashes、selection/resource policy |
| source artifact 构建 | 完成 | `outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/formal_strict_v1/source_index_manifest.json` |
| formal 评估报告 | 完成 | `outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/formal_strict_v1/evaluation_report.json` |
| Recall@K / 覆盖 / 用户分层 | 完成 | eval report 记录 `raw_recall@50/100/500`、`in_universe_recall@50/100/500`、`candidate_user_rate`、sequence bucket hit rate |
| readiness 明确 | 完成 | `DIAGNOSTIC_ONLY` |
| 方法文档和配置更新 | 完成 | `METHOD.md`、`source_config.yaml`、`dataset_policy.yaml`、`pool500_method_registry.json`、`rs_core/recsys/recall_sources/registry.py` |
| 工程叙事日志 | 完成 | `dic/ENGINEERING_NARRATIVE_LOG.md` 已追加 `itemcf_weak recent-2y strict 重建与诊断保留` |
| 未把旧 artifact / oracle / smoke 误晋升 | 完成 | current latest artifact 已切到 recent-2y formal strict；权限位均为 false |
| 主路并入证据 | 不满足，停止晋升 | formal strict Recall@K 为 0，coverage 太低，缺少 route gate/source overlap 证据 |

## 3. smoke 结果

manifest：

`outputs/recall/pool500_method_datasets/recent_2y/collab_v1_smoke/itemcf_weak/method_dataset_manifest.json`

关键指标：

- `status=PASS`
- `train_only=true`
- `forbidden_scope_audit.status=PASS`
- `row_count=4152`
- `unique_pair_count=2076`
- `directed_edge_count_after_topk=4152`
- `user_count=1000`
- `item_count=2400`
- `candidate_generation_allowed=false`
- `ranking_input_replacement_allowed=false`

smoke 只用于链路验证，不作为正式效果或晋升依据。

## 4. formal dataset / source artifact 结果

formal method dataset manifest：

`outputs/recall/pool500_method_datasets/recent_2y/collab_v1/itemcf_weak/method_dataset_manifest.json`

关键指标：

- `status=PASS`
- `train_only=true`
- `forbidden_scope_audit.status=PASS`
- `row_count=17866`
- `unique_pair_count=8933`
- `directed_edge_count_after_topk=17866`
- `user_count=4313`
- `item_count=9856`
- `score_policy=weighted_cooc_cosine_normalized_v1`

formal source manifest：

`outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/formal_strict_v1/source_index_manifest.json`

关键指标：

- `status=PASS`
- `row_count=17866`
- `sharded=true`
- `shard_count=8`
- `source_status=DIAGNOSTIC_ONLY`
- `candidate_generation_allowed=false`
- `ranking_input_replacement_allowed=false`
- `promotion_allowed=false`

## 5. formal 后验评估与停止晋升依据

formal evaluation report：

`outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/formal_strict_v1/evaluation_report.json`

关键指标：

- `evaluated_users_with_train_sequence=54362`
- `raw_label_total=71669`
- `in_universe_label_total=281`
- `in_universe_label_ratio=0.003921`
- `users_with_seed_hit=274`
- `seed_hit_user_rate=0.00504`
- `users_with_candidates=232`
- `candidate_user_rate=0.004268`
- `candidate_count_stats.max=14`
- `raw_recall@50=0.0`
- `raw_recall@100=0.0`
- `raw_recall@500=0.0`
- `in_universe_recall@50=0.0`
- `in_universe_recall@100=0.0`
- `in_universe_recall@500=0.0`

据此判断：strict formal 边图虽然构建成功，但 eval label 的 in-universe 覆盖极低，候选用户覆盖也极低，没有形成可证明 Recall@K 收益。因此不能把它晋升为 READY 或并入 pool500 主路。

## 6. 权限位与主路状态

当前权限位：

```yaml
candidate_generation_allowed: false
ranking_input_replacement_allowed: false
promotion_allowed: false
pool1000_allowed: false
final_pool500_ready_claimed: false
```

主路结论：

```text
not_promoted_to_pool500_main_route
```

原因：

1. formal strict `candidate_user_rate=0.004268`，覆盖不足。
2. formal strict `raw_recall@500=0.0`。
3. formal strict `in_universe_recall@500=0.0`。
4. 缺少 source overlap / route gate 互补性证据。
5. strict item universe 对 valid/test label 的覆盖不足，`in_universe_label_ratio=0.003921`。

## 7. 验证命令与结果

已通过：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_pool500_method_dataset.py tests/test_pool500_itemcf_method_dataset_source_adapter.py tests/test_pool500_itemcf_weak_method_source.py
```

结果：

```text
31 passed in 1.25s
```

JSON registry 格式校验通过：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m json.tool configs/recall/pool500_method_registry.json >/dev/null
```

全局 registry drift 测试仍受其他方法既有漂移影响，失败点包括 `category`、`usercf_recall`、`semantic_title_category_expansion`、`co_visit_fallback_repair`，不属于本窗口 `itemcf_weak` 范围。本窗口已同步 `itemcf_weak` 的 JSON registry 与 `rs_core/recsys/recall_sources/registry.py` latest artifact / row count。

## 8. 下一步

若后续继续推进 `itemcf_weak`，建议作为新任务单独执行：

1. 构建 `weak_coverage` formal profile：考虑 `sequence_sufficient + collaborative_rich` 用户桶，item bucket 扩展到 `cf_ready/embedding_ready`，但必须 server 优先、分 shard、记录资源水位。
2. 与 `popular`、`category`、`swing_recall`、`itemcf_strong`、`usercf_recall` 做 source overlap 和边际 Recall@K 对比。
3. 若 coverage profile 仍无收益，则长期保持 `DIAGNOSTIC_ONLY`，作为诊断/消融 source，而不是 pool500 主路 source。
