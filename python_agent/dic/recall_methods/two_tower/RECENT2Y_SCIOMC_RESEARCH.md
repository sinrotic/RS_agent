# two_tower recent-2y SciOMC 调研

日期：2026-06-02

## 1. 调研结论摘要

`two_tower` 在本轮 pool500 recent-2y 重建中应定位为 **embedding / ANN 召回候选源**，而不是直接替代 ranking input。它的核心价值是把用户历史序列和 item 表征映射到同一向量空间，再用向量检索补充协同过滤、热门和类目召回覆盖不到的相似 item。

本项目当前治理边界决定了：

- 训练、item universe、负采样和 source index 构建只能读取 `recent_2y_1m_3m` 的 train-visible 输入与 `train_only_governance/*`。
- valid/test/holdout/LOPO/oracle/eval label 只能在评估阶段读入，不能进入训练、负采样、item vocab 或 index 构建。
- smoke 只验证 schema、训练入口、embedding/index 查询链路和无泄漏审计，不能作为正式效果结论。
- formal 数据集可作为训练/构建输入依据；但 formal 训练和 ANN/source artifact 属于重资源任务，完整执行应优先 server 远程。

## 2. 论文与工业实践证据

| 方向 | 代表论文/实践 | 对本项目的启发 |
|---|---|---|
| 两阶段推荐与候选生成 | Covington et al., **Deep Neural Networks for YouTube Recommendations**, RecSys 2016（Google Research: https://research.google/pubs/deep-neural-networks-for-youtube-recommendations/） | 工业推荐通常拆为候选生成和排序两阶段；two_tower 只应承担候选生成 source，不应直接宣称 ranking replacement。 |
| 双塔/语义检索基本范式 | Huang et al., **Learning Deep Structured Semantic Models for Web Search using Clickthrough Data**, CIKM 2013（Microsoft Research: https://www.microsoft.com/en-us/research/publication/learning-deep-structured-semantic-models-for-web-search-using-clickthrough-data/） | query/user tower 与 document/item tower 映射到共享低维空间，点击/交互监督可驱动向量召回；本项目可把用户历史序列作为 query tower 输入。 |
| 负采样与采样偏差 | **Sampling-Bias-Corrected Neural Modeling for Large Corpus Item Recommendations**（WebFetch 摘要：随机 batch negatives 在偏斜 item 分布下有 sampling bias，需考虑 item 频率校正） | recent-2y item 长尾明显，负采样不能只固定少量热门；manifest 中必须记录负采样 universe、频率来源、power/ratio，并报告负样本覆盖和 top item 集中度。 |
| 隐式反馈 pairwise 学习 | Rendle et al., **Bayesian Personalized Ranking from Implicit Feedback**, UAI 2009 / arXiv: https://arxiv.org/abs/1205.2618 | 对隐式反馈，训练目标应强调“已交互 item 排在未交互 item 前”，负样本选择本身是训练信号；本项目样本合同应保证 target 来自 train 正反馈，negative 排除用户历史和 target。 |
| 多兴趣用户表示 | Li et al., **MIND: Multi-Interest Network with Dynamic Routing for Recommendation at Tmall**, CIKM 2019 / arXiv: https://arxiv.org/abs/1904.08030 | 单向量用户塔会压缩多兴趣用户；本阶段可先用单向量 YouTubeDNN smoke/formal，后续若 medium/heavy 用户多兴趣明显，再扩展多向量 query。 |
| 大规模向量检索 / ANN | Johnson et al., **Billion-scale similarity search with GPUs**, FAISS / arXiv: https://arxiv.org/abs/1702.08734 | two_tower 产物不是只有模型文件，还必须把 vector index 作为可评估 artifact，记录 item count、build/search 资源、Recall@K 与速度。 |
| MIPS/向量量化索引 | **Accelerating Large-Scale Inference with Anisotropic Vector Quantization**, ScaNN（Google Research: https://research.google/pubs/accelerating-large-scale-inference-with-anisotropic-vector-quantization/） | ANN index 评估应看 top inner-product retrieval 保真，不只看向量重构误差；未来 formal index 应比较 exact/ANN 的召回保真、内存和延迟。 |
| 图表示与 hard cases | Ying et al., **PinSage: A Graph Convolutional Neural Network for Web-Scale Recommender Systems** / arXiv: https://arxiv.org/abs/1806.01973 | 说明大规模召回可结合图邻域、hard examples 和离线批量推理；two_tower formal 评估应与 ItemCF/Swing overlap 对比，而不是孤立看 raw recall。 |

## 3. 本项目数据适配判断

### 3.1 用户侧

`train_only_governance/manifest.json` 显示：

- `eligible_for_two_tower=687147`。
- v2 桶：`sequence_sufficient=637338`、`collaborative_rich=49719`、`medium_behavior=90`。

因此 two_tower 的 formal 数据集应覆盖 `sequence_sufficient + collaborative_rich + medium_behavior`，而不是只训练极少数 heavy 用户。低行为/冷启动用户仍应由 popular/category/fallback 承担。

### 3.2 item 侧

recent-2y train-only item universe：

- train item 总数：864288。
- `embedding_ready=335024`。
- min_freq≥3 universe：335032，覆盖约 94.08% train 正反馈事件。

本阶段建议：

- **负采样 universe**：优先使用 `item_quality_profile` 中 `embedding_ready` 与 `item_frequency_train` join 后的 train-only item。
- **训练 item universe**：`negative_universe + sampled train positive targets`，避免把部分 train target 因不在 embedding_ready 中而从正样本中误删。
- **检索 item universe**：formal source artifact 需要单独冻结，不能把 smoke vocab 或旧 full-data vocab 当 current formal universe。

## 4. smoke/formal 数据集设计建议

### smoke

用途：程序与 schema 验证。

建议合同：

- 输入：recent-2y train-only governance、`user_sequences.train.jsonl`、`canonical_items.jsonl`。
- 规模：小样本，如 500-1000 用户或 ≤2 万训练样本。
- target：同一 train 序列中 `history_before_target_time -> target_item`。
- negative：从 train-only `embedding_ready` universe 采样，排除用户历史和 target。
- manifest 必须写入 `candidate_generation_allowed=false`、`promotion_allowed=false`、`ranking_input_replacement_allowed=false`。

### formal

用途：正式方法数据集与后续重资源训练输入。

建议合同：

- 输入仍只来自 train-visible 数据。
- 不使用旧 `local_formal` 小 cap；formal 不在方法侧写死小样本上限。
- 记录 `eligible_user_count`、`train_sample_count`、negative universe、training item universe、target coverage、input/output hash。
- 保留 `label_artifacts/oracle_artifacts` 只能 diagnostic eval、不能用于训练/负采样/index build 的 data usage boundary。

## 5. 训练与 source artifact 建议

- 模型：当前阶段使用 `youtube_dnn_two_tower_v1`，embedding_dim=32 起步，保守训练 1-3 epoch。
- 负采样：记录 `negative_samples`、`negative_sampling_power`、negative universe 来源、负样本覆盖率、top10 share。
- 资源：smoke 可本地 `.venv` 跑；formal 训练/全量 embedding/ANN 构建应优先 server 远程，并限制 batch、记录 progress log、拉回 manifest/stats/eval。
- source artifact：必须包含 artifact manifest、item/user embeddings、recall index、source_index_manifest，并由 manifest 校验 row_count、hash、权限位。
- 默认权限：formal 未通过评估前 `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`promotion_allowed=false`。

## 6. 评估建议

formal source artifact 的评估至少包含：

1. Recall@20/50/100/500 与 hit-rate。
2. candidate rows、用户覆盖率、underfilled user rate。
3. 用户桶分层：medium、sequence_sufficient、collaborative_rich。
4. in-universe denominator：单独报告 eval positives 中有多少落入 retrieval item universe。
5. source overlap：与 popular/category/ItemCF/Swing 的 overlap、新增覆盖、独有命中。
6. 资源指标：训练秒数、GPU/显存、index size、search latency/QPS。

## 7. 失败模式与 gate

| 失败模式 | gate |
|---|---|
| 旧 full-data artifact 回流 | 所有 manifest 必须指向 recent-2y train-only hash；旧路径只能写为 historical reference。 |
| eval label 泄漏 | 训练、负采样、item vocab、source index read paths 不得包含 valid/test/holdout/LOPO/oracle/eval label。 |
| smoke 被当正式效果 | smoke manifest 必须写 `promotion_allowed=false`，METHOD 中明确 smoke 仅链路验证。 |
| item universe 过窄导致 Recall@K 失真 | formal 评估报告 in-universe denominator 和 missing positive rate。 |
| 负采样被热门 item 主导 | 报告 used_negative_distinct_item_count、coverage ratio、top1/top10 share。 |
| ANN 指标不足 | 未完成 exact/ANN 保真、速度、资源评估时不得晋升 READY。 |
| 与主路缺少互补性 | 未提供 source overlap / 独有命中证据时保持 `DIAGNOSTIC_ONLY` 或 `DEFERRED`。 |

## 8. 当前阶段适配结论

本轮 two_tower 可以完成 recent-2y smoke/formal **方法数据集**与 smoke source 链路验证；但 formal 训练和 ANN/source artifact 属于重资源项，应通过 server 远程执行。若本地只完成 smoke source 和 formal dataset，而缺少 formal Recall@K/overlap/route gate，则不应把 `two_tower` 晋升为 READY。当前更合理状态是 `FORMAL_DATASET_READY_SOURCE_BLOCKED` 或 `DIAGNOSTIC_ONLY`。
