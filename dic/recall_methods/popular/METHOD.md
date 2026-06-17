# popular

## 方法定位

`popular` 是 pool500 recent-2y 召回链路中的热门兜底与 coverage backfill source。它的目标不是个性化建模，而是在冷启动、fallback_only、重召回无命中或候选池不足时提供稳定候选。

本轮重建后，`popular` 使用 recent-2y train-only governance 下的 `item_frequency_train.jsonl` 直接构建全局热门 source，不复用旧 full-data / sidecar artifact 作为当前结论。

## 当前 readiness

- 状态：`READY`
- 已并入 pool500 主路，作为 budgeted fallback / backfill candidate source。
- 允许在主路候选生成阶段使用 formal source artifact。
- 不允许 ranking input replacement。
- 不允许 pool1000 自动晋升。
- 不允许单方法自动 promotion；本次并入口径只覆盖召回候选池中的兜底补齐，不代表整体 pool500 final ready。

## Recent-2y 治理契约

### 允许输入

- `data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json`
- `data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/item_frequency_train.jsonl`

评估阶段可以读取 valid/test label 与 train user sequences，但仅用于指标计算和 seen filtering，不得影响候选排序或 source 构建。

### 禁止输入

- holdout / valid / test 作为候选生成或构建输入
- LOPO / oracle / eval label
- clean_10000 / pool1000 诊断产物
- 旧 full-data-derived method dataset 或旧 sidecar artifact 作为当前结论

## 构建策略

- 方法类型：非训练型统计 source。
- 排序规则：`(-frequency, parent_asin)` deterministic rank。
- item universe：recent-2y train-only positive item frequency 中 `frequency > 0` 的 item。
- smoke：top 500，仅验证 schema、manifest、path、no-holdout gate 和最小评估链路。
- formal：完整 train-only positive-frequency item universe，不做方法侧小 cap。

## 当前产物

### Smoke

- method dataset manifest：`outputs/recall/pool500_method_datasets/recent_2y/popular/smoke/popular_recent2y_smoke_v1/method_dataset_manifest.json`
- source index manifest：`outputs/recall/pool500_method_sources/recent_2y/popular/smoke/popular_recent2y_smoke_v1/source_index_manifest.json`
- row count：500
- 用途：program/schema validation only；不作为正式效果依据。

### Formal

- method dataset manifest：`outputs/recall/pool500_method_datasets/recent_2y/popular/formal/popular_recent2y_formal_v1/method_dataset_manifest.json`
- source index manifest：`outputs/recall/pool500_method_sources/recent_2y/popular/formal/popular_recent2y_formal_v1/source_index_manifest.json`
- candidates：`outputs/recall/pool500_method_sources/recent_2y/popular/formal/popular_recent2y_formal_v1/candidates.jsonl`
- evaluation report：`outputs/recall/pool500_method_sources/recent_2y/popular/formal/popular_recent2y_formal_v1/evaluation_report.json`
- row count：762622
- `candidate_generation_allowed=true`
- `main_route_merge_status=MERGED_AS_BUDGETED_FALLBACK_SOURCE`
- `main_route_candidate_source_allowed=true`
- `ranking_input_replacement_allowed=false`
- `pool1000_allowed=false`
- `promotion_allowed=false`

## Formal 评估摘要

评估报告：`outputs/recall/pool500_method_sources/recent_2y/popular/formal/popular_recent2y_formal_v1/evaluation_report.json`

- eval_user_count：234485
- positive_event_count：308281
- Recall@10/50/100/500：0.005343 / 0.018924 / 0.027238 / 0.078068
- HitRate@10/50/100/500：0.006879 / 0.024155 / 0.034783 / 0.098360
- in-train-candidate-universe positives：276897
- In-universe Recall@500：0.086917
- long_tail_positive_count：15894
- Long-tail Recall@500：0.0
- candidates per eval user@500：min=500, p50=500, mean=500, max=500

分层观察：

- cold_start Recall@500：0.073762
- fallback_only Recall@500：0.065653
- sequence_sufficient Recall@500：0.044652
- collaborative_rich Recall@500：0.009076

结论：`popular` 对冷启动/兜底用户有基础覆盖价值，但个性化用户和长尾 positive 召回弱。因此本轮直接并入 pool500 主路的口径是 **budgeted fallback / backfill candidate source**：可参与主路候选生成和补齐，但不扩大为主力个性化召回或 ranking replacement。

## 资源画像

- 构建方式：本地 `.venv`，无 GPU、无 ANN、无 embedding 训练。
- 资源类型：轻量 train-only frequency sort + JSONL/manifest 输出。
- formal source candidate row count：762622。
- no_holdout_audit：PASS。

## 风险与门禁

| 风险 | 当前处理 |
|---|---|
| 旧 full-data artifact 回流 | 当前 manifest 指向 recent_2y 输出路径，旧产物只作历史参考 |
| valid/test 热度泄漏 | 构建输入仅 `item_frequency_train.jsonl`；valid/test 只用于 evaluation report |
| smoke 误晋升 | smoke manifest `candidate_generation_allowed=false`，文档声明不可作为效果依据 |
| 热门挤占长尾/个性化 source | 保留 source budget 建议，formal 长尾 Recall@500=0.0 作为 blocker 证据 |
| route gate 证据不足 | 用户已确认本路直接并入主路；并入口径限定为 budgeted fallback/backfill source，仍保留 source budget 与非排序替代约束 |

## 下一步

1. 主路运行时按 fill order 将 `popular` 放在后置 backfill 位置，并用 source budget 控制占比。
2. 若 popular source share 过高，应补强 category/semantic/CF 等非 popular source，而不是提升 popular 权重。
3. 后续可做 recent-popular、category-popular 或 time-decay-popular challenger，但必须使用同一 train-only formal protocol 对照。

## 专项优化 Agent 调用说明

后续单独优化本方法时，目标应是控制主路中 popular fallback 的预算占比、重复率和长尾挤占风险，而不是把热门兜底包装成个性化召回。Agent 必须保持 train-only governance，不得把 popular 兜底覆盖解释为整体 pool500 final ready、ranking input replacement 或 pool1000 权限。
