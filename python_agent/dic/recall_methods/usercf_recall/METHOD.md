# usercf_recall

## 方法定位

`usercf_recall` 是基于共享正反馈 item 的用户相似召回：先在 train-only 用户-item 行为图中寻找相似用户，再从相似用户历史中扩展候选。它适合 `heavy_cf_eligible` / `collaborative_rich` 用户的补充召回，不适合 cold/fallback 用户，也不应替代 popular/category 等覆盖型召回。

本轮 recent-2y 重建的调研和计划文档：

- SciOMC 调研：`dic/recall_methods/usercf_recall/RECENT2Y_SCIOMC_RESEARCH.md`
- RALPLAN 执行计划：`dic/recall_methods/usercf_recall/RECENT2Y_REBUILD_PLAN.md`
- 低覆盖论文调研与解决方案：`dic/recall_methods/usercf_recall/RECENT2Y_LOW_COVERAGE_SOLUTION_RESEARCH.md`

## 当前 readiness

- 当前状态：`DIAGNOSTIC_ONLY`
- source index：`INDEX_READY`
- diagnostic output：`DIAGNOSTIC_OUTPUT_READY`
- future promotion status：`DIAGNOSTIC_ONLY_NOT_READY`；后续只有在全局 route gate / source overlap / Recall@K / 互补性 / 资源成本证据充分后，才可重新评审是否进入 `POOL500_RECALL_ONLY_SUPPLEMENTAL_READY`。
- 禁止：`candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`promotion_allowed=false`、`final_pool500_ready_claimed=false`

结论：本轮已经完成 recent-2y train-only clean-sequence item-first full diagnostic 重建，并通过 `user_after_src_filter>=2/3/4/5/6/10` 阈值扫描，固定当前 UserCF 默认 full diagnostic artifact 为 `usercf_itemfirst_src2_dst3_user3_keep_hot_full_diagnostic_v1`。该产物只作为 `DIAGNOSTIC_ONLY` diagnostic contribution 参与审计，不纳入 READY stoploss sources，也不晋升 READY。选择 `user>=3` 的原因是它在覆盖、成本和 served-user test HitRate@100 之间最均衡；valid/test labels 仅用于 evaluation-only 后验评估，不参与候选生成。

## recent-2y 数据基础

- 数据根：`data/processed/amazon_2023_recall_recent_2y_1m_3m/`
- train-only governance：`data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json`
- governance 状态：`PASS`
- train users：`6,826,801`
- `collaborative_rich`：`49,719`
- train-only item universe：`864,288` items

允许输入：

- `train_only_governance/manifest.json`
- `train_only_governance/user_quality_profile.jsonl`
- `train_only_governance/item_quality_profile.jsonl`
- `train_only_governance/item_frequency_train.jsonl`
- `user_sequences.train.jsonl`
- 本方法基于上述输入派生的 smoke/formal method dataset

禁止输入：holdout / valid / test / LOPO / oracle / eval label / clean_10000 / pool1000 / 旧 full-data-derived method dataset。

## recent-2y smoke/formal method dataset

| 档位 | manifest | row_count | user_count | item_count | 说明 |
| --- | --- | ---: | ---: | ---: | --- |
| smoke | `outputs/recall/pool500_method_datasets/recent_2y/usercf_sciomc_v1/smoke/usercf_method_dataset/method_dataset_manifest.json` | 995 | 995 | 1364 | profile-driven 2% actual eligible users，只验证链路 |
| formal | `outputs/recall/pool500_method_datasets/recent_2y/usercf_sciomc_v1/formal/usercf_method_dataset/method_dataset_manifest.json` | 15884 | 15884 | 19595 | actual eligible users，不套旧 fixed cap |

筛选策略：

- sampling unit：`connected_user_item_subgraph`
- eligible user：`collaborative_rich` / heavy-CF ready 用户
- eligible item：`cf_ready` 且 non-over-hot
- min overlap：要求可形成共享 item 邻居
- item weighting / control：通过 cf-ready/non-over-hot 与 `max_item_user_freq=5000` 控制热门 item 影响
- dropped reason：记录 `user_bucket_not_allowed`、`no_cf_ready_non_over_hot_items`、`item_over_hot`、`item_not_cf_ready` 等原因

## recent-2y source artifact

### smoke source

- output root：`outputs/recall/pool500_method_sources/recent_2y_smoke/`
- run id：`usercf_recent_2y_sciomc_smoke_v1`
- source index：`outputs/recall/pool500_method_sources/recent_2y_smoke/usercf_recall/usercf_recent_2y_sciomc_smoke_v1/source_index_manifest.json`
- 结果摘要：`target_user_count=995`、`candidate_user_count=9`、`candidate_total_count=20`
- 用途：验证 method-dataset 输入、schema、no-holdout gate、source builder 和 loader 可用；不作为正式效果依据。

### formal source

- output root：`outputs/recall/pool500_method_sources/recent_2y/`
- run id：`usercf_recent_2y_sciomc_formal_v1`
- source index：`outputs/recall/pool500_method_sources/recent_2y/usercf_recall/usercf_recent_2y_sciomc_formal_v1/source_index_manifest.json`
- readiness contract：`outputs/recall/pool500_method_sources/recent_2y/usercf_recall/usercf_recent_2y_sciomc_formal_v1/readiness_contract.json`
- coverage audit：`outputs/recall/pool500_method_sources/recent_2y/usercf_recall/usercf_recent_2y_sciomc_formal_v1/coverage_audit.json`
- undercoverage audit：`outputs/recall/pool500_method_sources/recent_2y/usercf_recall/usercf_recent_2y_sciomc_formal_v1/undercoverage_audit.json`
- resource audit：`outputs/recall/pool500_method_sources/recent_2y/usercf_recall/usercf_recent_2y_sciomc_formal_v1/resource_audit.json`
- no-holdout audit：`outputs/recall/pool500_method_sources/recent_2y/usercf_recall/usercf_recent_2y_sciomc_formal_v1/no_holdout_audit.json`
- formal summary：`outputs/recall/pool500_method_sources/recent_2y/usercf_recall/usercf_recent_2y_sciomc_formal_v1/formal_evaluation_summary.json`

formal 构建参数：

- `candidate_top_k_per_user=500`
- `generation_usercf_per_user=500`
- `similar_users_top_k=200`
- `max_items_per_user=80`
- `max_item_user_freq=5000`
- `target_batch_size=2000`
- `shard_count=16`
- `max_rss_mb=4096`

formal 结果摘要：

- `target_user_count=15884`
- `candidate_user_count=2081`
- `candidate_total_count=4043`
- `candidate_row_count=4043`
- 用户覆盖率：`2081 / 15884 = 0.131012`
- candidate count stats：`min=1`、`p50=1`、`p90=4`、`max=14`
- `neighbor_edge_checks=4800`
- `similar_user_links_used=4780`
- `dropped_hot_item_count=0`
- `peak_rss_mb=67`
- `runtime_seconds=0.598863`

undercoverage 摘要：

- `only_seen_items_after_neighbor_merge=13803`
- `unknown_after_train_only_diagnostics=2081`

解释：formal artifact 可以证明 recent-2y train-only UserCF source 构建链路可用，但大量用户在邻居合并后只剩已看 item 或候选不足，覆盖率不足以支撑 READY 晋升。

### raw-vs-filtered reachability 诊断

- 诊断脚本：`scripts/experiments/recall/pool500/diagnose_usercf_raw_vs_filtered_reachability.py`
- bounded smoke report：`outputs/recall/pool500_method_diagnostics/recent_2y/usercf_recall/raw_vs_filtered_reachability_v1/report.json`
- 范围：`target_user_limit=100`，valid/test 仅作为 evaluation-only label。
- 结果摘要：`label_total_count=20`、`raw_neighbor_reachable_label_count=1`、`filtered_neighbor_reachable_label_count=0`、`final_candidate_hit_count=0`、`raw_reachability_rate=0.05`、`filtered_reachability_rate=0.0`、`final_recall_at_k=0.0`。
- 解释：该 bounded smoke 初步支持“raw 邻居空间存在少量未来 label 可达，但 strict filtered eligible item universe 截断了这部分信号”的判断；样本较小，不作为 formal 效果依据，也不改变 `DIAGNOSTIC_ONLY` readiness。

### relaxed IUF smoke 变体

- 方法数据集：`outputs/recall/pool500_method_datasets/recent_2y/usercf_relaxed_iuf_v1/smoke/usercf_method_dataset/method_dataset_manifest.json`
- source artifact：`outputs/recall/pool500_method_sources/recent_2y_usercf_relaxed_iuf_smoke/usercf_recall/usercf_recent_2y_relaxed_iuf_smoke_v1/source_index_manifest.json`
- evaluation-only report：`outputs/recall/pool500_method_evals/recent_2y/usercf_relaxed_iuf_smoke_v1/method_source_eval_report.json`
- 变体口径：eligible user 放宽到 `sequence_sufficient ∪ collaborative_rich`；eligible item 放宽到 `cf_ready ∪ embedding_ready`，hot item 不直接 drop，而在 sidecar 使用 `scoring_policy=iuf_cosine` 降权。
- smoke 结果摘要：method dataset `row_count=5000`、`item_count=19097`；source `candidate_user_count=3783`、`candidate_total_count=169565`、`underfilled_user_coverage=0.7566`、`candidate_count p50=20 / p90=117 / max=500`、`peak_rss_mb=73`。
- evaluation-only 指标：`scored_user_count=25`，`Recall@20/50/100/500=0.04`、`HitRate@20/50/100/500=0.04`；valid/test 只用于评估，report 中 `label_inputs_role=evaluation_only_not_candidate_generation_inputs`、`no_oracle_label_injection=true`。
- 解释：relaxed IUF smoke 已证明放宽 item universe + IUF 降权可以显著改善候选覆盖，并出现少量 evaluation-only 命中；但样本仍是 smoke，`scored_user_count` 仅 25，尚不足以把 `usercf_recall` 晋升 READY。

### clean train item-first smoke 变体

- source artifact：`outputs/recall/pool500_method_sources/recent_2y/usercf_recall/usercf_itemfirst_src2_dst3_keep_hot_smoke_diagnostic_v1/source_index_manifest.json`
- resource audit：`outputs/recall/pool500_method_sources/recent_2y/usercf_recall/usercf_itemfirst_src2_dst3_keep_hot_smoke_diagnostic_v1/resource_audit.json`
- no-holdout audit：`outputs/recall/pool500_method_sources/recent_2y/usercf_recall/usercf_itemfirst_src2_dst3_keep_hot_smoke_diagnostic_v1/no_holdout_audit.json`
- evaluation-only report：`outputs/recall/pool500_method_evals/recent_2y/usercf_itemfirst_src2_dst3_keep_hot_smoke_diagnostic_v1/method_source_eval_report.json`
- 变体口径：不先生成 formal flat dataset；直接读取 clean train `user_sequences.train.jsonl`，用完整 train-only positive sequence 去重统计 item positive user count。先筛 item：src item 要求 `positive_user_count>=2`，dst candidate item 要求 `positive_user_count>=3`；`keep_hot=true`，hot item 不 hard drop，使用 `iuf_cosine` 降权。再筛 user：用户 history 按 src eligible item 过滤后，保留 item 数 `<2` 的用户不贡献 UserCF pair。
- source 结果摘要：`target_user_count=5000`、`candidate_user_count=5000`、`candidate_total_count=499994`、`candidate_count min/p50/p90/max=94/100/100/100`，候选覆盖从旧 strict formal 的 `13.10%` 提升到 smoke `100%`。
- item/user 过滤统计：`src_eligible_item_count=446326`、`dst_eligible_item_count=332996`、`indexed_user_count=1141645`、`observed_over_freq_item_count=10`、`dropped_hot_item_count=0`、`peak_rss_mb=4034`、`runtime_seconds=171.116251`。
- no-holdout 审计：构建阶段 `read_files` 只包含 `user_sequences.train.jsonl` 和内部 eligible manifest；`uses_valid=false`、`uses_test=false`、`uses_holdout=false`、`uses_10k=false`、`uses_pool1000=false`，`ranking_input_modified=false`。
- evaluation-only 指标：report 为 `PASS`，valid/test 仅用于后验打分，`label_inputs_role=evaluation_only_not_candidate_generation_inputs`、`no_oracle_label_injection=true`；整体 `Recall@20=0.000001`、`Recall@50=0.000002`、`Recall@100=0.000003`、`Recall@500=0.000003`，`HitRate@500=0.000017`。
- 解释：item-first clean train 口径解决了 UserCF 候选覆盖稀疏问题，但命中仍很弱，说明当前 UserCF 更适合作为后续 formal/route-gate/overlap 诊断对象，不能仅凭覆盖改善晋升 READY。

### src/item 筛选消融诊断

针对“是否应先筛 user、是否不筛 item”的问题，追加了 3 组并行 smoke 诊断：

| 变体 | run id | target users | item/user 口径 | candidate users | candidate rows | candidate-only Recall@100 | candidate-only HitRate@100 | 结论 |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
| A | `usercf_itemfirst_src2_dst3_user2_keep_hot_smoke3k_diagnostic_v1` | 3000 | src>=2,dst>=3,user2 | 3000 | 300000 | 0.006192 | 0.028986 | 历史 smoke 口径选择证据，不是当前默认 full artifact，也不是 READY |
| C | `usercf_nosrc_dst3_user2_keep_hot_smoke3k_diagnostic_v1` | 3000 | src>=1,dst>=3,user2 | 3000 | 300000 | 0.006192 | 0.028986 | 放开 src 未改善命中 |
| B | `usercf_nosrc_dst3_user3_keep_hot_smoke3k_diagnostic_v1` | 3000 | src>=1,dst>=3,user3 | 3000 | 300000 | 0.006192 | 0.028986 | 加严 user 未改善命中 |
| D | `usercf_noitem_src1_dst1_user2_keep_hot_smoke3k_diagnostic_v1` | 3000 | src>=1,dst>=1,user2 | 3000 | 300000 | 0.006192 | 0.028986 | 不筛 item 与 A/B/C 在 @100 持平，但 @50 更弱 |

valid/test 分拆后，四组在 test split 上均无命中；valid split 上 A/B/C 的 candidate-only `Recall@50/100=0.006689`、`HitRate@50/100=0.029412`，D 在 `@50` 只有 `Recall=0.003344`、`HitRate=0.014706`，到 `@100` 才追平。全量 eval denominator 下 A/B/C/D 的 `valid+test Recall@100/500` 都约为 `0.000001`，`HitRate@100/500` 都约为 `0.000009`。补充观察：A/C 候选 pair Jaccard 为 `0.946497`，A/B 为 `0.846620`，说明放开 src 或加严 user 会改变一部分候选，但命中没有同步提升。当前证据不支持“完全不筛 item”或“仅放开 src”作为 UserCF 主方向；如果必须按 valid/test 选择，优先保留 A：`src>=2,dst>=3,user2,keep_hot,iuf_cosine`，因为它与最好命中持平且候选 universe 更受控。下一步如果继续验证 user-first，应实现真正的 `user-first item count scope`：先按 raw train user 行为筛 user，再只在 retained users 上统计 src/dst item support，而不是只用 `min_src_filtered_items_per_user` 近似。

### full diagnostic 用户阈值扫描与固定方案

用户指出“只有两个交互的用户相似度信号弱”，因此在 item 口径不变的前提下追加 full diagnostic 阈值扫描。固定 item 口径为 `src_min_positive_user_count=2`、`dst_min_positive_user_count=3`、`keep_hot=true`、`scoring_policy=iuf_cosine`，只调整 `min_src_filtered_items_per_user`。

| user 阈值 | target users | rows | eval served users | combined Recall@100 | combined HitRate@100 | combined served HR@100 | test served HR@100 | 结论 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 2 | 1,495,958 | 1,495,497 | 11,391 | 0.001870 | 0.002456 | 5.06% | 3.74% | 全局覆盖和全局指标最高，但包含大量低行为用户，成本最高 |
| 3 | 651,099 | 651,046 | 5,066 | 0.000950 | 0.001305 | 6.04% | 4.77% | **固定为当前默认 full diagnostic 阈值**：覆盖、成本和 test 稳定性最均衡 |
| 4 | 349,726 | 349,715 | 2,678 | 0.000492 | 0.000708 | 6.20% | 3.94% | served 质量略高但覆盖较 user3 几乎腰斩 |
| 5 | 212,252 | 212,249 | 1,657 | 0.000285 | 0.000456 | 6.46% | 2.19% | valid/combined served 质量高，但 test 命中少且不稳 |
| 6 | 140,803 | 140,801 | 1,152 | 0.000183 | 0.000316 | 6.42% | 1.72% | 覆盖过窄，test 弱 |
| 10 | 45,937 | 45,936 | 485 | 0.000044 | 0.000124 | 5.98% | 2.13% | 覆盖过窄，不作为主阈值 |

选定产物：`outputs/recall/pool500_method_sources/recent_2y/usercf_recall/usercf_itemfirst_src2_dst3_user3_keep_hot_full_diagnostic_v1/source_index_manifest.json`。远程构建摘要：`status=PASS`、`source_status=DIAGNOSTIC_ONLY`、`target_user_count=651099`、`row_count=651046`、`candidate_total_count=64327024`、`underfilled_user_coverage=0.999919`、`peak_rss_mb=3745`、`runtime_seconds=2068.227114`、`no_holdout_audit=PASS`。阈值扫描 summary：`outputs/recall/pool500_method_evals/recent_2y/usercf_threshold_shard_eval_summary.json`。

下一步至少需要 source overlap、popular overlap、candidate 质量分层和 item-universe recall 审计。

## 治理契约

- `source=usercf_recall`
- `source_status=DIAGNOSTIC_ONLY`
- `train_only=true`
- `candidate_generation_allowed=false`
- `ranking_input_replacement_allowed=false`
- `pool1000_allowed=false`
- `promotion_allowed=false`
- `final_pool500_ready_claimed=false`
- 构建阶段不读取 valid/test/holdout/LOPO/oracle/eval_label/pool1000

no-holdout audit 已确认：

- `uses_valid=false`
- `uses_test=false`
- `uses_holdout=false`
- `uses_10k=false`
- `uses_pool1000=false`
- `ranking_input_modified=false`
- `train_sequence_field=eligible_item_sequence`

## 旧 artifact 边界

以下路径仅作为历史诊断参考，不是当前 recent-2y 正式结论，也不能作为 pool500 readiness 晋升、ranking input replacement 或 pool1000 的依据：

- `outputs/recall/pool500_sidecar_fix/usercf_recall_heavy28_guarded_diagnostic/`
- `outputs/recall/pool500_usercf_method_train/usercf_recall/usercf_v1_formal_route_ready/`
- 旧 `target20/target100/target500_guarded` 诊断产物

`route_ready` 是历史产物命名，不等于当前 `READY`。

## 晋升判断与 blocker

当前固定为 pool500 主路默认 UserCF diagnostic contribution 的是 `usercf_itemfirst_src2_dst3_user3_keep_hot_full_diagnostic_v1`，但不进入 READY stoploss sources，不作为最终 READY 依据，整体保持 `DIAGNOSTIC_ONLY`。

blocker：

1. 旧 strict formal 用户覆盖率仅 `13.1012%`，说明依赖 formal method dataset 的口径不可作为 READY 依据。
2. 新 item-first smoke 虽然达到 `5000/5000` 候选覆盖，但 evaluation-only 整体 `Recall@500=0.000003`、`HitRate@500=0.000017`，尚未证明真实 label 命中价值。
3. 本窗口尚未产出 formal-like unlimited、source overlap、route gate、popular overlap 和 item-universe denominator 评估。
4. 当前证据只能证明 train-only item-first 构建可用和诊断候选生成，不足以证明对 pool500 主路有稳定互补价值。

后续如果要晋升 `POOL500_RECALL_ONLY_SUPPLEMENTAL_READY`，至少需要：

- 在全局 route gate 中报告 Recall@K、coverage、source overlap、用户桶分层、item-universe 内 recall。
- 证明 UserCF 对 heavy/collaborative-rich 用户有边际新增候选价值，而不是只补热门或已看 item。
- 通过 source loader、candidate merge、route gate regression tests。
- 保持 ranking replacement、pool1000、final pool500 ready 均为 false，除非另有全局收口批准。

## 面试可讲点

这次重建体现的是“方法特化的数据治理”：UserCF 不是简单复用旧 full-data sidecar，而是在 recent-2y train-only 口径下重新定义 eligible 用户、item 过滤、热门控制、smoke/formal 双层验证和 readiness 门禁。最终结果没有硬包装成 READY，而是基于 formal 覆盖率、undercoverage 和缺失 route-gate 证据保持 `DIAGNOSTIC_ONLY`，体现了推荐系统工程中对数据泄漏、旧产物回流和诊断结果误晋升的控制。
