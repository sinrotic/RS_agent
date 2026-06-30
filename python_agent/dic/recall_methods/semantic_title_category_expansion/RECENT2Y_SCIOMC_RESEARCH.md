# semantic_title_category_expansion recent-2y SciOMC 调研

日期：2026-06-03

## 1. 调研目标

本调研服务于 pool500 recent-2y 单方法重建，只覆盖 `semantic_title_category_expansion`。目标不是证明该 source 已可进入主路，而是在 recent-2y train-only governance 下，明确 title/category 扩展召回的可用数据、构建方式、评估口径和晋升门禁。

强约束：候选生成、source index 构建和方法数据集只允许使用 train-visible 用户历史与 catalog metadata；holdout、valid、test、LOPO、oracle、eval label 只能在评估阶段使用，不能反向参与 token/category 选择、候选生成或训练/索引构建。

## 2. 论文与最佳实践依据

### 2.1 经典候选生成与简单强基线

- **Amazon.com Recommendations: Item-to-Item Collaborative Filtering**（Linden, Smith, York, 2003）强调大规模电商推荐中应把重计算前置为离线 item-item 关系，在线阶段只做快速候选扩展。这给本方法的启发是：title/category expansion 应定位为可解释、低成本的候选补充 source，而不是复杂 reranker 或 oracle 补洞器。
- **Are We Really Making Much Progress?**（Ferrari Dacrema, Cremonesi, Jannach, 2019）指出许多新神经推荐方法在 Top-N 任务上未必稳定优于调好参数的简单近邻/图方法。对本项目的启发是：语义扩展必须与 category/popular/CF baseline 做 overlap、coverage 和 Recall@K 对比；不能因为“语义”概念更高级就默认晋升。

### 2.2 词项匹配、title/category 检索与漂移控制

- **Okapi BM25 / Probabilistic Relevance Framework** 的核心是词项稀有度、词频饱和和长度归一化。对 item title/category 召回而言，它支持“title/category 词项重叠是强 lexical baseline”的判断，但也提醒泛词、长字段和高频 token 会放大噪声。
- 本方法当前实现更接近 lexical overlap + category gate，而非 dense semantic retrieval。因此最佳实践应是：
  - 对 title token 做最小长度、停用词、泛词桶上限控制；
  - 对 category path 使用约束或强加权，不把弱类目当作唯一命中依据；
  - 记录 token bucket truncation、candidate_count 分布和 undercoverage reason；
  - 保持 source identity 独立于 canonical `semantic`。

### 2.3 embedding / graph / neural 方法的边界

- **Item2Vec: Neural Item Embedding for Collaborative Filtering**（Barkan, Koenigstein, 2016）说明 item 序列/共现可以学习 item embedding 并用于近邻候选生成。但本方法不训练 embedding，也不应把 title/category overlap 伪装成 item2vec/ANN 召回。
- **Graph Convolutional Neural Networks for Web-Scale Recommender Systems / PinSage**（Ying et al., 2018）说明大规模图推荐可结合图邻域和 item feature 做候选生成。本方法可借鉴“item feature 参与召回”的思想，但没有图卷积训练和 hard negative 机制，因此正式结论必须限定在 metadata overlap source。
- **Wide & Deep Learning for Recommender Systems**（Cheng et al., 2016）和 **Neural Collaborative Filtering**（He et al., 2017）更偏 ranking/learned matching；它们说明 metadata 与行为特征组合有价值，但不构成本方法直接晋升 READY 的证据。
- **Behavior Sequence Transformer for E-commerce Recommendation in Alibaba**（Chen et al., 2019）说明序列建模可提升电商推荐，但本方法只使用近期 seed item 做扩展，不建模复杂序列注意力。因此可报告 seed_window/recency 的工程取舍，但不能宣称 sequence model 能力。

## 3. 对本项目的适配判断

### 3.1 数据质量条件

`semantic_title_category_expansion` 最依赖：

1. train-only seed item 的 title/category metadata 覆盖；
2. title token 的清洗质量，尤其泛词过滤与 token bucket 上限；
3. category path 的稳定性，避免跨大类漂移；
4. eligible user 的 recent positive sequence 是否有可查 metadata；
5. semantic recall inputs / inverted index 是否由 recent-2y train-visible item universe 派生，并通过 no-holdout audit。

当前 recent-2y governance manifest 为 PASS，用户质量分布高度偏冷：cold_start 占 0.771641、fallback_only 占 0.127705、sequence_sufficient 占 0.093358、collaborative_rich 占 0.007283。因此 formal 设计应覆盖 collaborative/sequence/fallback 用户，但不能让无 seed 的 cold_start 用户拉低或污染正式候选生成口径。

### 3.2 构建方式建议

推荐保留当前 `title_category_scorer` 作为本轮正式构建模式：

- seed 来源：用户 recent train-only positive sequence，按 `seed_window` 取近期去重 seed；
- item 文本字段：`title_clean`、`main_category`、`categories_flat`；
- 候选生成：用 seed tokens 命中 inverted index 后，再按 title token overlap + category overlap 打分；
- 漂移控制：默认 `require_category_overlap=true`，弱类目只做 boost，不做唯一依据；
- 资源控制：限制 `per_token_item_limit` 和 `max_candidate_items`，在 manifest 中记录 truncation；
- 输出：必须生成七件套 `method_dataset_manifest.json`、`source_index_manifest.json`、`candidates.jsonl`、`coverage_audit.json`、`undercoverage_audit.json`、`resource_audit.json`、`no_holdout_audit.json`。

不建议本轮引入 dense embedding、LLM rewrite、query expansion 或 eval-label-driven token selection。这些会增加资源/泄漏/不可解释风险，且超出单方法 source artifact 重建范围。

## 4. smoke/formal 数据集设计

### 4.1 smoke

用途：只验证程序、schema、路径和 governance，不作为效果结论。

建议 contract：

- eligible manifest：`outputs/recall/pool500_method_sources_newdata/eligible_users_semantic_recent2y_smoke_v1/eligible_user_manifest.json`
- 用户规模：200；分层 quota 为 collaborative_rich 40、sequence_sufficient 100、fallback_only 50、cold_start 10；
- 方法参数：`seed_window=20`、`per_user=80`、`per_seed=40`、`per_token_item_limit=1000`、`max_candidate_items=30000`；
- 输出 manifest 明确：`promotion_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`。

### 4.2 formal

用途：作为 recent-2y train-only 口径下的正式 source artifact 与评估依据。

建议 contract：

- eligible manifest：`outputs/recall/pool500_method_sources_newdata/eligible_users_semantic_recent2y_formal_v1/eligible_user_manifest.json`
- 用户规模：50000；分层 quota 为 collaborative_rich 10000、sequence_sufficient 30000、fallback_only 10000；medium_behavior 仅 audit-only，cold_start 不进入 formal candidate generation；
- 方法参数：`seed_window=50`、`per_user=120`、`per_seed=60`、`per_token_item_limit=2000`、`max_candidate_items=200000`；
- 资源策略：该方法非训练型，优先本地受控运行；若 runtime/磁盘/内存异常，再迁移 server，回传 manifest、stats、candidates 和评估报告。

## 5. 评估建议

正式效果必须基于 formal，而不是 smoke。建议报告：

- source artifact 侧：target_user_count、candidate_row_count、user_coverage_count、candidate_count p50/p90/max、title_coverage、category_coverage、seed_item_metadata_coverage、undercovered reasons、runtime；
- evaluation-only 侧：Recall@20/50/100/500、HitRate@20/50/100/500、用户桶分层、与 category/semantic/popular/CF 的 overlap；
- route gate 侧：如果要建议主路并入，必须额外证明 source loader、candidate merge、route gate regression 通过，并给出边际贡献或 fallback 价值。

valid/test label 可以用于 evaluation-only 指标，但必须在报告中注明 `label_inputs_role=evaluation_only_not_candidate_generation_inputs`，并保留 no-holdout/no-oracle 审计证据。

## 6. 风险与门禁

| 风险 | 门禁 |
|---|---|
| 旧 full-data artifact 回流 | registry/source_config/METHOD 只能指向 recent-2y 当前产物；旧路径标为 archived/reference |
| title 泛词导致漂移 | 停用词、token bucket truncation、category overlap required、candidate_count 分布审计 |
| 类目过宽导致弱相关候选 | 报告 category consistency；弱类目仅 boost，不作为唯一 gate |
| seed metadata 缺失 | 报告 seed_item_metadata_coverage 与 undercoverage reasons |
| smoke 被误作正式效果 | smoke manifest/policy 写明 program/schema validation only 和 promotion_allowed=false |
| formal 产物不足以 READY | 保持 DEFERRED/TARGET_SLICE_DIAGNOSTIC，列 blocker，不强行并入主路 |
| eval label 泄漏 | 构建阶段 no_holdout_audit 必须 PASS；eval label 只在独立评估脚本读取 |

## 7. 可执行结论

本轮应把 `semantic_title_category_expansion` 完成为 recent-2y **诊断级正式 artifact**：允许生成可复核 source artifact 和 formal 评估报告，但默认仍保持 `DEFERRED` / `TARGET_SLICE_DIAGNOSTIC`，`candidate_generation_allowed=false`，不直接替换 ranking input，不自动进入 pool500 主路。是否晋升 READY 留给后续全局主路收口和 route gate。

## 8. 参考来源

- Amazon.com Recommendations: Item-to-Item Collaborative Filtering, Linden/Smith/York, 2003: https://www.cs.umd.edu/~samir/498/Amazon-Recommendations.pdf
- Okapi BM25 explanation, Stanford IR Book: https://nlp.stanford.edu/IR-book/html/htmledition/okapi-bm25-a-non-binary-model-1.html
- Item2Vec: Neural Item Embedding for Collaborative Filtering, Barkan/Koenigstein, 2016: https://arxiv.org/abs/1603.04259
- Wide & Deep Learning for Recommender Systems, Cheng et al., 2016: https://arxiv.org/abs/1606.07792
- Neural Collaborative Filtering, He et al., 2017: https://arxiv.org/abs/1708.05031
- Graph Convolutional Neural Networks for Web-Scale Recommender Systems / PinSage, Ying et al., 2018: https://arxiv.org/abs/1806.01973
- Behavior Sequence Transformer for E-commerce Recommendation in Alibaba, Chen et al., 2019: https://arxiv.org/abs/1905.06874
- Are We Really Making Much Progress? A Worrying Analysis of Recent Neural Recommendation Approaches, Ferrari Dacrema/Cremonesi/Jannach, 2019: https://arxiv.org/abs/1907.06902
