# two_tower recent-2y 效果不佳诊断调研

日期：2026-06-03
状态：diagnosis complete / implementation pending

## 1. 结论摘要

`two_tower` formal preflight 的低效果不是单一 bug，而是多因素叠加：

1. **训练规模与 item universe 不匹配**：preflight 只训练 20000 个 eligible users，但 source index 覆盖 499566 个 item；实际被训练正样本触达的 distinct item 约 61728，只占 index item 的 12.36%。大量 item 只有文本 hash 初始化，缺少行为监督更新。
2. **用户 query 构造过弱**：direct eval 用最近 positive seed 做平均向量；500 个 eval users 中 95 个没有可用 seed 向量，`queryless_user_rate=0.19`。可查询用户平均 seed-in-index 也只有 1.542，难以表达多兴趣和短期意图。
3. **模型结构过浅**：当前 YouTubeDNN 实现本质是 32 维 item embedding + 单层 user tower，对历史 item 做平均/加权平均后投影；没有 session order、attention、多兴趣、hard negative 或 sampled-softmax correction。
4. **负采样和训练目标偏弱**：训练使用 popularity-power negatives，但没有 logQ / sampling-bias correction、in-batch negative 或 hard negative 机制。论文显示大规模 item recommendation 中采样偏差会显著影响召回质量。
5. **评估目标与训练输入错位**：eval label 中约 83.96% 在 index universe 内，但只有约 45.66% 的 label events 出现在 20k preflight 训练用户正样本触达 item 中。模型对大量 eval target 只靠初始化文本向量，行为信号不足。
6. **two-tower 本身适合作为 candidate generation，不应替代 ranking 或多路召回**：YouTubeDNN 论文强调候选生成后仍需独立 ranking；本项目 preflight 指标不足，不能单独进入主路。

因此当前 `DIAGNOSTIC_ONLY` 判断是合理的。下一步优先不是盲目调参，而是先补全训练规模、query 覆盖、负采样校正和序列/多兴趣表达。

## 2. 本项目证据

### 2.1 formal preflight 指标

证据文件：

- `outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_preflight_20k_training_run/artifact_manifest.json`
- `outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_preflight_20k_eval/raw_two_tower_direct_eval_manifest.json`
- `outputs/recall/pool500_method_sources/recent_2y/two_tower/formal_preflight_20k_evaluation_report.json`

关键字段：

- `training_input_users=20000`
- `users_with_training_rows=19429`
- `training_examples=60219`
- `item_count=499566`
- `user_embedding_count=20000`
- `loss_history=[1.770341]`
- `recall_at_20=0.00289`
- `recall_at_50=0.00578`
- `recall_at_100=0.008671`
- `recall_at_500=0.021676`
- `hit_rate_at_500=0.028`
- `query_user_count=405`
- `queryless_user_count=95`
- `underfilled_user_rate=0.19`

### 2.2 seed/query 覆盖诊断

本地诊断脚本统计了 500 eval users 的 train sequence seed 覆盖：

```json
{
  "eval_users": 500,
  "seq_found": 500,
  "queryless_by_seed_index_coverage": 95,
  "seed_count_min": 0,
  "seed_count_avg": 1.592,
  "seed_in_index_avg": 1.542,
  "users_with_zero_seeds": 85,
  "users_with_zero_seed_in_index": 95,
  "label_total": 692,
  "label_in_index": 581,
  "label_in_index_ratio": 0.839595
}
```

解释：

- eval user 都能找到 train sequence，但很多用户没有可用于 two_tower query 的 recent positive seed。
- 即使能 query，平均只有约 1.5 个 seed item 在 index 中，近似退化为“单 seed item embedding 相似检索”。
- 这与 SASRec/GRU4Rec/MIND 等论文强调的序列、多兴趣建模方向相反。

### 2.3 preflight 训练触达 item 太少

本地诊断统计：

```json
{
  "selected_preflight_users": 20000,
  "distinct_train_positive_items_in_20k_subset": 61728,
  "index_item_count": 499566,
  "train_positive_item_ratio_vs_index": 0.123563,
  "eval_distinct_label_items": 684,
  "eval_distinct_label_items_in_index": 576,
  "eval_distinct_label_items_seen_as_train_positive_in_20k": 311,
  "eval_label_events_seen_as_train_positive_in_20k": 316,
  "eval_label_events_total": 692,
  "eval_label_events_seen_as_train_positive_ratio": 0.456647
}
```

解释：

- source index 很大，但 preflight 监督信号只覆盖少数 item。
- 499566 个 index item 中，约 87.64% 没有在 20k preflight 正样本中被行为监督直接更新。
- eval labels 虽然大多在 index universe 内，但只有约 45.66% 的 label events 属于 preflight 正样本触达 item。
- 这会导致检索排序主要受初始化文本 hash 与少量训练更新影响，而不是充分的用户-物品协同行为信号。

## 3. 代码机制诊断

相关代码：

- `rs_core/offline/training/two_tower.py`
- `rs_core/workflow/two_tower_training.py`
- `rs_lab/experiments/recall/run_pool500_two_tower_direct_eval.py`

### 3.1 item 表示初始化过强，训练更新不足

当前 item 初始向量来自文本字段 token hash + IDF：

- `title_clean`
- `main_category`
- `category`
- `description_text`
- `features_text`
- `item_text`
- `categories_flat`

YouTubeDNN 路线使用 `Embedding.from_pretrained(item_features, freeze=False)`，但 preflight 训练样本只有 `60219`，相对于 `499566` item 过少。

结果：很多 item embedding 主要停留在文本 hash 初始化状态，行为学习不足。

### 3.2 用户向量是历史 item 平均，缺少序列意图

训练与 eval 都倾向于把历史 item embedding 聚合成单个 user vector：

- training：`encode_user(history_indices, history_mask)` 对历史 embedding 做 masked mean，再过 user tower。
- eval：`average_vectors(seed item vectors, recency_decay)` 后再 `_apply_user_tower_projection`。

问题：

- 不建模 item 顺序；
- 不区分多个兴趣簇；
- 对短历史/稀疏 seed 用户非常脆弱；
- 对多兴趣用户容易把向量平均到“中间区域”，召回不准。

### 3.3 训练目标没有采样偏差修正

当前 negative sampling 主要是 popularity-power：

- `negative_sampling.strategy=popularity_power`
- `power=0.75`

但没有：

- logQ correction；
- sampled softmax correction；
- in-batch negatives；
- hard negatives；
- sampled negative audit by bucket / category / popularity。

这与 YouTube / large-corpus neural retrieval 论文中强调的采样校正不一致。

## 4. 论文与工业实践映射

### 4.1 YouTubeDNN：候选生成不是完整推荐

来源：Deep Neural Networks for YouTube Recommendations, Covington et al.

要点：

- YouTube 使用两阶段结构：candidate generation + ranking。
- candidate generation 目标是从大规模 corpus 中筛出候选，不负责最终排序。
- 工业系统中有大量训练样本、example age、特征、softmax/sampling 设计和 serving 优化。

映射到本项目：

- 当前 preflight 训练规模远小于 full formal；
- 没有完整的工业级特征、年龄特征和 sampling correction；
- 因此不能期待单个 20k preflight two_tower 达到主路召回效果。

### 4.2 Sampling-Bias-Corrected Neural Modeling：负采样偏差会拖垮大库召回

来源：Sampling-Bias-Corrected Neural Modeling for Large Corpus Item Recommendations, Google / YouTube NDR.

要点：

- in-batch / sampled negatives 会受 power-law item distribution 影响。
- 需要估计 item frequency 并修正 sampled loss。
- sampling bias correction 在 offline 和 A/B 中都能提升 large-corpus retrieval。

映射到本项目：

- 当前只用了 popularity-power negatives，没有 logQ / bias correction。
- 训练目标可能偏向头部或采样分布，不能很好学习真实 ranking objective。

### 4.3 DSSM：双塔依赖高质量点击/交互数据和共享空间

来源：Learning Deep Structured Semantic Models for Web Search using Clickthrough Data.

要点：

- DSSM 把 query/document 映射到共享低维空间。
- 质量依赖点击数据、表示学习和大规模训练。

映射到本项目：

- 当前共享空间是 32 维，训练更新稀疏；
- query 侧只有少量 seed item 平均，无法稳定表达用户意图。

### 4.4 BPR / NCF：点积召回表达力有限，pairwise/interaction modeling 很重要

来源：

- Bayesian Personalized Ranking from Implicit Feedback, Rendle et al.
- Neural Collaborative Filtering, He et al.

要点：

- BPR 强调隐式反馈推荐应直接优化 pairwise ranking。
- NCF 指出简单 inner product 表达力有限，MLP interaction function 更强。

映射到本项目：

- 当前训练是 sampled cross-entropy 风格，召回检索是 dot product。
- 没有 pairwise hard-negative ranking，也没有更强 user-item interaction model。
- dot product two-tower 可用于粗召回，但弱于后续 ranker 或 interaction-heavy 模型。

### 4.5 GRU4Rec / SASRec：序列顺序和短期意图不能被简单平均替代

来源：

- Session-based Recommendations with Recurrent Neural Networks / GRU4Rec.
- Self-Attentive Sequential Recommendation / SASRec.

要点：

- GRU4Rec 建模 session sequence。
- SASRec 用 self-attention 捕捉长短期依赖和关键历史 item。
- 两者都避免把历史简单平均成一个向量。

映射到本项目：

- eval 平均 seed 数只有 1.542，且没有 sequence order。
- 对最近意图、短 session、兴趣切换用户不敏感。
- 这解释了 hit-rate 偏低和 queryless/underfilled 问题。

### 4.6 MIND：单 user vector 压缩多兴趣会损失召回

来源：Multi-Interest Network with Dynamic Routing for Recommendation at Tmall.

要点：

- MIND 用多个 interest capsules 表达用户多兴趣。
- 单向量会把多个兴趣压缩到一个中心，降低候选匹配质量。

映射到本项目：

- 当前 one-user-vector two_tower 对 Amazon 多品类行为不友好。
- category overlap 与 user-level overlap 证据不足，也提示单向量可能没有捕捉多兴趣。

### 4.7 Faiss / ANN：向量召回要同时评估质量、速度和 exact/ANN tradeoff

来源：Billion-scale similarity search with GPUs / Faiss.

要点：

- 大规模向量检索要同时看 kNN 质量、速度、内存和近似误差。
- 不应只看 index row count。

映射到本项目：

- 当前已记录 source row count、search timing，但还未做 exact-vs-ANN、latency/QPS、artifact size 与召回质量联合 gate。
- 这也是不能 READY 的原因之一。

### 4.8 Recommender reproducibility / evaluation bias：不能只凭弱对照或单次 preflight 下结论

来源：Are We Really Making Much Progress? A Worrying Analysis of Recent Neural Recommendation Approaches, Dacrema et al.

要点：

- 许多 neural recommender 结果难复现，且常被简单强 baseline 打败。
- offline evaluation 如果 baseline 或 protocol 不公平，容易夸大模型收益。

映射到本项目：

- 当前 two_tower preflight 低于 popular fallback 的 Recall@500；
- 必须与 popular/category/ItemCF/Swing 做公平 source overlap 和 marginal lift，而不是单独看神经模型是否“高级”。

## 5. 主要原因优先级

### P0：训练规模不够，导致大 index 中多数 item 未被行为监督充分更新

证据：

- `training_input_users=20000`
- `training_examples=60219`
- `item_count=499566`
- 20k preflight distinct train positive item 约 61728，仅占 index item 12.36%。

影响：

- 行为信号稀薄；
- 大量 item 向量接近文本初始化；
- dot-product 检索无法稳定命中 eval target。

### P0：queryless / seed coverage 问题

证据：

- `queryless_user_count=95/500`
- `users_with_zero_seeds=85`
- `seed_in_index_avg=1.542`

影响：

- 19% eval users 直接无法检索；
- 可检索用户也经常只有 1 个 seed，召回退化为 item-to-item 相似。

### P1：单向量平均历史无法表达多兴趣/序列意图

证据：

- 当前 eval query 是 seed vectors average + user_tower projection。
- MIND/SASRec/GRU4Rec 均说明多兴趣和序列顺序对 next-item 推荐重要。

影响：

- 类目跨度大的 Amazon 用户会被平均向量稀释；
- 对最近意图不敏感。

### P1：负采样目标与真实大库召回目标错配

证据：

- `negative_sampling.strategy=popularity_power`
- 没有 logQ / sampling-bias correction / hard negatives。

影响：

- 模型可能学到采样分布而非真实候选 ranking；
- 头部 item 与长尾 item 训练不均衡。

### P2：评估样本与训练子集错位

证据：

- eval label item in index ratio = 0.839595。
- eval label events seen as 20k preflight train positive ratio = 0.456647。

影响：

- 很多 eval target 对模型来说不是行为监督充分学习过的 item；
- bounded preflight 指标偏低不完全代表 full formal 上限，但足以说明不能 READY。

## 6. 后续优化建议

### 6.1 先做 full remote formal training，而不是本地继续小修

目标：

- 使用完整 `eligible_user_count=687147`。
- 保留 `item_count=499566` training item universe。
- 记录训练资源、loss、user/item coverage。

建议配置：

- `epochs=1-3` 分段跑，保留 checkpoint。
- batch size 8192/16384 + gradient accumulation。
- mixed precision。
- 每 10k/50k users 记录 progress log。
- 输出 full artifact + direct eval + overlap + route gate。

验收：

- queryless rate 是否下降；
- `Recall@500` 是否显著超过 preflight；
- 是否有相对 popular/category/ItemCF/Swing 的独有命中。

### 6.2 修 query 构造：降低 queryless 和单 seed 退化

可选方案：

1. eval/build query 同时读取：
   - `recent_positive_item_sequence`
   - `recent_strong_positive_item_sequence`
   - `recent_item_sequence`
2. 对无 positive seed 用户启用 train-only fallback：
   - category profile seed；
   - popular-in-category seed；
   - usercf/itemcf seed。
3. 记录每个用户 seed count、seed-in-index count、query source。

注意：fallback 只能来自 train-only，不得读 label。

### 6.3 从平均历史升级到序列/多兴趣用户表示

短期：

- recency-weighted pooling 加强；
- top recent N + category-diverse pooling；
- 多 query vector：按 category/时间窗口拆兴趣。

中期：

- SASRec-style self-attention user tower；
- MIND-style multi-interest capsules；
- session-aware query tower。

### 6.4 改负采样与训练目标

建议实验：

- sampled softmax + logQ correction；
- in-batch negatives；
- hard negatives：同类目高频未交互 item、ItemCF 近邻但未点击 item；
- popularity bucket balanced negatives；
- BPR / pairwise ranking auxiliary loss。

评估时分桶看：

- head / torso / tail item recall；
- user behavior bucket；
- in-universe recall；
- category consistency；
- unique hit contribution。

### 6.5 增强 item 特征，但不要只靠文本 hash

当前文本 hash 初始化可以提供冷启动相似性，但不足以替代行为训练。

建议：

- 使用更稳定的 item text embedding 初始化，例如已有 RAG/semantic embedding；
- 增加 category/brand/price bucket 等 structured feature；
- 对 item tower 做 feature ablation，比较 text-only / behavior-only / hybrid。

### 6.6 与多路召回做 marginal lift，而不是单独追求 raw Recall

READY 前必须回答：

- two_tower 命中的 positive 是否是 popular/category/ItemCF/Swing 没命中的？
- 是否改善某些 user bucket，如 sequence_sufficient / medium_behavior？
- 引入 two_tower 后是否增加重复、降低候选多样性或挤占强 source budget？

如果没有独有命中或 fallback 价值，即使 raw Recall 提升也不应进入主路。

## 7. 建议的下一轮实验顺序

1. **query coverage 修复 smoke**：先让 500 eval users 的 queryless rate 从 0.19 降到接近 0，验证不读 label。
2. **20k preflight v2**：加入多 seed source、strong+positive+recent_item fallback，复测 Recall@K。
3. **negative sampling v2**：加入 popularity bucket / hard negative / in-batch negative，对比 loss 与 Recall@K。
4. **full remote formal v1**：687147 eligible users 全量训练，1 epoch 起步。
5. **multi-interest / sequence tower v0**：如果 full formal 仍不达标，再引入 SASRec/MIND 方向，而不是过早复杂化。
6. **route-level marginal lift**：与 READY sources 做 overlap、unique hit 和 source budget gate。

## 8. 当前最终判断

`two_tower` 效果不佳的主要矛盾是：**用小规模 preflight 的浅层单向量 two-tower，去检索接近 50 万 item 的大库，并且 eval query 本身有 19% 缺失、可用 seed 很少。**

这不是简单增加 epoch 就一定能解决；更核心的是：

- full formal 训练规模；
- query coverage；
- 序列/多兴趣建模；
- sampling bias correction；
- 与多路召回的 marginal lift 评估。

因此当前应保持 `DIAGNOSTIC_ONLY`，下一步按“query 修复 → preflight v2 → full remote formal → sequence/multi-interest”的顺序推进。
