# Popular recent-2y SciOMC 调研

日期：2026-06-03

## 1. 方法定位

`popular` 是热门与兜底召回源，核心价值不是个性化，而是在冷启动、行为稀疏、重召回无命中或候选池不足时提供稳定覆盖。它适合作为 pool500 主路中的 fallback/backfill source，但不应替代个性化召回、排序输入或 pool1000 晋升依据。

## 2. 最佳实践摘要

1. **严格 train-visible 热度统计**：热门 item 的排序只能来自 train 可见的正反馈频次、用户数和 train-scope metadata。valid/test/holdout/LOPO/oracle/eval label 只能用于评估，不能反向影响候选生成或热度排序。
2. **全局热门先作为基线**：在 recent-2y 重建第一版中，全局 train 热度是最稳定、最容易复核的兜底 baseline；短期热门、类目热门、时间衰减热门可作为后续对照，但不能在没有验证前默认复杂化。
3. **候选去重与 seen 过滤**：source artifact 可保存全局热门序列；实际 per-user candidate 应在 merge/eval 时过滤用户 train seen item，避免给用户推荐训练期已交互物品。
4. **控制热门挤占**：popular 应通过 `popular_per_user_cap`、source share cap、fill order 和 route gate 限制在候选池中的占比，避免把长尾与个性化 source 挤出。
5. **分层评估**：除了 Recall@K，还要报告用户桶（cold_start/fallback_only/sequence_sufficient/collaborative_rich）、覆盖率、候选数、长尾命中和 train item universe 内召回。

## 3. 数据质量依赖

- **item 频次可靠性**：需要 train-only 的正反馈 item 频次，且 `parent_asin` 不为空、频次为正。
- **时间窗口径清晰**：当前正式基础为 `recent_2y_1m_3m`，train 窗口是 2021-06-15 到 2023-05-15；valid/test 不能进入统计。
- **item universe 明确**：候选 item 应来自 train item universe；评估报告需区分 eval positive 是否在 train universe 内。
- **用户桶可用**：`train_only_governance/user_quality_profile.jsonl` 可用于分层报告，但不是 popular 训练输入。
- **metadata 可选**：category/store/brand 可作为解释和后续 category-popular 对照字段，但全局热门排序不依赖 metadata。

## 4. 数据预处理建议

### 4.1 输入

允许输入：

- `data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/item_frequency_train.jsonl`
- `data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json`
- 评估阶段可读 `canonical_interactions.valid.jsonl`、`canonical_interactions.test.jsonl` 和 `user_sequences.train.jsonl`，但只能用于指标计算与 seen filtering，不能改变 source 排序。

禁止输入：holdout、valid/test 作为构建输入、LOPO、oracle、eval label、clean_10000、pool1000、旧 full-data-derived artifact。

### 4.2 清洗与排序

- 过滤 `parent_asin` 为空或 `frequency <= 0` 的 item。
- 以 `(-frequency, parent_asin)` 做 deterministic 排序；如 `user_count` 存在，则记录为审计字段。
- 记录 `category`、`store`、`is_long_tail`，便于覆盖与长尾副作用分析。
- 不引入 eval hit、valid/test 热度、oracle 正样本或人工 label 注入。

## 5. smoke / formal 数据集设计

### smoke

目标：只验证代码路径、schema、manifest、无泄漏和最小候选非零。

建议：

- 输入仍来自 train-only `item_frequency_train.jsonl`。
- 输出 top 500 或等价小规模热门 rows。
- `purpose=program_and_schema_validation_only`。
- `promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。
- 评估用户可限制为 valid/test 前 500 个正样本用户；结果只作为链路 smoke，不作为正式效果。

### formal

目标：构建 recent-2y train-only 正式 popular source artifact。

建议：

- 不做方法侧小 cap，完整读取 train item frequency 统计。
- 输出完整热门序列与 `source_index_manifest.json`。
- 使用 valid/test 评估 Recall@K、hit rate、候选覆盖、用户桶分层、长尾命中、train universe 内召回。
- formal 结果可支持 popular 作为 candidate source 的 fallback evidence，但不自动代表 ranking replacement 或 pool1000。

## 6. source artifact 构建建议

- `method_dataset_manifest.json`：记录 train-only lineage、input hash、row count、过滤规则、scale tier。
- `source_index_manifest.json`：记录 source=`popular`、rank policy、candidate file、candidate_generation_allowed、禁止 ranking/pool1000/promotion。
- `candidates.jsonl`：全局热门候选序列，字段包含 `rank`、`parent_asin`、`score`、`frequency`、`category`、`is_long_tail`。
- `no_holdout_audit.json`：显式记录构建输入未包含 holdout/valid/test/LOPO/oracle/eval label。
- `evaluation_report.json`：评估使用 valid/test label，但声明仅用于指标计算。

## 7. 评估建议

必要指标：

- Recall@10/50/100/500 与 hit rate@K。
- 每用户候选数均值、p50、p95、覆盖率。
- 用户桶分层：cold_start、fallback_only、medium_behavior、sequence_sufficient、collaborative_rich。
- eval positive 是否在 train item universe 内的分母与召回。
- 长尾 positive 命中：popular 对长尾天然弱，应报告而不是掩盖。
- source share / route gate：进入主路时需限制 popular source budget，避免热门挤占。

## 8. 常见失败模式与 gate

| 风险 | 表现 | Gate |
|---|---|---|
| 数据泄漏 | valid/test 热度参与排序 | manifest 只允许 item_frequency_train；no_holdout_audit 必须 PASS |
| 旧 artifact 回流 | latest_artifact 指向 old sidecar/full-data | registry/source_config 必须更新为 recent_2y 路径 |
| smoke 误晋升 | smoke 指标被写成正式效果 | smoke manifest 必须 `promotion_allowed=false` 且文档声明不可作为效果结论 |
| popular 过强 | source share 过高、长尾被挤出 | route gate/source budget 控制；文档保留 blocker |
| 评估口径混乱 | 未区分 train universe 内外 positive | evaluation report 必须报告 in-train-universe 分母 |

## 9. 论文与工业实践补充调研

### 9.1 Popularity baseline 与离线评估

- Cremonesi, Koren, Turrin, *Performance of recommender algorithms on top-n recommendation tasks*（RecSys 2010，DOI: 10.1145/1864708.1864721）。该工作强调 Top-N 推荐评估应关注相关 item 是否进入前 N，并且 simple/popularity baseline 必须作为强参照。对本项目的启示是：`popular` 不能被当成“随便跑的兜底”，需要 formal manifest、固定排序、固定 K 和可复核评估协议。
- Rendle, Zhang, Koren, *On the Difficulty of Evaluating Baselines: A Study on Recommender Systems*（CoRR 2019）。该文指出 baseline 评估本身很容易因实现、调参和协议差异失真。对本项目的启示是：popular formal 评估应和其他召回源共享同一 valid/test、seen filtering、Recall@K 和用户桶口径，不能用特殊口径包装效果。
- Ferrari Dacrema, Cremonesi, Jannach, *Are we really making much progress? A worrying analysis of recent neural recommendation approaches*（RecSys 2019，DOI: 10.1145/3298689.3347058）。该文提醒复杂模型常被弱 baseline 高估。对本项目的启示是：popular 应作为 pool500 召回系统的必要 sanity baseline；如果复杂召回在 formal 上无法明显超过或补充 popular，需要保留 blocker，而不是强行晋升。

### 9.2 热门偏置与长尾风险

- Steck, *Item popularity and recommendation accuracy*（RecSys 2011，DOI: 10.1145/2043932.2043957）。该工作关注 item popularity 对 recommendation accuracy 的影响，说明准确率指标可能被热门 item 放大。对本项目的启示是：popular formal 不应只报告 Recall@K，还要报告长尾命中、item coverage 和 source share，避免热门覆盖掩盖长尾失败。
- Abdollahpouri, Burke, Mobasher, *Controlling Popularity Bias in Learning-to-Rank Recommendation*（RecSys 2017，DOI: 10.1145/3109859.3109912）。该文指出学习排序容易放大热门曝光，挤压长尾和公平性。对本项目的启示是：popular 可做 fallback，但进入主路时必须有 `popular_per_user_cap`、source budget、fill order 和 route gate，不允许在高质量用户上无限挤占个性化 source。

### 9.3 时间感知、时间窗口与泄漏控制

- Koren, *Collaborative filtering with temporal dynamics*（Communications of the ACM 2010，DOI: 10.1145/1721654.1721677）。该文强调用户偏好与 item 受欢迎度都会随时间变化。对本项目的启示是：recent-2y train 窗口比旧 full-data 更适合当前任务；短期/时间衰减热门可以作为 challenger，但必须只用 train 窗口内部时间，不得读取 valid/test 热度。
- Campos, Díez, Cantador, *Time-aware recommender systems: a comprehensive survey and analysis of existing evaluation protocols*（User Modeling and User-Adapted Interaction 2014，DOI: 10.1007/s11257-012-9136-x）。该综述强调 time-aware 推荐不仅是模型加时间特征，更关键是时间切分和评估协议贴近未来预测。对本项目的启示是：`popular` 构建必须使用 train-only 时间窗，valid/test 只能用于评估；manifest 需要记录 train window、input hash 和 forbidden scope audit。
- Alabduljabbar, Alshareef, Alshareef, *Time-Aware Recommender Systems: A Comprehensive Survey and Quantitative Assessment of Literature*（IEEE Access 2023，DOI: 10.1109/access.2023.3274117）。该综述进一步说明时间粒度、数据划分和指标不统一会削弱方法可比性。对本项目的启示是：全局热门、短期热门、时间衰减热门若做对照，必须共用同一 formal evaluation protocol，否则不能作为晋升依据。

### 9.4 冷启动与 fallback

- Schein 等关于 cold-start recommendation 的经典方向，以及后续属性/混合式冷启动研究共同说明：冷启动不应只依赖热门榜单；能用 metadata/profile 时应优先利用属性信号。对本项目的启示是：`popular` 应定位为最后兜底或候选补齐，而不是替代 category、semantic 或后续 Agent 画像召回。
- 近期 hybrid attribute-based cold-start 研究也支持类似判断：属性/画像可缓解纯 cold-start，popular 更适合做最后 fallback。对本项目的门禁是：若 formal 分层显示 cold_start/fallback_only 以外用户大量依赖 popular，应记录为非 popular source 覆盖不足，而不是提高 popular 权重。

### 9.5 对本项目的可执行门禁

1. **baseline gate**：popular formal 必须固定排序规则 `(-frequency, parent_asin)`，并记录 input hash；否则 baseline 不可复现。
2. **temporal gate**：构建输入只能是 train-only item frequency；valid/test label 只进 evaluation report。
3. **bias gate**：formal report 必须包含长尾、coverage、source share 和用户桶分层；不能只看 Recall@K。
4. **fallback gate**：candidate_generation_allowed 可以为 true，但 ranking_input_replacement_allowed、pool1000_allowed、promotion_allowed 保持 false。
5. **comparison gate**：若后续尝试 recent-popular/time-decay-popular/category-popular challenger，必须在同一 formal protocol 下与 global popular 对照。

## 10. 本项目适配判断

当前治理 manifest 已 PASS，且 `item_frequency_train.jsonl` 已按 train-only 正反馈频次给出 864k 级 item universe。`popular` 不需要远程 GPU 或重训练，本地 `.venv` 构建 formal 是合理的。结合论文调研，`popular` 应维持为 READY fallback / sanity baseline source：允许在 recent-2y source artifact 中进行候选生成，但 ranking replacement、pool1000、自动 promotion 仍保持 false，最终主路并入由全局 route gate 决定。
