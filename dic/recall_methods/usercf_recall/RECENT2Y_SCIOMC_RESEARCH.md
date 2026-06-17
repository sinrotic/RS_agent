# usercf_recall recent-2y SciOMC 调研摘要

日期：2026-06-03

## 1. 调研目标

本调研服务于 pool500 recent-2y 召回方法重建中的 `usercf_recall` 单方法窗口。目标不是重新解释 UserCF 算法原理，而是把隐式反馈 UserCF 在推荐召回中的最佳实践落到本项目的 train-only governance、smoke/formal 双层数据集、source artifact 构建和晋升门禁上。

当前边界：

- 当前数据基础：`data/processed/amazon_2023_recall_recent_2y_1m_3m/`
- train-only governance：`data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json`
- 当前方法状态：`DIAGNOSTIC_ONLY`
- 禁止把旧 full-data artifact、holdout/valid/test/LOPO/eval label/oracle/pool1000 作为候选生成或训练输入。

## 2. UserCF 对数据质量的核心依赖

UserCF 基于“用户之间共享正反馈 item”推断相似用户，再从相似用户历史中扩展候选。它对数据质量的依赖比热门、类目、ItemCF 更敏感：

1. **用户行为数量必须足够**：低行为用户只有 1-2 个正反馈时，共享 item 很容易只是偶然重合，Jaccard/cosine 等相似度不稳定；因此本项目不应强行覆盖 cold/fallback 用户。
2. **共享 item 必须有区分度**：如果共享关系主要由超热门 item 连接，邻居看似很多但个性化信号很弱，会产生热门候选堆叠。
3. **item 频次需要约束或降权**：高频 item 应被 cap、drop 或 IUF/IDF 降权；低频但只出现一次的 item 又难以形成可靠邻居，应通过 item quality/profile 区分。
4. **用户序列需要去重和清洗**：同一用户重复 item、空 item、非法 item、过长序列都会放大噪声和资源成本；构图前应保留 first unique item 序列，并记录 dropped reason。
5. **时间窗必须一致**：相似用户、共享 item 和候选扩展都应只来自 recent-2y train-visible 数据；valid/test/holdout 只能用于后续评估。

结合 governance 当前画像：train users `6,826,801`，`collaborative_rich=49,719`，但 UserCF recent-2y formal 在 cf-ready/non-over-hot 过滤后实际输出 `15,884` 个可训练用户。这说明 UserCF 适合作为 heavy/collaborative-rich 用户的诊断或补充源，而不是全用户主力召回源。

## 3. 数据预处理建议

### 3.1 用户过滤

推荐策略：

- 主要使用 `collaborative_rich` / `heavy_cf_eligible` 用户。
- 可在分析中保留 `sequence_sufficient` 的覆盖画像，但 formal 训练/构建不要默认把低行为用户纳入 UserCF。
- 每个目标用户至少需要足够正反馈 item 和可形成共享 item 邻居的 item 序列。
- 记录被过滤用户原因，例如：`user_bucket_not_allowed`、`no_cf_ready_non_over_hot_items`、`insufficient_positive_items`、`no_neighbor_overlap`。

### 3.2 item 过滤与热门控制

推荐策略：

- 使用 train-only `item_frequency_train.jsonl` / `item_quality_profile.jsonl`。
- 优先保留 `cf_ready=true` 且非 over-hot 的 item。
- 对超热门 item 做 cap/drop；如果保留，应采用 IUF/IDF 或 BM25-like 降权，避免热门 item 主导用户相似度。
- 同时报告被 drop 的 hot item 数量与原因，避免静默改变 item universe。

### 3.3 序列清洗

推荐策略：

- 构图前对用户正反馈序列做 first-unique 去重。
- 丢弃空 item、非法 item、空序列、无 eligible sequence 行。
- 限制 smoke 的 `max_items_per_user`，formal 可按资源策略放宽，但必须记录上限语义和实际统计。

## 4. 相似度与候选扩展实践

### 4.1 相似度选择

可选方案：

- **Jaccard**：直观、抗用户长度差异，但对热门 item 仍敏感；适合 smoke 或 baseline 对照。
- **cosine**：常用隐式反馈相似度，适合二值用户-item 向量；对行为长度归一化较好，但仍需要热门 item 控制。
- **IUF/IDF 加权 cosine**：对高频 item 降权，更适合本项目大规模 Amazon 行为数据，可减少热门 item 导致的伪相似。
- **BM25-like**：通过 item IDF 与用户长度归一化控制长序列用户和热门 item 的影响，适合作为 formal 方向，但实现和解释成本高于简单 cosine。

本项目当前实现侧更接近“共享 item 邻居 + hot item cap + 候选排序”的工程化 UserCF。近期重建优先保证 train-only、可复核和资源受控；若后续要晋升 READY，再考虑把 IUF/BM25-like 权重显式固化为可对比实验。

### 4.2 邻居与候选扩展

推荐策略：

- smoke：`similar_users_top_k` 小而固定，例如 50；候选 topK 用于验证链路，不代表正式效果。
- formal：允许更大邻居数，例如 200；但需要记录实际邻居分布、候选数分布和 undercoverage reason。
- 候选生成必须去除目标用户 train 已交互 item。
- 候选排序应结合相似用户分数、item 出现次数、热门惩罚；至少保证 deterministic tie-break。
- 对 candidate underfill 用户单独审计，避免只看总体 candidate_total_count。

## 5. smoke/formal 数据集设计

### 5.1 smoke dataset

目的：验证 schema、路径、manifest、source builder、no-holdout gate 和候选非零链路。

建议 contract：

- 输入只来自 train-only governance、`user_quality_profile.jsonl`、`item_quality_profile.jsonl`、`item_frequency_train.jsonl`、`user_sequences.train.jsonl`。
- 用户来自 `heavy_cf_eligible` / `collaborative_rich` 的小样本。
- 规模按实际 eligible 用户比例采样，不能作为正式效果结论。
- 产物必须包含 `method_dataset_manifest.json`、`method_dataset_rows.jsonl`、input hash、过滤规则、forbidden scope audit。
- 必须写明 `candidate_generation_allowed=false`、`promotion_allowed=false`、`ranking_input_replacement_allowed=false`。

当前已存在 smoke method dataset：

`outputs/recall/pool500_method_datasets/recent_2y/usercf_sciomc_v1/smoke/usercf_method_dataset/method_dataset_manifest.json`

已记录：`row_count=995`，`user_count=995`，`item_count=1364`。

### 5.2 formal dataset

目的：作为 recent-2y train-only 口径下的正式方法数据集，用于构建 source artifact 和评估 UserCF 是否有补充价值。

建议 contract：

- 使用实际 eligible 用户全集，不复用旧 `smoke/diagnostic/local_formal` 固定 cap。
- 保留完整 lineage、input hash、过滤规则和 dropped reason。
- 不读取任何 valid/test/holdout/LOPO/eval label/oracle。
- formal 结果可以用于方法效果评估，但不自动意味着 READY、ranking input replacement 或 pool1000。

当前已存在 formal method dataset：

`outputs/recall/pool500_method_datasets/recent_2y/usercf_sciomc_v1/formal/usercf_method_dataset/method_dataset_manifest.json`

已记录：`row_count=15884`，`user_count=15884`，`item_count=19595`。

## 6. source artifact 构建与资源控制

UserCF formal 构建属于重资源任务，建议采用：

- 本地先跑 smoke source 构建，验证 `.venv`、schema、loader、no-holdout audit。
- formal 若估计内存/耗时可控，可本地分批运行；否则迁移到 server 执行并拉回 manifest、stats、评估报告和必要 artifact。
- 必须设置：`target_batch_size`、`shard_count`、`max_rss_mb`、`min_free_bytes` 或等价资源门禁。
- 启用 checkpoint/resume，避免中断后重跑全图。
- 输出至少包含：`source_index_manifest.json`、`readiness_contract.json`、`candidates.jsonl`、candidate shards、`coverage_audit.json`、`undercoverage_audit.json`、`resource_audit.json`、`no_holdout_audit.json`。

当前 source builder 入口：

`rs_lab/experiments/recall/pool500/methods/usercf_recall/builder.py`

构建后仍应默认保持 `DIAGNOSTIC_ONLY`，除非 route gate 和 formal 证据充分；本窗口不自动晋升主路。

## 7. 评估与门禁

formal source artifact 至少需要报告：

- Recall@K 或 recall-only 评估指标。
- 用户覆盖率：candidate_user_count / target_user_count。
- 候选数分布：min / p50 / p90 / max。
- 用户桶分层：heavy/collaborative-rich 内覆盖，medium/cold 只报告不强行纳入。
- undercoverage reason：无邻居、只剩已看 item、hot item drop 后无索引 item 等。
- source overlap：与 popular/category/swing/itemcf 等已 READY 或候选方法的重叠与新增候选比例。
- item universe 内分母：如果 item 过滤限制了可召回物品，需要单独报告 universe 内 recall，避免把不可召回 item 算成方法失败或反向夸大效果。
- 资源成本：峰值 RSS、批次数、shard 数、运行时、candidate_total_count。
- no-holdout audit：确认构建阶段未读取 forbidden scopes。

## 8. 常见失败模式

1. **低行为用户伪相似**：cold/fallback 用户因为共享 1 个热门 item 被错误扩展。
2. **热门 item 主导**：候选主要来自头部 item，source overlap 高、边际贡献低。
3. **underfill 严重**：formal 大量用户没有候选，说明 UserCF 在当前过滤策略下覆盖不足。
4. **路径/配置漂移**：METHOD、dataset_policy、source_config、registry 指向不同 artifact，导致不可复核。
5. **旧 artifact 回流**：旧 full-data 或 route_ready 命名产物被误当 recent-2y 结论。
6. **smoke 误晋升**：只用 smoke 非零候选声称方法 ready。
7. **评估泄漏**：valid/test/holdout/LOPO/eval label 参与候选生成或训练。

## 9. 晋升建议

本轮默认结论应谨慎：

- 如果 formal 只证明 source 可构建，但覆盖、Recall@K、source overlap 或资源成本证据不足，应保持 `DIAGNOSTIC_ONLY`。
- 只有在 formal 评估证明对 heavy/collaborative-rich 用户有稳定补充价值，并通过 source loader、candidate merge、route gate 与 no-holdout audit 后，才建议进入 `POOL500_RECALL_ONLY_SUPPLEMENTAL_READY` 候选。
- 即使进入 supplemental ready，也不等于 `ranking_input_replacement_allowed=true`、`pool1000_allowed=true` 或 final pool500 ready。

## 10. 论文依据补充

本轮外部检索通道曾出现超时、403、429，因此这里先沉淀可复述的经典论文依据清单；后续如需要正式论文链接，可再用学校/公司网络或 Semantic Scholar / ACM / IEEE 页面补 DOI/URL。以下论文不作为“照搬实现”的依据，而是用于支撑本项目 UserCF 重建中的数据清洗、热门惩罚、implicit feedback 与评估门禁。

| 论文/资料 | 核心观点 | 对本项目 `usercf_recall` 的落地含义 |
| --- | --- | --- |
| Resnick et al., 1994, *GroupLens: An Open Architecture for Collaborative Filtering of Netnews* | 早期 user-based collaborative filtering 系统，强调用户邻居和相似用户投票。 | 支撑 UserCF 的基本定位：基于相似用户历史扩展候选；但现代大规模隐式反馈下必须补充过滤、降权和资源门禁。 |
| Herlocker et al., 1999, *An Algorithmic Framework for Performing Collaborative Filtering* | 系统比较邻居选择、相似度、归一化与推荐生成环节。 | 支撑把 UserCF 拆成“用户过滤 → 相似度 → 邻居 topK → 候选扩展 → 评估”的可审计 pipeline，而不是只看最终候选。 |
| Sarwar et al., 2001, *Item-Based Collaborative Filtering Recommendation Algorithms* | 虽然重点是 ItemCF，但系统讨论 kNN CF 的相似度、稀疏性和在线计算成本。 | 对 UserCF 的反向启发：用户数远大于 item 时，UserCF 更容易受资源和稀疏性影响，因此 formal 必须有 shard/batch/memory guard。 |
| Deshpande & Karypis, 2004, *Item-Based Top-N Recommendation Algorithms* | Top-N 推荐不只看评分预测，而要面向候选排序、支持度和覆盖。 | 支撑本项目 formal 阶段必须报告 Recall@K、candidate coverage、候选数分布和 undercoverage，而不能只说 source 可生成。 |
| Hu, Koren & Volinsky, 2008, *Collaborative Filtering for Implicit Feedback Datasets* | 隐式反馈缺少显式负反馈，需要区分 preference 与 confidence，并重视行为频次/置信度。 | 支撑本项目只把 train 正反馈用于构图，不把未交互当强负样本；同时用用户行为数、item 频次和质量桶控制置信度。 |
| Koren, 2008, *Factorization Meets the Neighborhood: a Multifaceted Collaborative Filtering Model* | 邻域方法和隐因子方法可以互补，邻域信号强调局部相似与可解释性。 | 支撑 UserCF 在 pool500 中更适合作为 heavy 用户的 supplemental source，而不是替代排序或 embedding 主路。 |
| Rendle et al., 2009, *BPR: Bayesian Personalized Ranking from Implicit Feedback* | Top-N 隐式反馈推荐应按排序目标评估，而不是只优化评分重建。 | 支撑 formal 指标要面向 Recall@K / rank quality；但 BPR 是训练型排序/召回思路，本窗口不把 eval label 注入 UserCF 候选生成。 |
| Cremonesi et al., 2010, *Performance of Recommender Algorithms on Top-N Recommendation Tasks* | Top-N 推荐评估中候选集构造、热门 item 和采样策略会显著影响结论。 | 支撑本项目必须区分 full denominator 与 item-universe 内 denominator，避免因 item 过滤或热门偏置误读 Recall。 |
| McNee, Riedl & Konstan, 2006, *Being Accurate is Not Enough* | 推荐系统只看 accuracy 不够，还需要覆盖、新颖性、多样性和用户体验指标。 | 支撑 route gate 不能只看 Recall@K；还要看 coverage、source overlap、长尾/热门偏置和边际新增候选。 |
| Adomavicius & Kwon, 2012, *Improving Aggregate Recommendation Diversity Using Ranking-Based Techniques* | 推荐列表可能被头部 item 垄断，需要关注 aggregate diversity。 | 支撑对 UserCF 热门 item 主导风险设置 gate：如果新增候选高度集中在头部且与 popular/source overlap 高，不应晋升 READY。 |
| Steck, 2011/2018 相关工作：popularity bias / calibrated recommendation | 推荐结果容易向流行物品偏置，准确率和校准/多样性之间存在张力。 | 支撑 UserCF 的 hot item cap、IUF/IDF 降权和 source overlap 审计；尤其防止共享热门 item 造成伪邻居。 |
| Robertson & Sparck Jones BM25 / TF-IDF 系列信息检索权重 | 高频词需要 IDF 降权，文档长度需要归一化。 | 作为 BM25-like UserCF 的方法类比：把 item 看作 token、用户历史看作 document，可用 IDF/IUF 和长度归一化抑制热门 item 与超长用户序列。 |

### 10.1 论文调研转成工程约束

1. **IUF/IDF / BM25-like 的位置**：本轮不强行改算法核心，但将其作为 formal 后续优化方向；当前至少通过 `max_item_user_freq=5000`、`cf_ready/non-over-hot`、dropped hot item audit 控制热门 item。
2. **kNN 邻居数不是越大越好**：论文中邻域方法通常需要在覆盖、噪声和计算成本之间折中；本项目 smoke 使用较小 `similar_users_top_k=50`，formal 使用 `similar_users_top_k=200`，并报告邻居/候选分布。
3. **implicit feedback 不能偷看评估标签**：Hu/Koren/Volinsky 与 BPR 系列强调隐式反馈排序，但本项目治理边界更严格：eval label 只用于评估，不参与 source index 或候选生成。
4. **Top-N 评估要防采样误读**：Cremonesi 等工作提示候选集和负采样会影响结论；因此本项目需要同时报告 full denominator、item-universe denominator、用户桶分层和 source overlap。
5. **准确率之外的晋升门禁**：McNee、Adomavicius/Kwon、popularity bias 相关工作支持把 coverage、diversity、popularity concentration、overlap 纳入 route gate。

## 11. 本项目落地判断

当前 `usercf_recall` 已具备 recent-2y method dataset 基础，但配置和 registry 仍存在路径不一致与旧 artifact 残留。下一步应优先：

1. 固化 `usercf_sciomc_v1` smoke/formal dataset 为当前事实。
2. 基于 formal method dataset 构建 recent-2y source artifact。
3. 输出 coverage/resource/no-holdout/undercoverage 与评估报告。
4. 更新 `METHOD.md`、`source_config.yaml`、`dataset_policy.yaml` 和 registry，明确仍为 `DIAGNOSTIC_ONLY` 或列出晋升 blocker。
