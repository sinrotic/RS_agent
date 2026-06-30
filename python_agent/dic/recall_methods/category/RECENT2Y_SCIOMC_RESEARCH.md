# category recent-2y SciOMC 调研

日期：2026-06-03

## 1. 调研结论摘要

`category` 在 pool500 recent-2y 重建中应定位为**轻量、稳定、可解释的类目偏好 / fallback 覆盖召回**，而不是强个性化主力召回或排序替代。它的价值来自：

1. train-only item taxonomy / category metadata 可以为中低行为用户提供可解释候选。
2. 用户历史 item 映射到类目画像后，可用类目内 train popularity 生成弱个性化候选。
3. 对行为稀疏、协同信号不足的用户，category 比重 CF/embedding 召回更稳。
4. 主要风险是类目字段噪声、热门类目过度曝光、与 popular 高重叠、以及用 coverage 误包装成高 Recall 方法。

因此本项目采用：

- 输入只来自 `recent_2y_1m_3m` train-visible 数据和 `train_only_governance`。
- `smoke` 只验证 schema / path / gate / 非零候选。
- `formal` 用 train-only 用户类目画像 + train-only category top buckets 构建 source artifact，并用 eval label 只做离线指标。
- 允许作为 category source 的 READY artifact，但不允许 ranking input replacement、pool1000 自动晋升或单方法主路硬并。

## 2. 论文与工业最佳实践补充

> 说明：ACM / Springer 页面在当前环境多次 403 或重定向，Exa 搜索也超时；本节以可访问的 Google ML 文档、arXiv 页面和经典论文题录知识为基础，强调对本项目的工程启发，而不是逐篇复述全文。

### 2.1 两阶段推荐与 candidate generation

- **Deep Neural Networks for YouTube Recommendations, 2016**：YouTube 工业实践强调推荐系统先做大规模 candidate generation，再做 ranking。对本项目的启发是：category source 应是召回候选源之一，目标是扩大可排序候选池，而不是直接决定最终排序。
- **Google ML Recommendation Candidate Generation / Retrieval 文档**：Google 将 candidate generation 定义为推荐第一阶段，强调 retrieval 与 ranking 分离；候选生成需要多源覆盖和可扩展检索，而最终排序交给后续模型。对 `category` 的启发：类目桶可以作为轻量 retrieval source，manifest 中必须明确 `ranking_input_replacement_allowed=false`。
- **Amazon.com Recommendations: Item-to-Item Collaborative Filtering, 2003**：Amazon 工业经典强调可扩展候选生成和离线预计算。虽然它主要是 item-to-item CF，但工程启发适用于 category：候选源应可离线构建、可缓存、可审计，并保持与 ranking 层边界清晰。

### 2.2 内容 / taxonomy / category 用户画像

- **Toward the Next Generation of Recommender Systems, 2005** 和 **Content-Based Recommendation Systems, 2007**：传统内容推荐强调从 item 内容特征构造用户 profile，特征可包括 title、category、taxonomy、品牌等。对本项目的启发是：category profile 应由用户 train 历史 item 的 metadata 聚合而来，而不是读取 eval label。
- **Deep Learning based Recommender System: A Survey and New Perspectives, 2017/2019**：综述指出深度模型可以学习特征表示，但本轮 `category` 不应复杂化为深度模型；它更适合作为可解释、轻量、低资源的 metadata source。
- **Neural Collaborative Filtering, 2017**：NCF 强调隐式反馈下的非线性 user-item 交互建模。它对本轮 category 的直接帮助有限，但提醒我们不要把 category 当成 CF 主力；category 的优势在冷启动和 metadata fallback。

### 2.3 Popularity fallback 与偏置控制

- **Managing Popularity Bias in Recommender Systems with Personalized Re-ranking, 2019**：论文指出推荐系统容易过度曝光热门 item，需要在准确率之外监控长尾覆盖和曝光平衡。对本项目的启发：category / popular source 不能只看 Recall@K，还要看 category bucket 分布、top category share、long-tail / popular overlap。
- Google 文档也提示相似度和检索设计会影响热门 item 曝光。对 `category` 来说，类目内热门会天然偏向大类目和高频 item，因此 gate 中需要记录：单类目占比、category diversity、与 popular overlap、用户桶覆盖。

## 3. 数据质量条件

`category` 最依赖以下数据条件：

1. `canonical_items.jsonl` 中 `main_category`、`categories_flat`、`category` 可解析。
2. `recall_views/category_top_items.jsonl` 已基于 train popularity 构建，不能包含 valid/test 热度。
3. 用户 train 序列中最近正反馈 item 能映射到 item metadata。
4. 稀疏类目需要 fallback 到 train-only 全局 main category buckets。
5. 类目桶必须设置最小 item 数，避免噪声类目生成空候选或极窄候选。

本轮 recent-2y 现状：

- `train_only_governance` 为 PASS。
- train item universe：864,288 items。
- recent-2y lightweight recall views 已包含 `category_recall_items` 和 `category_top_items`。
- category top bucket 原始 1,605 个，formal 中保留 1,363 个（最小 5 item），丢弃 242 个稀疏桶。

## 4. 类目字段清洗与层级选择

推荐策略：

1. 优先使用 `main_category` 作为粗粒度稳定桶。
2. 同时保留 `categories_flat` 的 path bucket，提升细粒度覆盖。
3. 对每个用户只保留 top-N profile buckets，避免长历史用户被过多弱类目稀释。
4. 对每个 bucket 设置 per-user cap，防止单类目垄断候选。
5. 对 item 数少于 `category_min_item_count` 的 bucket 不生成 formal 候选，转 fallback。

本轮实现策略：

- `main::<main_category>` + `path::<categories_flat item>` 双层 bucket。
- `category_min_item_count=5`。
- formal：`max_profile_buckets=6`，`category_bucket_cap_per_user=20`，`per_user=80`。
- smoke：更小的 500 用户 / per_user 40 / bucket cap 12。

## 5. 用户类目画像与候选生成

用户画像构建：

1. 从 `user_sequences.train.jsonl` 读取 `recent_positive_item_sequence`；若无 positive，则退到 `recent_item_sequence`。
2. 只取最近 `seed_window=20` 个 seed item。
3. 每个 seed item 映射到 `main::` 和 `path::` 类目桶。
4. 使用 `1/sqrt(offset)` 作为近期权重，越近权重越高。
5. 输出 `user_category_profile.jsonl`，记录每个用户的 top profile buckets、seed 命中数和权重。

候选生成：

1. 对每个用户按 profile bucket 顺序读取 `category_top_items`。
2. 排除用户 train 历史 item。
3. 按 train popularity / recent popularity / profile weight 合成分数。
4. 每个 bucket 限制候选数，每用户限制总候选数。
5. profile 为空或类目不可解析时，退到 train-only global main category buckets。

## 6. smoke / formal dataset 设计

### smoke

- 目标：程序、schema、path gate、manifest/audit 验证。
- 用户：500 个 train-only eligible 用户。
- 候选：每用户最多 40。
- 必须写入：`purpose=program_and_schema_validation_only`，`promotion_allowed=false`。
- 不用于正式效果结论。

### formal

- 目标：recent-2y train-only category source 正式方法逻辑 artifact。
- 本轮本地 formal：50,000 个 train-only eligible 用户；不是全 1.56M eligible route artifact。
- 候选：每用户最多 80。
- 用途：证明 category source 的构建链路、coverage、用户桶分层和弱召回效果。
- 限制：全量主路并入仍需 global route gate / server batch 重新计算 overlap、merge 和 route 贡献。

## 7. 评估建议与本轮结果

指标应同时覆盖：

1. Recall@20/50/80：验证纯 category 对 eval positives 的命中能力。
2. 用户覆盖率：category 是否能为目标用户生成候选。
3. 候选数分布：min/p50/p90/max，避免大量空用户。
4. 用户桶分层：fallback_only、sequence_sufficient、collaborative_rich 等。
5. category diversity：每用户 distinct category、max category share。
6. item/category 覆盖：unique item、category bucket top share。
7. popular overlap：留给全局 route gate 统一评估。

本轮 formal 50k 结果：

- `candidate_row_count=3,976,451`
- `target_user_count=50,000`
- `user_coverage_ratio=1.0`
- `unique_item_count=7,944`
- per-user candidates：min 20 / p50 80 / p90 80 / max 80
- valid Recall@80：0.012225
- test Recall@80：0.010989

解释：category 覆盖稳定，但纯 category Recall 弱。它应该保留为 fallback/coverage source，不应作为 ranking replacement 或单独主路晋升证据。

## 8. 失败模式与 gate

常见失败模式：

1. **类目噪声**：metadata 类目为空、过粗或错分，导致 profile 弱相关。
2. **热门偏置**：大类目 top items 占比过高，与 popular 重叠。
3. **长尾不足**：类目内热门召回覆盖稳定但不利于长尾发现。
4. **评估泄漏**：用 valid/test item 或 label 构建类目 profile / top bucket。
5. **错误晋升**：用 smoke 或 coverage 结果宣称 final pool500 ready。

Gate 建议：

- `no_holdout_audit.status == PASS`
- `candidate_generation_allowed=false` 直到全局 route gate 批准
- `ranking_input_replacement_allowed=false`
- smoke 不允许效果宣称
- formal 必须记录 lineage/hash 和 eval-only label policy
- 若 Recall@K 弱但 coverage 强，应写成 fallback 价值，不写成主力召回提升
- 全局并入前必须重新计算 popular/category overlap、source contribution、route merge underfill 和 pool500 route gate

## 9. 对本项目的执行建议

1. 保持 `category` 为 READY source artifact，但状态语义是“train-only category coverage/fallback source ready”，不是“主路已并入”。
2. 50k local-formal artifact 可作为单方法完成证据；全量 route artifact 因输出规模较大，交给后续 global route gate / server batch。
3. 后续优化重点不是训练模型，而是：
   - 类目层级权重；
   - popular overlap 降低；
   - fallback_only 用户覆盖；
   - top category share 和长尾 bucket exposure 控制。

## 参考来源

- Google Machine Learning Recommendation — Candidate Generation: https://developers.google.com/machine-learning/recommendation/overview/candidate-generation
- Google Machine Learning Recommendation — Retrieval: https://developers.google.com/machine-learning/recommendation/dnn/retrieval
- He et al., Neural Collaborative Filtering, 2017: https://arxiv.org/abs/1708.05031
- Zhang et al., Deep Learning based Recommender System: A Survey and New Perspectives, 2017/2019: https://arxiv.org/abs/1707.07435
- Abdollahpouri et al., Managing Popularity Bias in Recommender Systems with Personalized Re-ranking, 2019: https://arxiv.org/abs/1901.07555
- Linden, Smith, York, Amazon.com Recommendations: Item-to-Item Collaborative Filtering, 2003: https://www.cs.umd.edu/~samir/498/Amazon-Recommendations.pdf
