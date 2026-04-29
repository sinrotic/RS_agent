# Optimization Narrative：从可跑闭环到可诊断推荐系统

这个文档用于持续记录项目优化过程中的问题、判断、实验结果和面试叙事。它不是最终指标报告，而是解释“为什么这样做、遇到了什么、下一步为什么这么走”的过程文档。

---

## 当前主线

项目当前不是在做“纯 LLM 推荐”，而是在做一个以传统推荐 backbone 为底座、以 Agent 决策为上层的 hybrid recommendation demo。

当前阶段位置：

```text
Phase 1.5：推荐闭环 + ItemCF backbone + 诊断指标   已完成
Phase 1.6：semantic/text recall 增强                 已完成第一版
Phase 1.7：rerank / 排序曝光诊断                     已形成阶段性结论
Phase 1.8：item-level feature rerank                  已完成第一版
Phase 2：商品展示卡 contract + 训练前闭环              规划中
Phase 3：前端 + 多角色模拟客户沙盒 + 动画回放          规划中
```

当前核心判断：

> 系统已经从“候选池召回不到目标”推进到“部分目标已进入候选池，但排序没有推入 Top-K”。title/category-only semantic 是目前 valid/test 最好的对照；但 conservative config 和 semantic-only penalty 都没有提升 Top-K hit，说明 source-level 调参已经到边界。当前不应继续盲调召回参数，下一步应把 Agent feedback、rollout、商品展示卡 contract 和训练前闭环收紧；前端、多角色模拟客户和动画回放作为后期展示与仿真评估层。

---

## Phase 1.5：先搭小样本可诊断闭环

### 当时要解决的问题

一开始项目不能只证明“脚本能跑”，而是要形成一个可解释的推荐闭环：

1. 构建小样本 Amazon Electronics recall clean / recall views。
2. 合并 popular、ItemCF、category 召回源。
3. 用 deterministic baseline ranker 生成 Top-K。
4. 用 Agent policy stub 做最终推荐包装和解释。
5. 用指标判断问题发生在召回、排序还是最终曝光。

### 遇到的问题 1：不能只讲 LLM / Agent

如果项目叙事变成“LLM 直接推荐”，面试中会很容易被问：

- 召回在哪里？
- 排序在哪里？
- 为什么不是一个会说话的 chatbot？
- 工业推荐链路的边界在哪里？

因此项目主线调整为：

> Agent 不是替代推荐系统，而是编排推荐系统。底层仍然保留召回、排序、规则和评估模块。

### 遇到的问题 2：ItemCF 有候选，但 Top-K 几乎没有曝光

早期 valid/test 里 ItemCF source 在候选池中存在，但最终 Top-K 几乎被 popular / category 占据。

为了解决这个诊断盲区，增加了：

- `topk_source_coverage`
- `topk_source_minimums`

其中 `topk_source_minimums: {"itemcf": 1}` 用于保证 ItemCF 至少有机会进入最终推荐列表。

### 遇到的问题 3：Top-K 曝光提升了，但 hit-rate 没提升

ItemCF minimum 后，ItemCF 在 Top-K 中曝光明显增加，但 valid/test hit-rate 没有提高。

这说明问题不是简单的排序权重，而可能是 holdout 正样本根本没有进入候选池。

因此增加了候选池命中诊断：

- `candidate_hit_rate_at_pool`
- `candidate_hit_users`
- `candidate_hit_source_coverage`
- `ranked_hit_users`

### Phase 1.5 关键结果

valid/test：

```text
users_with_holdout = 30
candidate_hit_users = 2
candidate_hit_rate_at_pool = 0.066667
ranked_hit_users = 1
hit_rate_at_k = 0.033333
fallback_rate = 0.31
```

解释：

> valid/test 的主要瓶颈是 recall coverage，而不是简单 rank weight。

LOPO：

```text
lopo_input_users = 100
lopo_eligible_users = 49
candidate_hit_users = 43
candidate_hit_rate_at_pool = 0.877551
ranked_hit_users = 42
hit_rate_at_k = 0.857143
itemcf_only_hit_rate_at_k = 0.857143
```

解释：

> 在可控 leave-one-positive-out 场景下，ItemCF backbone 能有效找回用户近期正反馈中的 heldout item，说明 ItemCF 模块本身是有效的。

### Phase 1.5 的面试叙事

可以这样讲：

> 我没有直接堆复杂模型，而是先把推荐闭环拆成召回、排序、Agent 决策和评估四层。valid/test 低分不是失败，而是通过 candidate-hit diagnostics 定位到了真实切分下的召回覆盖问题；LOPO 高分则证明 ItemCF backbone 在可控场景下工作正常。

---

## Phase 1.6：semantic/text recall 增强

### 为什么进入 semantic recall

Phase 1.5 已经证明 valid/test 的主要问题是候选池覆盖不足。因此 Phase 1.6 没有先做复杂 LLM Agent 或 learning-to-rank，而是增加一个轻量、确定性的 semantic/text recall stub。

设计原则：

- 不引入 LLM 依赖。
- 不新增复杂训练流程。
- 使用已有 `semantic_recall_inputs.jsonl`。
- 只在 `semantic_enabled: true` 时启用，避免影响 Phase 1.5 baseline。

### 实现内容

新增 semantic recall source：

- 读取 item title、category、description、features、item_text。
- 提取简单 token set。
- 根据用户最近正反馈 item 的 token overlap 召回相似商品。
- source 名称为 `semantic`。

新增配置：

```text
configs/hybrid_demo_electronics_1000_semantic.yaml
configs/hybrid_demo_electronics_1000_lopo_semantic.yaml
```

### 遇到的问题 1：semantic 会挤占 ItemCF 候选池

刚接入 semantic 后，LOPO candidate hit 一度下降，原因是 semantic 候选进入 candidate pool 后挤掉了部分 ItemCF 候选。

修正：增加 candidate-pool 层面的 source minimum：

```json
"candidate_source_minimums": {
  "itemcf": 20,
  "semantic": 20
}
```

这保证 semantic 是增量召回源，而不是替换 ItemCF backbone。

### 遇到的问题 2：category-only overlap 噪声过宽

早期 semantic recall 允许 category overlap 单独触发召回，会把很多只是在大类上相同、文本并不相似的商品带进来。

修正：要求必须达到最小 token overlap，category 只作为加分项。

### 遇到的问题 3：seen item 过滤只在 merge 层发生

semantic recall 函数直接调用时可能返回 seed / seen item。虽然 merge 层会过滤，但这容易误用。

修正：把 seen-item filtering 前移到 semantic candidate generation 内部。

### Phase 1.6 关键结果

valid/test：

```text
Phase 1.5 candidate_hit_users = 2 / 30
Phase 1.6 candidate_hit_users = 6 / 30
Phase 1.6 candidate_hit_rate_at_pool = 0.2
candidate_hit_source_coverage.semantic = 5
ranked_hit_users = 1
```

LOPO：

```text
candidate_hit_users = 46 / 49
ranked_hit_users = 44 / 49
hit_rate_at_k = 0.897959
fallback_rate = 0.0
```

解释：

> semantic recall 确实提高了 valid/test 的候选池覆盖，而且没有破坏 ItemCF backbone 的 LOPO sanity check。

### Phase 1.6 的面试叙事

可以这样讲：

> 当诊断显示 valid/test 的瓶颈在召回覆盖时，我没有直接调排序权重，而是补了一个 deterministic semantic recall stub。它不依赖 LLM，只利用已有商品文本元数据。结果 candidate-hit 从 2/30 提升到 6/30，说明召回覆盖确实被改善；但 Top-K hit 没同步提升，进一步暴露出排序曝光问题。

---

## Phase 1.7：排序曝光诊断与 rerank 尝试

### 为什么进入排序诊断

Phase 1.6 后，目标商品已经更多地进入候选池，但最终 Top-K 没有明显变好。

因此增加 ranking exposure diagnostics：

- `candidate_hit_rank_min`
- `candidate_hit_rank_avg`
- `candidate_hit_rank_p50`
- `candidate_hit_missed_topk_users`

### 排名曝光诊断结果

semantic valid/test：

```text
candidate_hit_users = 6
ranked_hit_users = 1
candidate_hit_missed_topk_users = 5
candidate_hit_rank_min = 2
candidate_hit_rank_avg = 20.333333
candidate_hit_rank_p50 = 23.0
```

解释：

> 有 6 个用户的目标商品已经进入候选池，但只有 1 个进了 Top-5；剩下 5 个通常排在 20 名左右。

这说明问题已经从“召回不到”变成：

> 召回到了，但排序没有推上去。

### rerank policy 第一版

新增默认关闭的 deterministic rerank policy：

```json
"rerank_policy": {
  "enabled": true,
  "semantic_boost": 2.0,
  "multi_source_boost": 1.0,
  "popular_only_penalty": 0.5
}
```

支持：

- semantic source boost
- multi-source boost
- popular-only penalty

新增配置：

```text
configs/hybrid_demo_electronics_1000_semantic_rerank.yaml
configs/hybrid_demo_electronics_1000_lopo_semantic_rerank.yaml
```

### rerank 尝试结果

温和 rerank 后 valid/test：

```text
candidate_hit_users = 6
ranked_hit_users = 1
candidate_hit_missed_topk_users = 5
candidate_hit_rank_avg = 20.5
candidate_hit_rank_p50 = 23.5
```

LOPO：

```text
ranked_hit_users = 44
hit_rate_at_k = 0.897959
```

### 参数搜索结果

进一步尝试：

```text
semantic_boost = 4 / 6 / 8 / 10
multi_source_boost = 1 / 2 / 3
popular_only_penalty = 1 / 1.5 / 2
```

valid/test 仍然没有改善：

```text
ranked_hit_users = 1
candidate_hit_missed_topk_users = 5
```

### hit-level ranking case export

为了继续定位“召回到了但没有进 Top-K”的原因，新增了标准诊断产物：

```text
outputs/.../ranking_hit_cases.jsonl
```

每条 case 记录一个进入候选池的 holdout target：

```json
{
  "user_id": "...",
  "target_item": "...",
  "target_rank": 23,
  "target_score": 4.2,
  "target_sources": ["semantic"],
  "target_source_scores": {"semantic": 3.5},
  "is_topk_hit": false,
  "items_above_target": [...],
  "top_items": [...]
}
```

这一步的作用是把 aggregate metrics 继续拆到 case 层，直接观察 target 上方到底是什么候选。

### case export 的初步观察

在 semantic valid/test 的 `ranking_hit_cases.jsonl` 中，多个 missed target 被大量高分 `semantic` 或 `semantic + popular` 候选压住。例如：

- `B0B2JJV92T` 排在 rank 29，target source 是 `semantic`，上方大多也是高分 semantic 商品。
- `B0C72D4J46` 排在 rank 13，target source 是 `semantic`，上方仍主要是 semantic-only 商品。
- 部分 target 不是 semantic 命中，而是 `category + popular`，但被高分 semantic 候选整体压到很后面。

这个现象解释了为什么统一 `semantic_boost` 没有效果：

> 如果 target 和压住它的候选同属于 semantic source，那么给 semantic 整体加分不会改变它们之间的相对顺序。

### 当前关键结论

统一提升 semantic 分数没有用，因为：

> 目标商品和其他 semantic 候选一起上移，它们之间的相对顺序没有改变。

现在更具体地说，问题是：

> semantic recall 的 token-overlap 分数区分度不足，高分 semantic-only 候选会压住真实 holdout target；下一步应该改 semantic similarity / normalization，而不是继续调全局 rerank boost。

### normalized semantic scoring 对照

根据 case export 的观察，增加了 `semantic_score_mode: normalized`，将 raw token overlap 改为近似 Jaccard-style normalization：

```text
score = overlap / union_size * 100 + category_bonus
```

这样做的目的不是直接追指标，而是验证 raw token overlap 是否偏向长文本和通用词命中的候选。

normalized valid/test 结果：

```text
candidate_hit_users = 6
ranked_hit_users = 0
candidate_hit_missed_topk_users = 6
candidate_hit_rank_min = 7
candidate_hit_rank_avg = 14.0
candidate_hit_rank_p50 = 10.0
```

对比 raw semantic：

```text
candidate_hit_users = 6
ranked_hit_users = 1
candidate_hit_missed_topk_users = 5
candidate_hit_rank_min = 2
candidate_hit_rank_avg = 20.333333
candidate_hit_rank_p50 = 23.0
```

观察：

- normalized scoring 明显把多个 missed target 从 20–30 名附近推近到 7–18 名。
- 但它也把原本唯一的 Top-K hit 挤出了 Top-5，导致 valid/test `ranked_hit_users` 从 1 降到 0。
- LOPO hit-rate 从 0.897959 降到 0.877551，说明 normalized scoring 对 ItemCF sanity check 有轻微负面影响。

当前判断：

> normalized semantic scoring 方向有价值，因为它改善了 target 的候选池内排名分布；但直接替换 raw score 会损失已有 Top-K 命中，需要更保守地融合 normalized semantic，而不是完全替换。

进一步做了 normalized score + lower semantic rank weight 的小范围搜索：

```text
semantic rank weight = 0.4 / 0.6 / 0.8 / 1.0
```

结果 valid/test 仍然是：

```text
ranked_hit_users = 0
candidate_hit_missed_topk_users = 6
```

说明问题不只是 semantic rank weight 过高或过低，而是 full-text token set 本身仍然存在噪声。normalized 能把 target 推近，但不能稳定推入 Top-K，而且会损失原本的 Top-K 命中。

### title/category-only semantic scoring 对照

根据 normalized scoring 的结果，继续做了 title/category-only semantic token 对照：

```yaml
semantic_text_fields:
  - title_clean
  - main_category
  - categories_flat
```

这个实验要验证的问题是：full-text semantic 是否被 description、features、item_text 这类长文本字段放大了噪声。

valid/test 结果：

```text
candidate_hit_users = 6
ranked_hit_users = 2
hit_rate_at_k = 0.066667
candidate_hit_rank_min = 1
candidate_hit_rank_avg = 13.166667
candidate_hit_rank_p50 = 13.0
candidate_hit_missed_topk_users = 4
```

对比 raw full-text semantic：

```text
ranked_hit_users: 1 -> 2
hit_rate_at_k: 0.033333 -> 0.066667
candidate_hit_rank_avg: 20.333333 -> 13.166667
candidate_hit_rank_p50: 23.0 -> 13.0
candidate_hit_missed_topk_users: 5 -> 4
```

LOPO 对照：

```text
raw full-text semantic hit_rate_at_k = 0.897959, ranked_hit_users = 44
title/category-only semantic hit_rate_at_k = 0.877551, ranked_hit_users = 43
```

case-level 观察：

- `B0B2JJV92T` 从 raw full-text semantic 的 rank 29、normalized full-text 的 rank 7，提升到 title/category-only 的 rank 3，并成为 Top-K hit。
- 仍有多个 target 停留在 Top-K 外，例如 rank 12、17、18、32、37，说明 title/category-only 只是减少噪声，不是完全解决 semantic 内部排序。

阶段性判断：

> title/category-only semantic 是目前 valid/test 表现最好的 semantic variant。它证明 full-text 字段确实引入了排序噪声；但它轻微牺牲 LOPO 稳定性，因此暂时应作为 Phase 1.7 的推荐对照配置，而不是直接替代所有 semantic scoring。

### title-focused ranking case 聚合分析

为了避免只看个别 case，又新增了 `ranking_case_summary.json`，把 `ranking_hit_cases.jsonl` 里的 missed target 聚合成 source-composition 和 score-gap 统计。

valid/test title-focused 结果：

```text
total_hit_cases = 10
topk_hit_cases = 2
missed_topk_cases = 8
items_above_total = 171
semantic_only_items_above_share = 0.707602
top1_score_gap_avg = 12.925335
items_above_source_combinations.semantic = 121
items_above_source_combinations.category+semantic = 43
top_item_source_combinations.semantic = 22
top_item_source_combinations.category+semantic = 18
```

LOPO title-focused 结果：

```text
total_hit_cases = 46
topk_hit_cases = 15
missed_topk_cases = 31
semantic_only_items_above_share = 0.675778
top1_score_gap_avg = 23.145374
```

诊断结论：

> title/category-only 已经减少了一部分 full-text 噪声，但剩余 missed target 上方仍然主要是 semantic-only 或 category+semantic 候选。valid/test 中 missed target 的上方候选 70.8% 是 semantic-only，Top-5 source 也几乎都带 semantic。这说明下一步最有价值的不是继续提高 semantic 权重，而是限制 semantic-only 曝光、提高 semantic 准入门槛，或加入 semantic 与其他 source 的交互特征。

下一步应该尝试：

- 在 title/category-only 基础上做 conservative variant，例如 `semantic_min_overlap = 2` 或降低 `candidate_source_minimums.semantic`；
- 尝试限制 semantic-only 在 Top-K 的曝光，把 Top-K 留给 multi-source 或 ItemCF/category 支持的候选；
- 不再做大范围 boost 搜索，因为已有证据表明统一 boost 不改变 semantic 内部相对顺序。

### Phase 1.7 的面试叙事

可以这样讲：

> 在 semantic recall 提升候选覆盖后，我没有直接声称系统效果变好了，而是增加了 ranking exposure diagnostics。诊断显示新增命中大多排在 20 名左右。随后我尝试 deterministic rerank，但统一 semantic boost 无效，这说明问题不是全局权重，而是 semantic 候选内部的区分度不足。normalized scoring 证明长文本归一化能把 target 推近但会损失 Top-K hit；title/category-only semantic 则把 valid/test Top-K hit 从 1/30 提升到 2/30，说明长文本字段确实有噪声。下一步应该做 conservative title-focused 对照，而不是继续盲目调参。

---

## 当前问题列表

### 已定位

1. valid/test 原始 hit-rate 低，主要来自候选覆盖不足。
2. ItemCF backbone 在 LOPO 可控场景下有效。
3. semantic recall 能提高 valid/test candidate coverage。
4. semantic recall 需要 candidate-source minimum，否则会挤占 ItemCF。
5. category-only semantic overlap 噪声太宽，需要 token overlap 约束。
6. 目标商品召回后多数排在 Top-K 外。
7. 统一 semantic boost 不能改善目标商品在 semantic 内部的相对排名。
8. hit-level case export 显示 missed target 上方大量是高分 semantic-only 候选，说明 token-overlap semantic score 区分度不足。
9. full-text semantic 会受到 description / features / item_text 长文本噪声影响；title/category-only semantic 在 valid/test 上把 Top-K hit 从 1/30 提升到 2/30。
10. title-focused 聚合分析显示，valid/test missed target 上方 70.8% 的候选是 semantic-only，Top-5 source 几乎都带 semantic。

### 尚未解决

1. title/category-only 后仍有 4 个 candidate-hit target 停留在 Top-K 外。
2. title/category-only 轻微降低 LOPO hit-rate，说明它改善真实切分排序时也牺牲了一点 ItemCF sanity check 稳定性。
3. semantic-only 候选是否应该被限制 Top-K 曝光，还是只降低 candidate minimum？
4. 是否需要 source interaction feature，例如 semantic + category、semantic + recent positive overlap？
5. 是否需要在 title/category-only 基础上增加 stopword/domain-word filtering 或 conservative candidate minimum？

---

## 下一步建议

下一步不应该继续堆召回，也不应该继续盲目调 rerank 参数。

建议进入：

```text
Phase 1.7d：conservative title-focused semantic 对照
```

当前已经有聚合诊断产物：

```text
outputs/hybrid_demo_small_electronics_1000_semantic_title/ranking_case_summary.json
outputs/hybrid_demo_small_electronics_1000_lopo_semantic_title/ranking_case_summary.json
```

聚合结果回答了上一轮问题：

- Top-K 外 target 上方主要是 semantic-only，其次是 category+semantic。
- valid/test missed target 的上方候选 70.8% 是 semantic-only。
- Top-5 source 也几乎都带 semantic，说明不是 popular prior 过强，而是 semantic exposure 过强。
- title/category-only 修复了部分 case，但没有完全解决 semantic-only 候选压制 target 的问题。

### Phase 1.7d：conservative title-focused 对照

先做了 3 个 config-only conservative 变体：

```text
1. semantic_min_overlap = 2
2. candidate_source_minimums.semantic = 10
3. semantic_min_overlap = 2 + candidate_source_minimums.semantic = 10
```

结果三组 valid/test 和 LOPO 指标与 title-focused baseline 完全一致：

```text
valid ranked_hit_users = 2
valid hit_rate_at_k = 0.066667
valid semantic_only_items_above_share = 0.707602
LOPO ranked_hit_users = 43
LOPO hit_rate_at_k = 0.877551
```

诊断结论：

> 这些 config-only conservative 变体没有改变候选池或排序结果，说明当前命中的 semantic 候选本身已经满足 overlap=2，且 semantic minimum=10 仍足以保留同一批高分 semantic 候选。瓶颈不是“semantic 候选保底太多”，而是 Top-K 排序里 semantic-only 候选仍然得分过高。

随后增加了默认关闭的 `rerank_policy.semantic_only_penalty`，只惩罚纯 semantic 候选：

```json
"rerank_policy": {
  "enabled": true,
  "semantic_only_penalty": 5.0
}
```

小范围结果：

```text
penalty=2:  valid semantic_only_items_above_share 0.707602 -> 0.672840, hit_rate_at_k 0.066667
penalty=5:  valid semantic_only_items_above_share 0.707602 -> 0.639241, hit_rate_at_k 0.066667
penalty=10: valid semantic_only_items_above_share 0.707602 -> 0.636943, hit_rate_at_k 0.066667

penalty=10: LOPO semantic_only_items_above_share 0.675778 -> 0.591449, hit_rate_at_k 0.877551
```

诊断结论：

> semantic-only penalty 确实减少了排在 target 上方的 semantic-only 候选占比，但 Top-K hit 没有变化。这说明很多 target 本身也是 semantic-only；同源惩罚会把 target 和压住它的 semantic-only 候选一起下移，仍然不能解决 semantic 内部相对排序问题。

当前推荐：

1. 不把 `semantic_only_penalty` 作为推荐配置，因为它降低了 semantic-only exposure，但没有提升 hit-rate。
2. 保留这个机制作为诊断工具，证明“限制 semantic-only 曝光”单独不够。
3. 下一步不再继续调 semantic exposure，而应进入 Agent 层 demo 或补更真实的排序特征；如果仍留在排序层，则需要新的 item-level feature，而不是 source-level penalty。
4. Agent 层 demo 已经出现 CLI smoke 级反馈闭环修复结果，后续更适合补成稳定案例展示、反馈响应指标和可复现实验入口，而不是继续把叙事压在 source-level 调参上。

---

## Phase 1.8：item-level feature rerank 第一版

### 为什么做 item-level feature rerank

Phase 1.7 已经证明，统一提升或惩罚某个 source 不能稳定改变同源候选内部的相对顺序。因此 Phase 1.8 不再继续调 semantic exposure，而是把排序策略下沉到 item-level 特征：候选是否多源支持、是否只有 popular / semantic、是否命中用户反馈里的 category/source/keyword。

### 实现内容

新增默认关闭的 `item_feature_rerank`：

```json
"item_feature_rerank": {
  "enabled": true,
  "weights": {
    "multi_source": 1.0,
    "feedback_category_match": 1.0,
    "feedback_source_match": 1.0,
    "feedback_keyword_match_count": 1.0,
    "feedback_disliked_keyword_match_count": -2.0,
    "popular_only": -0.5,
    "semantic_only": -0.5
  }
}
```

排序输出增加：

- `feature_score`
- `item_features`
- `rerank_events` 中的 `item_feature` 事件

新增对照配置：

```text
configs/hybrid_demo_electronics_1000_semantic_title_item_feature.yaml
configs/hybrid_demo_electronics_1000_lopo_semantic_title_item_feature.yaml
```

### 实验结果

valid/test 对照：

```text
Phase 1.7 title baseline hit_rate_at_k = 0.043478
Phase 1.8 item-feature hit_rate_at_k = 0.043478
candidate_hit_rank_avg: 12.285714 -> 12.571429
semantic_only_items_above_share: 0.711864 -> 0.674556
top1_score_gap_avg: 12.144742 -> 12.089187
```

LOPO 对照：

```text
Phase 1.7 title baseline hit_rate_at_k = 0.888889
Phase 1.8 item-feature hit_rate_at_k = 0.888889
candidate_hit_rank_avg: 25.128205 -> 23.461538
candidate_hit_rank_p50: 34.0 -> 32.0
top1_score_gap_avg: 24.742213 -> 24.047873
```

### 阶段性判断

> item-level feature rerank 没有带来新的 Top-K hit，但改善了 LOPO 目标商品的候选池内排名分布，并让排序变化可以通过 `item_features` 和 `rerank_events` 解释。它更适合作为后续 Agent 反馈和学习排序的特征接口，而不是单独的 hit-rate 提升方案。

---

## 总体面试叙事

这条主线可以总结成：

> 我先搭了一个传统推荐 backbone + Agent 决策层的最小闭环。然后没有直接追求复杂模型，而是通过 source coverage、candidate hit、Top-K exposure、LOPO sanity check 等诊断指标逐层定位问题。Phase 1.5 发现 valid/test 的主要瓶颈是召回覆盖；Phase 1.6 用 deterministic semantic recall 提升了候选池命中；Phase 1.7 又发现 Top-K 未提升的原因是目标商品虽然进入候选池，但排序位置仍然靠后。简单统一 boost semantic 无效，normalized scoring 改善排名分布但损失 Top-K hit，title/category-only semantic 则把 valid/test Top-K hit 从 1/30 提升到 2/30。后续 conservative config 和 semantic-only penalty 都没有继续提升 hit-rate，说明 source-level 调参已经到边界，下一步应进入 Agent 层 demo 或补 item-level 排序特征。

这个叙事的价值在于：

- 不是堆模块，而是每一步都有诊断依据。
- 能讲清召回、排序、Agent 的边界。
- 能说明为什么暂时不做复杂 LLM Agent 或双塔。
- 能展示工业推荐系统里“定位瓶颈再优化”的思路。
