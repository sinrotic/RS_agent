# Optimization Narrative：从可跑闭环到可诊断推荐系统

这个文档用于持续记录项目优化过程中的问题、判断、实验结果和面试叙事。它不是最终指标报告，而是解释“为什么这样做、遇到了什么、下一步为什么这么走”的过程文档。

---

## 当前主线

项目当前不是在做“纯 LLM 推荐”，而是在做一个以传统推荐 backbone 为底座、以 Agent 决策为上层的 hybrid recommendation demo。

当前阶段位置：

```text
Phase 1.5：推荐闭环 + ItemCF backbone + 诊断指标       已完成
Phase 1.6：semantic/text recall 增强                   已完成第一版
Phase 1.7：rerank / 排序曝光诊断                       已形成阶段性结论
Phase 1.8：item-level feature rerank                    已完成第一版
Phase 1.9：source-aware fusion + 轻量 LTR               已完成第一版
Phase 1.10：推荐底座工业化诊断层                      已完成第一版
Phase 1.11：recall/source merge 泛化优化               已完成验证
Phase 1.12：two_tower recall POC                        已完成验证
Phase 1.13：YouTubeDNN 召回主路与排序承接               已完成验证
Phase 1.14：ranking v2 / LTR v2 固定召回池验证          已完成验证
Phase 1.15：YouTubeDNN pool100 冻结与隔离 ablation      已完成
Phase 1.16：item_graph recall 生成与接入验证              已完成验证但未晋升
Phase 1.18：two_tower_seed item-neighbor 旁路验证        已完成验证但未晋升
Phase 1.19：DeepWalk graph_walk_seed 结构召回旁路验证     已完成验证但未晋升
Phase 2：商品展示卡 + 服务层 + React Web Demo           已完成第一版
Phase 2.5：Session Replay + 一键 E2E 推荐闭环           已完成第一版
Phase 3：多角色 Simulation Scene / Batch Evaluation     已完成第一版
Phase 3.5：模型驱动模拟用户策略                        已完成第一版
Phase 4：Agent 综合评估闭环与训练信号收口               已完成第一版
```

当前核心判断：

> 系统已经从“候选池召回不到目标”推进到“Agent 推荐、结构化反馈、商品展示、Session Replay、多角色 Simulation 和 Agent 综合评估都能闭环演示”。title/category-only semantic、source-aware fusion、LTR baseline 与 item-level feature rerank 仍是推荐 backbone 的可解释对照；Agent 现在被明确放在独立交互决策层，而不是传统精排模块。当前 Phase 4 的重点不是宣称已经完成 SFT/GRPO，而是先用 baseline/enhanced 对比、五维 scorecard、internal artifact 和 training signals，把 Web Demo / Simulation 产生的 session、feedback、replay 轨迹收敛成可校验的训练前证据。

### Phase 1.31/1.32 排序算法实验回填

Phase 1.31 已把 `ranking_algorithm_experiment` scaffold 固化为统一底座，统一接入 method spec、registry、comparison report 和 baseline / variant / blocked 四类 row。Phase 1.32 则只做首批诊断性运行：规则 champion 复验、浅层 learned fine-ranker 变体和树模型准备都按 diagnostic-only / blocked 收口，tree / LambdaMART 仍停留在依赖与导出准备，不写成晋升结论。

这轮运行始终保持 `frozen pool200`、`candidate_pool_size=200`、`top_k=5`，`online_metric_claims=[]` 继续为 future-only。已验证 `./.venv/Scripts/python.exe -m py_compile rs_core/recsys/ranking.py rs_core/recsys/evaluation.py rs_core/workflow/hybrid_demo.py scripts/run_phase_1_30_physical_ranking_pipeline.py scripts/run_phase_1_26_real_ranking_experiments.py` 与 `./.venv/Scripts/python.exe -m pytest tests/test_evaluation.py tests/test_hybrid_demo.py tests/test_ltr.py tests/test_phase_1_31_ranking_scaffold.py -q`，并保留 `outputs/ranking/phase_1_30_physical_ranking_pipeline_regression/comparison.json`、`outputs/ranking/phase_1_26_real_ranking_experiments_regression/comparison.json`、`outputs/ranking/phase_1_31_ranking_algorithm_scaffold_smoke/comparison.json` 作为回填证据。

### Phase 3 树模型 / LambdaMART 诊断回填

Phase 3 的关键不是把 GBDT / LambdaMART 名称跑出来，而是确认树模型是否真的具备训练依赖、group/objective 与 serving 迁移条件。当前结果显示，tree 路线已经能导出训练行，但仍不能把依赖检查误写成晋升证据。

已核验证据：`scripts/run_phase_3_tree_ranking_experiments.py`、`tests/test_phase_3_tree_ranking_experiments.py`、`outputs/ranking/phase_3_tree_ranking_experiments_smoke/comparison.json`。smoke 口径保持 `candidate_pool_size=200`、`top_k=5`、training rows=2217、positive=16、negative=2201；`py_compile` 通过，Phase3/Phase2/Phase1 scaffold/evaluation pytest 12 passed，recall regression pytest 23 passed，`limit_users=20` smoke 通过。

因此本轮只把 `sklearn` GBDT 保留为 diagnostic-only；LambdaMART 即使依赖或 GPU 可用，仍因 serving adapter、valid-test promotion gate、objective recovery condition 不完整而 blocked。`merge_for_user`、召回语义和 future-only 在线指标都没有变化。

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
configs/demo/hybrid_demo/hybrid_demo_electronics_1000_semantic.yaml
configs/demo/hybrid_demo/hybrid_demo_electronics_1000_lopo_semantic.yaml
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
configs/demo/hybrid_demo/hybrid_demo_electronics_1000_semantic_rerank.yaml
configs/demo/hybrid_demo/hybrid_demo_electronics_1000_lopo_semantic_rerank.yaml
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

### 10k source-aware fusion 对照

在 10k `semantic_title` 实验后，问题进一步从“semantic 是否能召回 target”推进到“融合排序如何保护 ItemCF 和多源一致性”。新增默认关闭的 `source_aware_fusion`：

```json
"source_aware_fusion": {
  "enabled": true,
  "itemcf_source_boost": 8.0,
  "itemcf_multi_source_boost": 4.0,
  "semantic_only_penalty": 4.0,
  "popular_only_penalty": 2.0
}
```

它不改变召回，也不改变原始 `rank_weights`，只在排序阶段对 source 组合做轻量可解释调整，并在 `rerank_events` 中记录 `source_aware_fusion` 事件。实验报告的 `config_summary` 已显式记录该配置。

10k valid/test 温和版结果：

```text
semantic_title baseline hit_rate_at_k = 0.019635
source-aware hit_rate_at_k = 0.019635
ranked_hit_users = 14 -> 14
candidate_hit_rank_avg = 15.416667 -> 15.783333
```

10k LOPO 温和版结果：

```text
semantic_title baseline hit_rate_at_k = 0.755427
source-aware hit_rate_at_k = 0.755427
ranked_hit_users = 1044 -> 1044
candidate_hit_rank_avg = 40.308937 -> 35.738829
candidate_hit_rank_p50 = 47.0 -> 41.0
```

强保护版诊断结果：

```text
LOPO hit_rate_at_k = 0.755427 -> 0.810420
valid/test hit_rate_at_k = 0.019635 -> 0.011220
```

阶段性判断：

> source-aware fusion 的方向是有效的：强保护 ItemCF 可以把 LOPO target 明显推前，说明排序层确实存在可优化空间。但强保护会牺牲 valid/test 中由 semantic 命中的 target，因此默认配置必须保守。温和版不提升 Top-K hit，但保持主指标不受损，并改善 LOPO 候选池内排名分布。下一步如果继续在排序层优化，应从手写规则升级到可训练 ranker，学习 source 组合、multi-source、semantic-only、popular-only 等特征权重。

### Phase 1.9：轻量 learning-to-rank baseline

基于 source-aware fusion 暴露出的手写规则边界，新增默认关闭的 pure-Python LTR baseline：

- `rs_core/recsys/ltr.py`：抽取 source / score / interaction / metadata 特征，提供 pairwise perceptron 训练与线性打分。
- `rs_core/workflow/ltr_training.py` + `scripts/train_ltr_ranker.py`：复用 hybrid demo 候选生成和 LOPO / valid_test holdout label 生成训练样本。
- `rank_candidates()`：当 `ltr_model.enabled=true` 时额外输出 `ltr_score` 和 `ltr_model` rerank event；默认关闭时原排序不变。

10k LOPO 训练结果：

```text
training rows = 64900
positive_rows = 1298
pairs_seen = 129800
updates = 486
nonzero_weight_count = 18
```

模型学到的方向符合 source-aware 诊断：

```text
itemcf_source = +2.34
itemcf_multi_source = +2.21
multi_source = +1.26
semantic_only = -0.85
popular_only = -0.54
score_semantic = -0.46
```

10k LOPO 评估：

```text
semantic_title baseline hit_rate_at_k = 0.755427
source-aware hit_rate_at_k = 0.755427
ltr hit_rate_at_k = 0.758321
ranked_hit_users = 1044 -> 1048
candidate_hit_rank_avg = 40.308937 -> 32.591680
candidate_hit_rank_p50 = 47.0 -> 33.0
```

valid/test 泛化检查：

```text
semantic_title baseline hit_rate_at_k = 0.019635
source-aware hit_rate_at_k = 0.019635
ltr hit_rate_at_k = 0.014025
ranked_hit_users = 14 -> 10
candidate_hit_rank_avg = 15.416667 -> 17.833333
```

阶段性判断：

> LTR baseline 成功把手写 source-aware 经验转成可训练权重，并在 LOPO 中带来 Top-K 和候选命中排名改善；但同一个 LOPO 口径训练出的模型在 valid/test 上下降，说明它目前是排序学习 baseline / 诊断工具，不应包装成默认泛化提升。下一步如果继续优化排序，应拆出独立 train/validation split、做 score_scale 校准，或引入更强的 LTR 模型；如果转向 Agent 主线，则把 LTR 作为 backbone 可解释对照，而不是 Agent 交互能力的一部分。

### 2026-05-13 - Phase 2 fine-rank batch 收口

补齐 `scripts/run_phase_2_fine_rank_algorithm_batch.py` 和 `tests/test_phase_2_fine_rank_algorithm_batch.py` 后，Phase 2 learned/tree 批量实验统一收口到 fine_rank full-pool scoring 入口。`./.venv/Scripts/python.exe -m py_compile scripts/run_phase_2_fine_rank_algorithm_batch.py tests/test_phase_2_fine_rank_algorithm_batch.py` 与 `./.venv/Scripts/python.exe -m pytest tests/test_phase_2_fine_rank_algorithm_batch.py -q` 已通过（`3 passed`）；当前 learned rows 仅保留 diagnostic-only，tree/LambdaMART 仅做 blocked/preparation，不把任何 LTR/GBDT/LambdaMART 结果写成 promotion evidence，也不改变 frozen pool200 / `candidate_pool_size=200` / `top_k=5` / recall 语义边界。

### Phase 1.10：推荐底座工业化诊断层

在 Phase 1.9 之后，本阶段没有继续堆新模型，而是先补工业化离线指标与 gate report，用来判断下一步到底应该优化召回、source merge、排序/LTR，还是进入双塔/粗排/精排等更复杂架构。

新增诊断指标包括：

- `recall_at_k` / `recall_at_pool`
- `ndcg_at_k`
- `mrr_at_k`
- `map_at_k`
- `candidate_hit_rank_p90`
- `per_source_candidate_contribution`
- `per_source_topk_contribution`
- `source_overlap`
- `latency`
- `diagnostic_gate`

10k valid/test 与 LOPO 对照结果：

| 实验 | eval users | candidate hit users | ranked hit users | hit@5 | recall@pool | ndcg@5 | mrr@5 | rank avg | rank p50 | rank p90 | fallback | gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| valid/test semantic_title | 713 | 60 | 14 | 0.019635 | 0.034086 | 0.004996 | 0.009210 | 15.416667 | 11.5 | 32.0 | 0.088889 | `phase_1_11_recall_source_merge` |
| valid/test source-aware | 713 | 60 | 14 | 0.019635 | 0.034086 | 0.004629 | 0.008205 | 15.783333 | 12.5 | 33.0 | 0.088889 | `phase_1_11_recall_source_merge` |
| valid/test LTR | 713 | 60 | 10 | 0.014025 | 0.034086 | 0.002638 | 0.005259 | 17.833333 | 16.0 | 36.0 | 0.088889 | `phase_1_11_recall_source_merge` |
| LOPO semantic_title | 1382 | 1298 | 1044 | 0.755427 | 0.939219 | 0.298039 | 0.158309 | 40.308937 | 47.0 | 50.0 | 0.0 | `phase_1_12_ranking_ltr_gate` |
| LOPO source-aware | 1382 | 1298 | 1044 | 0.755427 | 0.939219 | 0.314323 | 0.179317 | 35.738829 | 41.0 | 46.0 | 0.0 | `phase_1_12_ranking_ltr_gate` |
| LOPO LTR | 1382 | 1298 | 1048 | 0.758321 | 0.939219 | 0.302548 | 0.163326 | 32.591680 | 33.0 | 48.0 | 0.0 | `phase_1_12_ranking_ltr_gate` |

关键观察：

1. valid/test 的 `candidate_hit_rate_at_pool=0.084151`、`recall_at_pool=0.034086`，说明主瓶颈仍是真实切分下的候选覆盖，而不是先上精排就能解决。
2. valid/test 中 target source 主要来自 semantic：`per_source_candidate_contribution.semantic=72`，但最终 Top-K hit 只有 14 个用户，说明 semantic recall 有贡献但还不稳定。
3. source-aware 在 valid/test 保持 `hit@5=0.019635`，没有带来泛化提升；在 LOPO 中改善 `ndcg@5`、`mrr@5` 和候选命中排名，适合作为排序诊断证据。
4. LTR 在 LOPO 中将 `hit@5` 提升到 0.758321、`ranked_hit_users` 提升到 1048，但 valid/test 降到 0.014025，不能默认启用。
5. 排序耗时不是瓶颈：valid/test LTR 的 `ranking_p95_seconds=0.001366`，候选池约 50，不需要独立粗排。
6. `diagnostic_gate` 在 valid/test 三组都指向 `phase_1_11_recall_source_merge`，在 LOPO 三组都指向 `phase_1_12_ranking_ltr_gate`，说明 valid/test 是泛化风险检查，LOPO 是内部排序诊断，两者不能混用。

Backbone readiness 判断：

- 作为 Agent 工程底座：足够。当前推荐 backbone 已有多路召回、候选合并、排序、source-aware/LTR 对照、离线指标、报告和 gate，足以支撑另一个窗口继续推进 Agent trajectory / simulation / serving / frontend。
- 作为强推荐算法底座：还不够。valid/test 候选覆盖仍低，下一阶段应优先进入 Phase 1.11 recall/source merge，而不是直接上双塔、粗排或默认 LTR。
- 是否需要独立粗排：当前不需要。`candidate_pool_size≈50`，ranking p95 毫秒级以下，粗排不是当前瓶颈。
- 是否需要双塔：Phase 1.10 时不做；后续 Phase 1.12 已作为默认关闭旁路推进到 PyTorch 双塔 smoke，但当前只有训练 `limit_users=10`、评估 `limit_users=30` 的证据，不能当作完整 10k 晋升结论。
- LTR 是否默认启用：不启用。LOPO 收益只能说明排序特征有价值，valid/test 下降说明当前模型不能通过泛化 gate。

阶段性判断：

> Phase 1.10 把“效果不好”拆成了可验证的瓶颈判断：valid/test 主要是 recall/source merge，LOPO 暴露排序仍有优化空间，latency 和粗排不是当前瓶颈。下一步应该先提升真实切分下的候选覆盖和 source merge 质量，再回到独立验证切分上的 LTR / 更强排序模型。

### 10k 默认晋升硬门禁复核

本轮只把 valid/test 作为默认晋升口径，LOPO 只作为 sanity / 诊断口径。实验入口均为：

```text
./.venv/Scripts/python.exe scripts/run_hybrid_demo.py --config <config>
```

召回 source key 的审计边界为：`popular`、`category`、`itemcf_weak`、`itemcf_strong`、`semantic`。`semantic_title` 是配置 / 实验变体，不是新的 source key；`user_profile` 只作为 Agent 偏好信号，不作为 10k 独立召回源；`two_tower` POC 配置与报告存在，但不纳入本次默认晋升 gate。

valid/test 默认晋升硬门禁以 baseline `metrics.latency.candidate_generation_p95_seconds≈0.000637s` 为基准，延迟阈值为 `<= baseline * 1.2≈0.000764s`：

| 实验 | candidate_hit_rate_at_pool | recall_at_pool | hit@5 | candidate_hit_users | candidate_generation_p95_seconds | 硬延迟门禁 | 默认晋升结论 |
|---|---:|---:|---:|---:|---:|---|---|
| baseline_main | 0.032258 | 0.010322 | 0.007013 | 23 | 0.000637 | baseline | 基准 |
| semantic_title | 0.084151 | 0.034086 | 0.019635 | 60 | 0.402541 | 未通过 | 不晋升 |
| semantic_title_source_aware | 0.084151 | 0.034086 | 0.019635 | 60 | 0.400739 | 未通过 | 不晋升 |
| semantic_title_ltr | 0.084151 | 0.034086 | 0.014025 | 60 | 0.388379 | 未通过 | 不晋升 |

LOPO 只用于 sanity / 诊断，不能替代 valid/test 晋升判断。LOPO baseline `metrics.latency.candidate_generation_p95_seconds≈0.000775s`，硬延迟阈值为 `<=0.000930s`：

| 实验 | candidate_hit_rate_at_pool | recall_at_pool | hit@5 | candidate_hit_users | candidate_generation_p95_seconds | 硬延迟门禁 | 诊断结论 |
|---|---:|---:|---:|---:|---:|---|---|
| lopo_baseline | 0.053546 | 0.053546 | 0.049204 | 74 | 0.000775 | baseline | 基准 |
| lopo_semantic_title | 0.939219 | 0.939219 | 0.755427 | 1298 | 0.353264 | 未通过 | 只能说明 sanity 改善 |
| lopo_semantic_title_source_aware | 0.939219 | 0.939219 | 0.755427 | 1298 | 0.334299 | 未通过 | 排序诊断有效但不晋升 |
| lopo_semantic_title_ltr | 0.939219 | 0.939219 | 0.758321 | 1298 | 0.337061 | 未通过 | LTR 只保留为诊断 baseline |

硬门禁结论：

> `semantic_title` 及其 source-aware / LTR 变体在 valid/test 上相对 baseline 有候选覆盖和 Top-K 命中提升，但 `metrics.latency.candidate_generation_p95_seconds` 均远高于 `baseline * 1.2` 的硬阈值，因此不能作为默认配置晋升。LOPO 大幅提升只能证明可控 holdout 下的 sanity 和排序诊断价值，不能替代 valid/test 泛化 gate。

### Phase 1.12：PyTorch 双塔向量召回 10k 证据

本阶段把前一轮 smoke 级双塔链路推进到同等 10k 数据规模验证：DSSM-style 与 YouTubeDNN-style 均使用项目默认 `.venv`，训练环境为 `torch 2.11.0+cu128`，`training_backend.device=cuda`，并保持 default-off / strict gate 约束。

实现过程中发现两个工程问题：

1. 初始安装的是 `torch 2.11.0+cpu`，虽然版本不低，但不会使用 GPU；已切换为 CUDA wheel。
2. 初始 PyTorch 训练是逐样本循环，即使模型在 CUDA 上也无法有效利用 GPU；已改为 batch tensor 训练，并记录 `batch_size`、`training_seconds`、`peak_cuda_memory_mb` 和 `batch_training=true`。

batch tuning 使用 2000 用户样本对比 `128/512/1024` 后，选择：

| variant | batch_size | 选择原因 |
|---|---:|---|
| DSSM | 512 | 比 128 更快，sample positive score 基本持平；1024 虽更快但 score 下降。 |
| YouTubeDNN | 128 | 512/1024 虽接近或更快，但 loss 和 sample positive score 明显变差。 |

训练结果：

| 训练 | batch_size | training_seconds | peak_cuda_memory_mb | loss_history | sample_positive_score_avg |
|---|---:|---:|---:|---|---:|
| DSSM | 512 | 18.890 | 26.164 | `[1.438792, 1.404867, 1.398311]` | 0.540509 |
| YouTubeDNN | 128 | 19.649 | 31.814 | `[1.987195, 1.866471, 1.770454]` | 0.692877 |

完整 10k valid/test 与 LOPO 结果：

| 实验 | candidate_hit_rate_at_pool | recall_at_pool | candidate_hit_users | hit@5 | fallback | candidate_p95 | strict gate |
|---|---:|---:|---:|---:|---:|---:|---|
| semantic_title valid/test baseline | 0.084151 | 0.034086 | 60 | 0.019635 | 0.088889 | 0.355698s | - |
| DSSM valid/test | 0.071529 | 0.029375 | 51 | 0.022440 | 0.0 | 0.430508s | `promotable=false` |
| YouTubeDNN valid/test | 0.077139 | 0.031527 | 55 | 0.023843 | 0.0 | 0.465984s | `promotable=false` |
| semantic_title LOPO baseline | 0.939219 | 0.939219 | 1298 | 0.755427 | 0.0 | 0.354190s | sanity only |
| DSSM LOPO | 0.938495 | 0.938495 | 1297 | 0.762663 | 0.0 | 0.411996s | `lopo_sanity_only_no_promotion` |
| YouTubeDNN LOPO | 0.954414 | 0.954414 | 1319 | 0.788712 | 0.0 | 0.400579s | `lopo_sanity_only_no_promotion` |

结论：

- 两个训练式双塔都没有通过 valid/test 晋升 gate：候选池覆盖和 `candidate_hit_users` 都低于 `semantic_title` baseline。
- DSSM / YouTubeDNN 的 Top-K hit@5 略高于 baseline，但这是在候选池覆盖下降的前提下发生的，不能解释为召回链路成功。
- YouTubeDNN 在 LOPO 上明显更好，说明模型能利用近期行为做同分布 holdout sanity，但 LOPO 不能替代 valid/test 泛化 gate。
- candidate generation p95 仍超过 `0.05s` budget，因此即使效果接近，也不能默认晋升。
- Node2Vec / DeepWalk、MIND / SDM、TDM、DeepFM / NCF 仍保留为 deferred roadmap，本批未实现。

随后追加了 `semantic_title + YouTubeDNN` 主路组合 ablation，不再验证“双塔单独赢”，而是测试它能否作为候选池增强与 semantic_title 组合：

| 临时组合 | candidate_pool_size | candidate_hit_rate_at_pool | recall_at_pool | candidate_hit_users | hit@5 | candidate_p95 |
|---|---:|---:|---:|---:|---:|---:|
| semantic_title baseline | 50 | 0.084151 | 0.034086 | 60 | 0.019635 | 0.355698s |
| YouTubeDNN low-min | 50 | 0.085554 | 0.032911 | 61 | 0.019635 | 0.476785s |
| YouTubeDNN pool80 | 80 | 0.096774 | 0.039319 | 69 | 0.018233 | 0.509201s |
| YouTubeDNN pool100 conservative | 100 | 0.105189 | 0.041803 | 75 | 0.018233 | 0.521105s |

低权重和 Top-K minimum 继续验证后，`hit@5` 仍无法超过 baseline；提高 two_tower 排序权重还会进一步压低 Top-K。临时 ablation 输出已清理，只保留结论。

当前判断：

> 训练式双塔已经具备可复现 artifact、CUDA batch 训练、向量索引、valid/test + LOPO paired gate 和默认关闭配置。作为 `semantic_title + YouTubeDNN` 组合召回，它能把 10k valid/test 候选覆盖从 `0.084151` 提升到 `0.105189`，`candidate_hit_users` 从 60 提升到 75，说明双塔确实有召回增量；但 Top-K hit 没有同步提升，candidate p95 也从约 0.36s 升到约 0.52s。因此它可以作为“候选池增强候选方案”，但还不能直接默认进最终 Top-K 主路。下一步应做排序承接：把 two_tower 命中、semantic overlap、multi-source 和 rank position 作为 LTR / feature rerank 特征，而不是继续手调 two_tower 权重。

### Phase 1.11：recall/source merge 验证记录

Phase 1.11 尝试在 10k `semantic_title` 基础上做 recall/source merge 改进：提高 ItemCF / semantic 候选预算，使用 `balanced_source_budget` 合并策略，限制 popular 上限，并通过 `candidate_multi_source_boost` 与 `topk_source_minimums` 保护多源和 ItemCF 信号。

本轮先完成了代码级验证：

```text
./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py
41 passed in 0.23s

./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts
通过
```

baseline 指标已成功复现：

| 实验 | users_evaluated | candidate_hit_rate_at_pool | recall_at_pool | candidate_hit_users | hit@5 | fallback |
|---|---:|---:|---:|---:|---:|---:|
| 10k semantic_title valid/test baseline | 713 | 0.084151 | 0.034086 | 60 | 0.019635 | 0.088889 |
| 10k semantic_title LOPO baseline | 1382 | 0.939219 | 0.939219 | 1298 | 0.755427 | 0.0 |

重跑完整 Phase 1.11 后，valid/test 没有通过 gate：

| 实验 | users_evaluated | candidate_hit_rate_at_pool | recall_at_pool | candidate_hit_users | hit@5 | fallback | candidate_p95 | gate |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Phase 1.11 valid/test | 713 | 0.061711 | 0.024854 | 44 | 0.018233 | 0.088889 | 5.079586s | phase_1_11_recall_source_merge |
| Phase 1.11 LOPO | 1382 | 0.941389 | 0.941389 | 1301 | 0.793054 | 0.0 | 5.645230s | phase_1_12_ranking_ltr_gate |

结论：

- valid/test 候选覆盖从 `0.084151` 降到 `0.061711`，`candidate_hit_users` 从 60 降到 44，没有达到 full target 或 partial target。
- hit@5 从 `0.019635` 降到 `0.018233`，没有超过 20% relative 下降，但这是因为 candidate pool 覆盖本身已退化，不能算成功。
- LOPO sanity 通过且提升：`candidate_hit_rate_at_pool` 从 `0.939219` 到 `0.941389`，hit@5 从 `0.755427` 到 `0.793054`，fallback 维持 0。
- 代价很明显：`candidate_generation_p95_seconds` 从 baseline 约 `0.385658s` 升到 valid/test `5.079586s`、LOPO `5.645230s`，说明当前 seed-aware semantic 仍是全量扫描路径，不能直接作为默认方案。

当前判断：

> Phase 1.11 的实现通过了单测、编译和 LOPO sanity，但没有通过真实 valid/test 泛化 gate；这说明“扩大历史 seed + balanced source budget + 当前 IDF semantic 扫描”更像是在可控 LOPO 中增强 ItemCF/semantic 暴露，却损害了 valid/test 候选命中。下一步不应进入 Phase 1.12 排序/LTR，也不应默认启用当前 Phase 1.11 参数，而应继续做召回/source merge 诊断：先拆分 ablation，确认是 semantic IDF、popular cap、source budget 还是 ItemCF seed decay 造成 valid/test 退化。

### Phase 1.17：固定候选池 rank_weights 单因素调权

Phase 1.17 回到已经冻结的 `semantic_title + YouTubeDNN pool100` 候选池，只做排序层 `rank_weights` 的单因素 smoke test。本轮不改召回、不改 `candidate_pool_size=100`，也不启用 `ranking_v2`、`source_aware_fusion`、`item_feature_rerank`、`ltr_model` 或 LLM rerank；9 个实验只分别调整 `semantic`、`popular`、`two_tower` 三个权重。

same-run baseline 指标如下：

| 实验 | candidate_hit_users | candidate_hit_rate_at_pool | recall_at_pool | fallback | candidate_count_avg | hit@5 | ndcg@5 | mrr@5 | rank p50 | rank p90 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 69 | 0.096774 | 0.040439 | 0.0 | 97.936752 | 0.019635 | 0.005876 | 0.012202 | 18.0 | 55.0 |

所有非 baseline 配置都与 baseline 保持相同的候选池统计：`candidate_hit_users=69`、`candidate_hit_rate_at_pool=0.096774`、`recall_at_pool=0.040439`、`fallback_rate=0.0`、`candidate_count_avg=97.936752`，因此没有 INVALID case，指标差异可以归因到排序权重。

| 调权实验 | changed_weight | new_value | hit@5 | hit delta | ndcg delta | mrr delta | 判定 |
|---|---|---:|---:|---:|---:|---:|---|
| `phase_1_17_rank_weight_popular_0_8` | popular | 0.8 | 0.025245 | +0.005610 | +0.001587 | +0.001566 | PROMOTION |
| `phase_1_17_rank_weight_popular_0_9` | popular | 0.9 | 0.021038 | +0.001403 | +0.000250 | +0.000467 | PROMOTION |
| `phase_1_17_rank_weight_semantic_1_3` | semantic | 1.3 | 0.021038 | +0.001403 | +0.000137 | 0.000000 | PROMOTION |
| `phase_1_17_rank_weight_semantic_1_0` | semantic | 1.0 | 0.015428 | -0.004207 | 下降 | 下降 | NO_GAIN |
| `phase_1_17_rank_weight_semantic_1_1` | semantic | 1.1 | 0.019635 | 0.000000 | 下降 | 下降 | NO_GAIN |
| `phase_1_17_rank_weight_popular_1_1` | popular | 1.1 | 0.019635 | 0.000000 | 下降 | 下降 | NO_GAIN |
| `phase_1_17_rank_weight_two_tower_1_0` | two_tower | 1.0 | 0.019635 | 0.000000 | 持平 | 持平 | NO_GAIN |
| `phase_1_17_rank_weight_two_tower_1_1` | two_tower | 1.1 | 0.019635 | 0.000000 | 持平 | 持平 | NO_GAIN |
| `phase_1_17_rank_weight_two_tower_1_3` | two_tower | 1.3 | 0.019635 | 0.000000 | 持平 | 持平 | NO_GAIN |

结论：

- `popular=0.8` 是本轮最强 promotion candidate，说明当前 Top-K 中 popular 信号略偏强，适度降权能让更多候选池内命中商品进入 Top-K。
- `popular=0.9` 与 `semantic=1.3` 也严格超过 same-run baseline，但提升幅度较小，应作为备选或后续稳定性复核对象。
- `semantic` 下调、`popular` 上调和 `two_tower` 单独调权都没有带来 Top-K 收益；本轮没有 PARTIAL_DIAGNOSTIC case。
- 这些结论只覆盖 frozen pool 上的排序权重，不代表召回主路改善；后续如果要晋升默认配置，应优先复核 `popular=0.8` 在更多切分或重复运行中的稳定性。

证据产物：

```text
outputs/archive/root_files/phase_1_17_rank_weight_comparison.json
outputs/archive/root_files/phase_1_17_rank_weight_required_matrix.json
outputs/archive/root_files/phase_1_17_rank_weight_required_matrix.csv
```

### Phase 1.17b：popular=0.8 稳定性复核与 baseline 晋升

### 为什么进入这一轮

Phase 1.17 已经在 frozen candidate pool 上找到 `popular=0.8` 的 promotion 候选，但单次 smoke 结果还不足以直接写成默认基线。Phase 1.17b 的目标是做同跑 rerun 和邻近权重复核，确认这个收益不是候选池波动，也不是偶然 case 偏差。

### 遇到的问题

1. 需要确认 `popular=0.8` 的收益是否能在 same-run rerun 中复现，而不是只在单次实验里成立。
2. 需要比较邻近配置 `popular=0.75` 和 `popular=0.85`，判断 0.8 是否是局部最优点。
3. 这轮只允许覆盖 frozen-pool ranking，不能把结果扩写成召回改进或全链路泛化结论。

### 定位方式

对照 `outputs/archive/root_files/phase_1_17b_rank_weight_comparison.json` 与 `outputs/archive/root_files/phase_1_17b_popular_0_8_case_effects.json`，核对 baseline 与 `popular=0.8/0.75/0.85` 的候选池统计、Top-K 指标和 case-level 变化；重点看 candidate-hit 稳定性、Top-K 增益，以及进入 Top-K 的 target 是否主要来自 semantic，避免把 popular 降权误读成召回变更。

### 结果

- same-run rerun 中，baseline 与 `popular=0.8` 的候选池统计完全一致：`candidate_hit_users=69`、`candidate_hit_rate_at_pool=0.096774`、`recall_at_pool=0.040439`、`fallback_rate=0.0`、`candidate_count_avg=97.936752`。
- `popular=0.8` 将 `hit_rate_at_k` 从 `0.019635` 提升到 `0.025245`，`ndcg_at_k` 从 `0.005876` 提升到 `0.007463`，`mrr_at_k` 从 `0.012202` 提升到 `0.013768`，因此继续保持 PROMOTION。
- 邻近配置 `popular=0.75` 也提升到 `0.02244`，`popular=0.85` 提升到 `0.021038`，说明 0.8 不是孤立噪声点，而是该局部区间内的更优选择。
- case-level 变化显示 5 个 shared target 进入 Top-K，且新增命中几乎都来自 semantic target；退出 Top-K 的 case 为 0，rank 改善 49 个、恶化 4 个，变化主要来自减少 popular / category+popular 在目标上方的遮挡。
- `users_with_changed_recommendation_top5=1424`，说明这个调权会影响大量用户的最终曝光，但候选池不变，变化来自排序层而不是召回层。

### 解决方式

把 `popular=0.8` 作为新的 frozen-pool ranking baseline，并把 `popular=0.75` / `0.85` 保留为稳定性复核对照，而不是继续扩大搜索空间。这样可以先固定当前最优排序基线，再把后续优化聚焦到更明确的排序特征或召回改动上。

### 验证结果

`outputs/archive/root_files/phase_1_17b_rank_weight_comparison.json` 与 `outputs/archive/root_files/phase_1_17b_popular_0_8_case_effects.json` 同时证明：候选池指标不变、Top-K 指标提升、case-level 命中变化可解释，因此 `popular=0.8` 可以晋升为新的 frozen-pool ranking baseline；邻近 `0.75/0.85` 只作为稳定性参考，不作为主基线。

### 面试可讲点

这轮可以讲成“固定候选池后做排序权重的局部稳定性验证”。我先用 same-run rerun 排除池波动，再用邻近权重确认 0.8 是局部最优，最后把结论严格限制在 frozen-pool ranking 范围内，避免把排序收益误写成召回收益。

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
11. 10k source-aware fusion 强保护版能把 LOPO `hit_rate@5` 从 0.755427 提升到 0.810420，但会把 valid/test 从 0.019635 降到 0.011220，说明 ItemCF 保护存在评估口径 tradeoff。
12. 10k source-aware fusion 温和版保持 valid/test 和 LOPO `hit_rate@5` 不变，并把 LOPO `candidate_hit_rank_avg` 从 40.308937 改善到 35.738829，说明它更适合作为安全默认配置。
13. Phase 1.9 LTR baseline 在 LOPO 中把 `hit_rate@5` 从 0.755427 提升到 0.758321、`candidate_hit_rank_avg` 改善到 32.591680，但 valid/test 降到 0.014025，说明当前训练排序器还需要独立验证切分和校准。
14. Phase 1.17b 复核确认 `popular=0.8` 在 frozen-pool ranking 上可稳定晋升，且 `popular=0.75/0.85` 也保持同方向收益，说明当前局部最优点更接近 0.8 而不是继续抬高 popular。

### 尚未解决

1. title/category-only 后仍有部分 candidate-hit target 停留在 Top-K 外。
2. source-aware fusion 只能带来安全的小幅排名分布改善，还不能稳定提升 Top-K hit。
3. strong ItemCF protection 与 valid/test semantic target 之间存在 tradeoff，需要学习排序而不是继续手调强规则。
4. semantic-only 候选是否应该被限制 Top-K 曝光，还是只降低 candidate minimum？
5. 是否需要更细的 source interaction / item-level feature，例如 semantic + category、semantic + ItemCF、semantic + recent positive overlap？
6. 是否需要在 title/category-only 基础上增加 stopword/domain-word filtering 或 conservative candidate minimum？

### Phase 1.12：two_tower recall POC

在 Phase 1.11 source-merge 组合被 valid/test gate 否决后，本轮没有继续硬调同一组规则，而是新增一路默认关闭的 `two_tower` 召回 POC。它不是完整训练式双塔模型，而是用商品文本 token-IDF 向量近似 item tower，用用户最近正反馈 item 向量聚合近似 user tower，在 10k 规模下先用确定性 cosine-style 检索验证 U2I 召回方向是否值得继续。

新增能力保持配置隔离：

- `two_tower_enabled` 默认关闭。
- 新 source 名为 `two_tower`，不合并到 `semantic`。
- 新配置：`configs/demo/hybrid_demo/hybrid_demo_electronics_10000_semantic_title_two_tower_poc.yaml` 与 `configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title_two_tower_poc.yaml`。
- LTR 仍保持 disabled。

代码级验证：

```text
./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py
46 passed

./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts
通过
```

完整实验结果：

| 实验 | users_evaluated | candidate_hit_rate_at_pool | recall_at_pool | candidate_hit_users | hit@5 | fallback | two_tower candidate hits | candidate_p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| semantic_title valid/test baseline | 713 | 0.084151 | 0.034086 | 60 | 0.019635 | 0.088889 | - | 约 0.344823s recommendation p95 |
| two_tower POC valid/test | 713 | 0.086957 | 0.035813 | 62 | 0.022440 | 0.088889 | 41 | 1.308537s |
| semantic_title LOPO baseline | 1382 | 0.939219 | 0.939219 | 1298 | 0.755427 | 0.0 | - | 约 0.316920s recommendation p95 |
| two_tower POC LOPO | 1382 | 0.939942 | 0.939942 | 1299 | 0.757598 | 0.0 | 86 | 1.138104s |

结论：

- two_tower POC 在 valid/test 上有小幅正向信号：`candidate_hit_users` 从 60 到 62，`candidate_hit_rate_at_pool` 从 `0.084151` 到 `0.086957`，hit@5 从 `0.019635` 到 `0.022440`。
- 但提升幅度还没达到 Phase 1.11 partial target（`candidate_hit_rate_at_pool>=0.092`、`recall_at_pool>=0.037`），diagnostic gate 仍指向 `phase_1_11_recall_source_merge`。
- LOPO sanity 基本稳定且略升，说明新增 source 没有破坏 ItemCF backbone。
- 延迟代价明显：valid/test candidate generation p95 到 `1.308537s`，LOPO 到 `1.138104s`，高于 baseline，但显著低于 Phase 1.11 seed-aware semantic 的 5 秒级。

当前判断：

> two_tower recall POC 不是“一上双塔就解决问题”，但它比 Phase 1.11 组合策略更健康：valid/test 小幅提升、LOPO 不坏、source contribution 能看到 `two_tower` 命中。下一步可以保留它为默认关闭的实验召回源，继续做更接近工业双塔的训练/负采样/向量索引版本，或者先做 two_tower-only / semantic+two_tower ablation，判断它与 semantic 的重叠是否过高。

---

## 下一步建议

Phase 1.10 的 gate 结果表明，下一步不应该直接上双塔、独立粗排或默认启用 LTR。当前候选池约 50，排序耗时不是瓶颈；LTR 虽然在 LOPO 中改善候选命中排名，但 valid/test 下降，不能通过泛化 gate。

建议进入：

```text
Phase 1.11：recall/source merge 泛化优化
```

目标是提高真实 valid/test 切分下的候选覆盖和 source merge 质量，优先处理 semantic_title 命中不稳定、source 贡献与 Top-K 贡献错配、候选池内 target 过少等问题。排序/LTR 可以继续作为诊断 baseline，但默认配置应以 valid/test gate 为准。

历史上已完成的 conservative title-focused semantic 对照记录如下，作为为什么不继续停留在 config-only 调参的依据：

```text
Phase 1.7d：conservative title-focused semantic 对照
```

当前已经有聚合诊断产物：

```text
outputs/hybrid_demo/hybrid_demo_small_electronics_1000_semantic_title/ranking_case_summary.json
outputs/hybrid_demo/hybrid_demo_small_electronics_1000_lopo_semantic_title/ranking_case_summary.json
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
configs/demo/hybrid_demo/hybrid_demo_electronics_1000_semantic_title_item_feature.yaml
configs/demo/hybrid_demo/hybrid_demo_electronics_1000_lopo_semantic_title_item_feature.yaml
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

---

### 2026-05-12 - Phase 1.23 sample-size LOPO 叙事补充

**任务：**
补写 Phase 1.23 的 sample-size sensitivity 中文叙事，明确它只是在 LOPO 内部做 recall-only sanity，不把结果误写成 valid_test 晋升证据。

**问题：**
100 / 1000 / 10000 三档样本下的 LOPO pool200 召回都很高，容易被误读成“低 recall 只是样本太少”；但这些结果和 Phase 1.21/1.22 的 valid_test holdout-hash baseline 不同口径，不能直接对比。

**定位：**
对照 `outputs/ranking/phase_1_23_sample_sensitivity/contract.json`、`metrics_by_sample.json`、`sample_size_sensitivity_summary.csv` 和 `report.json`，核对三档结果分别为 12/12=1.0、78/81=0.962963、1314/1382=0.950796，`candidate_count_avg` 依次为 52.166667、93.901235、128.83864；同时检查命中来源，发现更大样本下主要由 `itemcf_strong` / `itemcf_weak` 贡献，而不是 Phase 1.21 里解释 pool200-only 增益的 `semantic_title_category_expansion` / `popular`。

**解决：**
把叙事边界锁在 recall-only、pool200、LOPO internal split，并明确不做 ranking、Top-K、LTR rerank、holdout tuning 或 leakage 规避式包装；结论写成“数据/切分难度仍是主因，LOPO 证据不足以把 valid_test 低 recall 归因为样本规模”。

**验证：**
三档 LOPO 指标全部跑通且 fallback_rate=0.0；样本增大后候选供给确实上升，但 source 归因与 valid_test 基线不一致，说明 sample-size 变大并不自动等价于 valid_test recall 晋升。

**面试可讲点：**
这轮的价值不在“把 recall 做高”，而在“把证据边界说清楚”：我用同一 recall-only 合同验证了样本规模会影响候选供给，但也证明了 LOPO 不能直接替代 valid_test 口径，因此后续应优先做同风格 valid_test 大 split 或更严格的 leakage audit。

### 阶段性判断

> item-level feature rerank 没有带来新的 Top-K hit，但改善了 LOPO 目标商品的候选池内排名分布，并让排序变化可以通过 `item_features` 和 `rerank_events` 解释。它更适合作为后续 Agent 反馈和学习排序的特征接口，而不是单独的 hit-rate 提升方案。

---

## 总体面试叙事

这条主线可以总结成：

> 我先搭了一个传统推荐 backbone + Agent 独立交互层的最小闭环。然后没有直接追求复杂模型，而是通过 source coverage、candidate hit、Top-K exposure、LOPO sanity check 等诊断指标逐层定位问题。Phase 1.5 发现 valid/test 的主要瓶颈是召回覆盖；Phase 1.6 用 deterministic semantic recall 提升了候选池命中；Phase 1.7 又发现 Top-K 未提升的原因是目标商品虽然进入候选池，但排序位置仍然靠后。简单统一 boost semantic 无效，normalized scoring 改善排名分布但损失 Top-K hit，title/category-only semantic 则把 valid/test Top-K hit 从 1/30 提升到 2/30。10k source-aware fusion 进一步证明强保护 ItemCF 能提升 LOPO，但会伤害 valid/test；温和保护能安全改善候选池内排名分布，却不能稳定提升 Top-K hit。这说明纯 source-level 手调已经到边界，下一步应进入 learning-to-rank baseline，让模型学习 source 组合和 item-level 特征，而 Agent 仍作为推荐 backbone 之上的交互编排层。

当前长期排序路线可以概括为 recall → coarse rank → fine rank → rerank，但现在真正落地的物理范围只收在 frozen pool200 → learned fine ranker → bounded rerank trace。Phase 1.28 的 LOPO pointwise/pairwise smoke 已经能证明训练与推理链路可跑，但它仍然是 diagnostic-only，不是 promotion evidence；Phase 3 的树模型 / LambdaMART 仍因 `sklearn`、`xgboost`、`lightgbm` 依赖缺失、训练 adapter 不全和 GPU 验证不足而 blocked。在线 CTR/CVR/GMV/P95 统一放在 future-online 边界，不进入当前离线晋升口径。

这个叙事的价值在于：

- 不是堆模块，而是每一步都有诊断依据。
- 能讲清召回、排序、Agent 的边界。
- 能说明为什么暂时不做复杂 LLM Agent 或双塔。
- 能展示工业推荐系统里“定位瓶颈再优化”的思路。

### 2026-05-12 - Phase 1.25 工业排序研究收口

**任务：**
把 Phase 1.23 / 1.24 的 same-run 证据收束成工业排序研究文档，并同步补写过程日志。

**问题：**
1.23 / 1.24 都是 `VALID`，但 `hit_rate_at_k`、`ndcg_at_k`、`mrr_at_k` 全部持平，容易把实验可运行误解为默认晋升。

**定位：**
对照 `outputs/ranking/phase_1_23_pool200_ranking_isolation/comparison.json`、`outputs/ranking/phase_1_23_pool200_ranking_isolation/comparison.md`、`outputs/ranking/phase_1_24_pool200_semantic_near_miss_rescue/comparison.json`、`outputs/ranking/phase_1_24_pool200_semantic_near_miss_rescue/comparison.md`，核对 frozen pool200 的关键指标：`candidate_hit_rate_at_pool=0.123188`、`hit_rate_at_k=0.014493`、`ndcg_at_k=0.002779`、`mrr_at_k=0.006039`、`map_at_k=0.001208`、`candidate_hit_missed_topk_users=15`。

**解决：**
将研究边界收敛为工业指标概览、失败模式映射、两轮复盘和不超过 3 个轻量候选；明确不改召回、不动 `candidate_pool_size`、不做训练/集成、不晋升 LOPO。

**验证：**
`dic/experiments/ranking/phase_1_25/PHASE_1_25_INDUSTRIAL_RANKING_RESEARCH.md` 已落盘，内容和 frozen-pool 证据一致，且给出了后续实验的 stop gate。

**面试可讲点：**
这类工作能体现我如何把“实验做完”转成“证据说清楚”：先锁边界、再看 delta、最后才决定哪些候选值得继续。

### 2026-05-12 - Phase 1.25 pool200 召回体检与候选池健康收口

**任务：**
基于 `outputs/recall/phase_1_25_pool200_recall_health/` 的结果，补写 pool200 召回/候选生成健康叙事。

**问题：**
候选池虽然可跑通，但如果只看“有命中”容易忽略空候选、覆盖、候选规模分布和来源重叠，导致把召回健康误判为排序收益。

**定位：**
对照 `recall_health_report.json` / `.md`、`baseline/metrics.json`、`baseline/manifest.json`，核对 `empty_candidate_users=0`、`empty_candidate_rate=0.0`、`user_candidate_coverage_rate=1.0`、`candidate_count avg/min/p50/p90/max=157.112/67/160/200/200`、`candidate_hit_users@pool=19/138`、`catalog_candidate_coverage_count=12089`，并检查 source marginal hits：`semantic=4`、`popular=3`、`semantic_title_category_expansion=2`、`two_tower=1`，以及 top overlap：`itemcf_strong+itemcf_weak=0.736594`、`co_visit_fallback_repair+itemcf_weak=0.563265`、`semantic+semantic_title_category_expansion=0.52638`。

**解决：**
把结论锁定为“pool200 召回底座健康、候选池覆盖完整、来源贡献可解释”；只补召回体检与来源解释，不把 `candidate_recall@20/50/100/200` 或 `candidate_hit_rate@20/50/100/200` 误写成排序提升，也不引入 LTR/rerank/Top-K promotion。

**验证：**
`candidate_hit_rate@20/50/100/200=0.072464/0.108696/0.123188/0.137681`，`candidate_recall@20/50/100/200=0.034967/0.055921/0.05884/0.06971`；候选池无空用户、覆盖率 100%，说明召回健康问题已被体检证实可控。

**面试可讲点：**
这轮能讲成“先做候选池体检，再谈模型优化”：先用空候选、覆盖率、候选规模分布和 source overlap 判断底座是否稳定，避免把召回健康和排序收益混在一起。

### 2026-05-12 - Phase 1.25 normalized-additive 排序门禁验证

**任务：**
在 frozen pool200 候选池上验证 normalized-additive 排序平台是否只改变排序诊断，不引入召回、候选池规模、`top_k`、LTR、serving 或 frontend 合约漂移。

**问题：**
新增排序权重网格如果没有严格门禁，容易把候选池 hash/count 漂移、fallback 变化或二级指标局部变化误判成可晋升排序收益。

**定位：**
对照 `.omc/handoffs/team-exec-to-team-verify-phase-1-25-ranking-platform.md`、`outputs/ranking/phase_1_25_pool200_normalized_additive_limit500/comparison.json` / `.md`、`configs/ranking/phase_1_25/phase_1_25_pool200_*.yaml`、`rs_core/recsys/evaluation.py` 和 `tests/test_hybrid_demo.py`，核对 8 个变体均为 `candidate_pool_size=200`、`top_k=5`、`ltr_model=false`、`ranking_v2=false`、`item_feature_rerank=false`、`source_aware_fusion=false`。

**解决：**
保留 normalized-additive 为排序层诊断平台：有限权重网格、同跑 baseline、冻结候选 hash/count 对比、`strict_ranking_promotion_status` 强门禁；LTR 只允许 diagnostic-only，不允许 promotion。

**验证：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -q` 通过 80/80，`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过。limit-500 对照中 8 个变体 `all_variants_valid=true`、frozen hash 均为 `e664ad5ee7b133811d19e6b28b1e99f5d1cef15b6241f1ef51d40ed73b28195b`、`user_count=500`、`candidate_count=76136`；所有非 baseline 变体均为 `PARTIAL diagnostic-only`、`promotable=false`，主指标持平：`hit_rate_at_k=0.014493`、`ndcg_at_k=0.002779`、`mrr_at_k=0.006039`、`map_at_k=0.001208`、`candidate_hit_missed_topk_users=15`。

**面试可讲点：**
这轮可以讲成“先建排序实验门禁，再决定是否晋升”：我没有因为平台跑通就包装成收益，而是用 hash/count、freeze 指标和 promotion gate 证明这只是可复用诊断能力，当前排序效果不晋升。

### 2026-05-12 - Phase A 持久化合同落地与 frozen snapshot 诊断

**任务：**
把 recall persistence contract、schema、registry、artifact manifest 和 baseline snapshot 的叙事收口为 Phase A，不把它写成召回算法提升。

**问题：**
Phase A 产物能把 pool200 冻结快照跑通，但如果直接引用它来讲“召回变好”，会把 observation contract 和 algorithm improvement 混为一谈；同时目前 pool200 只有 observation/frozen baseline diagnostic snapshot，缺 frozen_candidates、ablation、latency 和 fallback promotion artifacts，不能晋升成可证明的提升证据。

**定位：**
对照 `.omc/recall/schema/recall_experiment_registry.schema.yaml`、`.omc/recall/schema/source_group_registry.schema.yaml`、`.omc/recall/registry/*.yaml`、`.omc/recall/artifacts/phase_1_25_pool200_frozen_baseline/{manifest,signature,contract,metrics}.yaml` 和 `scripts/validate_recall_registry.py`，核对 registry validation 输出 `Recall registry validation passed: 1 record(s)`，并检查 frozen baseline 只提供诊断快照，不提供晋升证据链。

**解决：**
把 Phase A 边界写成“持久化合同落地 + 冻结快照诊断”，明确只做 schema/registry/manifest/contract 对齐；pool200 统一标注为 `INCONCLUSIVE_MISSING_ARTIFACT`，不伪造 frozen_candidates、ablation、latency 或 fallback promotion 证据，也不引入 ranking/LTR/Top-K/线上指标叙事。随后把 `recall_registry_artifact.json` 接入 `run_hybrid_demo` 的实际产物路径，让每次 workflow 输出都带 recall-only registry artifact 摘要，而不是只停留在 `.omc` 静态合同。

**验证：**
registry 校验命令已通过；相关 schema/registry/artifact 文件已落盘，且文档中的结论只停留在 contract/diagnostic 层，没有宣称算法收益。新增生产路径验证：`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py::test_workflow_writes_outputs_report_and_metrics` 通过，确认 `metrics.json` 会记录 `recall_registry_artifact_path`，artifact hash 对应最终 metrics 文件，并且 gate status 仍为 `INCONCLUSIVE_MISSING_ARTIFACT`。

**面试可讲点：**
这轮能讲成“先把实验合同和证据链做实，再谈方法提升”：我把 pool200 作为诊断快照而不是晋升样本，先保证持久化与校验闭环，再决定后续是否补齐缺失 artifact。

### 2026-05-13 - Phase B recall promotion artifact 生产路径与 source family benchmark 框架

**任务：**
在 recall-only 边界内，把 pool200 observation 从静态合同推进到 workflow 可复现 artifact，并为后续所有主流召回方法建立 source family observation benchmark 框架。

**问题：**
之前 Phase A 已经能证明 schema/registry/manifest 一致，但缺 workflow sidecar 和 hash 证据；如果继续长期探索召回方法，却没有统一的 family 模板，后续 popular/category、ItemCF/co-visit、semantic/title-category、graph、vector/two-tower、sequence/multi-interest 会变成分散实验，难以比较和收敛最终路线。

**定位方式：**
核对 `run_hybrid_demo` 的 registry artifact 构造逻辑，确认 sidecar 是否 available 必须依赖文件已写出；核对 Phase 1.21 baseline 输出路径，确认它已经有固定 denominator、holdout hash、ranking disabled gate 和 no-leakage contract，适合承载 observation benchmark 注册模板。

**解决方式：**
新增 workflow 级 promotion sidecar 输出：source coverage、pool curve、latency、fallback、overlap/source contribution，并在 `metrics.json` 和 `recall_registry_artifact.json` 中记录路径与 sha256。新增 `source_family_observation_benchmarks.json`，把六类主流召回方法统一成 observation lane 的注册模板；当前只做框架和小样本 baseline 继承，不跑全量昂贵实验，也不把 missing ablation 包装成 promotion。

**验证结果：**
`./.venv/Scripts/python.exe scripts/validate_recall_registry.py` 输出 `Recall registry validation passed: 1 record(s)`；`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py tests/test_hybrid_demo.py::test_workflow_writes_outputs_report_and_metrics` 输出 20 passed。workflow 测试验证了 artifact path/hash、missing frozen_candidates/ablation 下仍 `INCONCLUSIVE_MISSING_ARTIFACT`、forbidden metrics 包含 ranking/online 指标；Phase 1.21 测试验证六类 source family 都是 recall-only observation。

**面试可讲点：**
可以讲成“用工程治理支撑算法路线探索”：不是一次性堆所有召回模型，而是先建可复现 artifact、registry gate 和 family benchmark，让 agent 持续探索组合时有统一证据标准；最终路线必须等完整 ablation/frozen/latency/fallback/overlap 证据齐全后再定。

**首批 observation baseline：**
已运行 `outputs/recall/phase_1_21_recall_coverage/source_family_baseline/`，固定 `limit_users=500`、`users_with_holdout=138`、`holdout_user_ids_hash=927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2`。当前 pool100 baseline 的召回侧结果为 `candidate_hit_users=14`、`candidate_hit_rate_at_pool=0.101449`、`recall_at_pool=0.060709`、`empty_candidate_rate=0.0`、`fallback_rate=0.0`；source marginal hits 为 semantic=9、popular=1、two_tower=1。结论仍是不产生 `baseline_vNext` 晋升：这只是 source family observation baseline，后续必须跑 family-specific variants 和 dedicated ablation 后才能改变晋升判断。

### 2026-05-13 - Phase C 召回长期执行合同与 evidence 状态机加固

**任务：**
按长期召回目标文档继续推进第一轮 Team+Ralph 执行，把 promotion gate、diagnostic-only 隔离、source family execution status、dedicated ablation/frozen promotion evidence 骨架做成机器可验证路径。

**遇到的问题：**
之前 `source_family_observation_benchmarks.json` 更像模板清单，如果没有 `execution_status` 和 `evidence_level`，后续 agent 容易把未运行的 family-specific variant 误当作 executed evidence；同时 promotion gate 如果不强制 `frozen_candidates_path`，会让缺冻结候选的 promotion record 漏过校验。

**定位方式：**
检查 `.omc/recall/schema/recall_experiment_registry.schema.yaml`、`scripts/validate_recall_registry.py`、`scripts/phase_1_21_recall_coverage_experiments.py` 和相关测试，确认 validator 已按 schema 的 `promotion_required_paths` 校验 promotion lane，并用 targeted pytest 验证 forbidden metrics、missing frozen candidates 和 missing ablation 的负向路径。

**解决方式：**
将 `frozen_candidates_path` 纳入 promotion required paths，validator 对 allowed/forbidden overlap、diagnostic-only metrics、decision_reason 引用 forbidden metrics 做负向校验；source family benchmark 增加 `execution_status`、`evidence_level`、`metrics_path`、`metrics_sha256`、`next_action` 等字段，只有当前真实 baseline 的 popular/category 标为 `EXECUTED_PASS`，ItemCF 和 semantic 标为 `READY_TO_RUN`，graph/vector/sequence 保持 template/missing-artifact 状态。ablation 模式新增 dedicated ablation evidence manifest 和 frozen promotion evidence checklist，但缺真实 frozen artifacts 时仍保持 `INCONCLUSIVE_MISSING_ARTIFACT`。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py::test_recall_registry_validator_accepts_source_alias_and_rejects_forbidden_metric_overlap` 通过；`./.venv/Scripts/python.exe -m compileall scripts/phase_1_21_recall_coverage_experiments.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py` 通过 19/19。当前 `baseline_vNext` 仍不得晋升，因为完整 frozen candidates、promotion artifact bundle 和可审计 ablation 证据仍未闭环。

**面试可讲点：**
这轮可以讲成“把长期召回探索从计划变成状态机”：不是声称新召回方法已经提升，而是把每个 source family 的真实执行状态、缺失 artifact 和下一步动作写进机器可校验产物，避免 agent 在长期实验中伪完成或误晋升。

### 2026-05-13 - Phase D semantic/title-category promotion candidate 收口

**任务：**
在长期召回执行中补齐真实 frozen candidates、family-specific observation 和 dedicated ablation evidence，并判断是否有 source 能进入 recall-only promotion candidate。

**问题：**
初始 ablation 结果中 baseline、semantic/title-category、co-visit、category long-tail 四行指标完全相同，说明实验配置被 source-family 开关污染；如果直接使用这组结果，会把组合配置误读成单 source 贡献。

**定位方式：**
对照 `outputs/recall/phase_1_21_recall_coverage/ablations/itemcf_covisit_semantic_pool200/summary_metrics.csv`、`dedicated_ablation_evidence_manifest.json` 与 `frozen_promotion_evidence_checklist.json`，核查同一 `holdout_user_ids_hash=927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2` 下各 source patch 的候选命中、候选量、fallback、overlap 和 latency artifact。

**解决方式：**
修正 ablation base config，只让每个实验 patch 启用当前待测 source，重新生成 summary、exclusive hits、overlap、latency、fallback 与 frozen promotion checklist；随后在 `.omc/recall/registry/recall_experiment_registry.yaml` 写入 `phase_1_21_semantic_title_category_promotion_candidate`，并在 `.omc/recall/artifacts/phase_1_21_semantic_title_category_promotion_candidate/` 落盘 manifest、metrics、signature。独立 verifier 通过后，再写入 `phase_1_21_semantic_title_category_baseline_vnext`，gate status 为 `PASS_PROMOTE_DEFAULT`，回滚基线为 `phase_1_25_pool200_frozen_baseline`。

**验证结果：**
修正后 baseline_only 为 `candidate_hit_users=17`、`candidate_hit_rate=0.123188`；`semantic_title_category` 为 `candidate_hit_users=19`、`candidate_hit_rate=0.137681`、`exclusive_hit_users=2`；`co_visit_fallback` 和 `category_long_tail` 均仍为 17 个 candidate-hit users。`frozen_promotion_evidence_checklist.json` 为 `READY_FOR_PROMOTION_REVIEW` 且无缺失 artifact；独立 verifier 结论为 APPROVE；`./.venv/Scripts/python.exe scripts/validate_recall_registry.py` 通过并识别 3 条 registry records。

**面试可讲点：**
这轮可以讲成“用消融修正单 source 归因，并通过 registry/verifier 完成默认基线晋升”：先发现配置污染导致 ablation 失真，再用干净 patch 重跑并把证据写进 registry。最终只晋升 semantic/title-category，没有把 co-visit、long-tail 或 Top-K/ranking 指标包装成召回收益。

### 2026-05-12 - Phase 1.26 持久排序实验治理底座

**任务：**
把长期排序路线探索拆成第一块可验证底座：实验注册表、冻结候选 artifact equality、严格 promotion status machine，让后续工业排序方法在同一证据框架下持续比较。

**问题：**
Phase 1.25 的 normalized-additive 变体全部 `PARTIAL diagnostic-only`，说明当前问题不是“再随手加一组权重”就能解决；如果没有 registry 和 artifact equality，后续 LTR、GBDT、LambdaMART 或深度模型实验很容易混入候选池漂移、`top_k` 漂移或微小指标噪声。

**定位：**
复用 `rs_core/recsys/evaluation.py` 里的冻结候选签名和严格状态机作为最小集成点，扩展测试集中已有的 `test_frozen_candidate_signature_compares_ordered_user_item_lists` 与 `test_strict_ranking_promotion_status_promote_partial_and_invalid_stop` 口径，不改召回、不改 `candidate_pool_size=200`、不改 `top_k=5`，线上 CTR/CVR/GMV/P95 仍保留到后续线上链路。

**解决：**
新增 `frozen_candidate_artifact()`、`compare_frozen_candidate_artifacts()`、`build_ranking_experiment_registry_entry()`，统一记录 schema version、canonical order、hash/count、promotion scope、关键离线指标和状态；同时把 promotion gate 实用化：`hit_rate_at_k` 需要绝对提升 `>=0.001`、相对提升 `>=3%`、`candidate_hit_missed_topk_users` 至少减少 1，并且 `ndcg_at_k`、`mrr_at_k`、`map_at_k` 不回退。

**验证：**
定向 Phase 1.26 registry/runner 测试通过 4/4，`compileall rs_core scripts tests` 通过；`tests/test_evaluation.py tests/test_hybrid_demo.py` 通过 86/86，并验证 Phase 1.25 runner 的 `comparison.json` 会实际写出 `ranking_experiment_registry`。该阶段只证明排序实验治理能力完成，不声明排序效果晋升。

**面试可讲点：**
可以把 Phase 1.26 讲成“工业排序探索的实验操作系统”：不是盲目实现所有主流模型，而是先把 frozen-pool equality、registry 和 promotion gate 固化，让后续每个方法都能被同一套证据规则公平比较，最终选择可解释、可复现、复杂度收益匹配的排序路线。

### Phase 1.23：full pool200 same-run ranking isolation

本轮在项目默认 `.venv` 下跑通完整对照命令，并带上 `--limit-users 500`，验证 pool200 冻结候选池上的排序隔离是否真的只归因于 ranking 层。产物落在 `outputs/ranking/phase_1_23_pool200_ranking_isolation/comparison.json` 和 `outputs/ranking/phase_1_23_pool200_ranking_isolation/comparison.md`。

诊断结果显示，所有变体均有效且没有 freeze drift，说明候选池边界稳定，可以直接比较排序层差异：baseline `users_with_holdout=138`、`candidate_hit_users=17`、`candidate_hit_rate_at_pool=0.123188`、`candidate_count_avg=152.272`、`fallback_rate=0.0`；same-run baseline `hit_rate_at_k=0.014493`、`ndcg_at_k=0.002779`、`mrr_at_k=0.006039`。`ranking_v2`、`item_feature_rerank`、`source_aware_fusion` 的指标与 baseline 完全一致，delta 全为 0。

最终判定是 `VALID but NO PROMOTION`：这轮 isolation gate 证明了归因边界干净，但也说明当前手写排序增量还不足以把稀疏正例推入 Top-K。下一步更值得先看 per-user hit rank 与 feature 分布，再决定是否进入 LTR 或更强的排序特征。

---

### Phase 1.15：YouTubeDNN pool100 冻结基线与隔离 ablation

### 为什么进入这一轮

Phase 1.14 以后，`semantic_title + YouTubeDNN pool100` 已经是当前召回主路里最稳定的一版。Phase 1.15 不再追新的主路模型，而是把这条路先冻结成基线，再补齐隔离的 gate / config / test 覆盖，确认后续任何 ablation 是否真的能在同跑 valid/test 上超过 frozen，而不是只在 LOPO 或局部指标上看起来更好。

### 遇到的问题

1. frozen 基线本身已经能跑通，容易把“能跑完”误写成“默认晋升”。
2. semantic IDF 版本在 `rs_core/recsys/candidate_merge.py` 里先出现过 hang，修复后虽然能跑完，但 valid/test 命中和 latency 都没有过门禁。
3. 如果把 ablation 结果混进 final，会把诊断实验误当成主路方案。

### 定位方式

把 `PHASE_1_15_FROZEN_YOUTUBEDNN_POOL100.md`、`PHASE_1_15_VALID_FINAL_CANDIDATE.md`、`PHASE_1_15_LOPO_SANITY.md` 和 `PHASE_1_15_ABLATION_SEMANTIC_IDF_BUDGET.md` 放在同一口径下对比，只看 `candidate_hit_rate_at_pool`、`hit_rate_at_k`、`candidate_generation_p95_seconds` 和 `ranking_p95_seconds`，并固定 `candidate_pool_size=100`、`top_k=5`、`YouTubeDNN pool100` 不变。

### 结果

- frozen baseline valid/test：`candidate_hit_rate_at_pool=0.106592`，`hit_rate_at_k=0.019635`，`candidate_generation_p95_seconds=0.461527s`。
- final valid/test candidate：`candidate_hit_rate_at_pool=0.106592`，`hit_rate_at_k=0.019635`，`candidate_generation_p95_seconds=0.485096s`。
- 结论：final 没有比 frozen 带来同跑增益，核心命中指标持平，延迟略差。
- LOPO sanity：`candidate_hit_rate_at_pool=0.959479`，`hit_rate_at_k=0.798119`，`candidate_generation_p95_seconds=0.39457s`。这只能证明同分布 sanity 通过，不能替代 valid/test gate。
- semantic IDF ablation：`candidate_hit_rate_at_pool=0.100982`，`hit_rate_at_k=0.00561`，`candidate_generation_p95_seconds=0.777899s`，`ranking_p95_seconds=0.000721s`。它既没有超过 frozen，也没有过 latency gate。

### 解决方式

把 `YouTubeDNN pool100` 固定为 Phase 1.15 的 recall baseline，只允许 isolated gate / config / test 继续做对照；semantic IDF hang 修复后，ablation 仍只保留为诊断证据，不进入 final。

### 面试可讲点

这轮更像是在做“基线冻结和门禁收口”，而不是做新模型冲分。我先把能站得住的 baseline 固定下来，再用隔离 ablation 证明哪些变体只是诊断、哪些变体真的能晋升，这样可以避免把 LOPO 或局部优化误写成主线收益。

### Phase 1.16：item_graph recall 生成与接入验证

### 为什么进入这一轮

Phase 1.15 已经把 `semantic_title + YouTubeDNN pool100` 冻结成 recall baseline，但它更多是在确认“基线站得住”，没有解决 valid/test 上候选覆盖和 Top-K 命中仍然偏保守的问题。Phase 1.16 选择 `item_graph`，是为了补一条与文本 recall 不同的结构化召回路径：先生成可诊断的 `item_graph_recall.jsonl`，再把它接入视图和离线 gate，验证它是否真的能给主路带来新的候选，而不是继续重复已有 source 的覆盖。

### 遇到的问题

1. 这一轮的重点不是再做一个“看起来更强”的配置，而是先判断 `item_graph` 是否只是和现有 recall 高重叠。
2. 如果只看 LOPO，很容易把同分布上的高分误写成晋升证据；但 valid/test 才是默认晋升口径。
3. item_graph 即使生成并接入成功，也必须检查它是否真的带来新的 valid/test 候选，而不是只改善诊断产物。

### 实现内容

- 生成 `item_graph_recall.jsonl`，并把它接入 views 重建流程。
- 保持 Phase 1.15 的 frozen baseline 口径不变，只在同跑对照里比较是否出现新增候选。
- 补充 item_graph diagnostics，用来观察 seed 命中、raw candidate/unseen 规模和 source coverage。

### 验证结果

```text
./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts
./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_simulation_runner.py tests/test_ltr.py -q
```

结果：

```text
compileall passed
pytest 61 passed
```

同跑 frozen baseline：

```text
candidate_hit_users = 76
candidate_hit_rate_at_pool = 0.106592
recall_at_pool = 0.042219
hit_rate_at_k = 0.019635
fallback_rate = 0.0
candidate_generation_p95_seconds = 0.461527
```

item_graph 接入后：

```text
candidate_hit_users = 76
candidate_hit_rate_at_pool = 0.106592
recall_at_pool = 0.042219
hit_rate_at_k = 0.019635
fallback_rate = 0.0
candidate_generation_p95_seconds = 0.411992
```

item_graph diagnostics：

```text
users_with_item_graph_seed_hits = 1514
raw_candidates = 55776
raw_unseen = 22286
candidate_hit_source_coverage.item_graph = 1
```

LOPO sanity：

```text
candidate_hit_rate_at_pool = 0.970333
hit_rate_at_k = 0.813314
item_graph candidate hits = 1341
```

### 结论

`item_graph` 已经生成并接入，但它没有让 valid/test 的候选覆盖或 Top-K 命中超过 frozen baseline；同跑指标持平，延迟还有改善，但没有形成新的晋升证据。LOPO sanity 很强，只能说明同分布下 item_graph 可用，不能替代真实切分 gate。

### 2026-05-13 - Phase B promotion evidence 补齐与 source family execution_status 收口

**任务：**
补写 Phase B 的中文优化叙事，收束 promotion schema/validator、diagnostic 隔离验证、source family execution_status 和后续执行队列。

**问题：**
当前 pipeline 已能产出 recall-only observation benchmark 骨架，但 baseline_vNext 还不能晋升，因为 frozen artifacts、dedicated ablation 和完整 promotion evidence 仍不完整；如果把这轮结果写成默认晋升，会把 observation scaffolding 误写成算法收益。

**定位方式：**
对照 `dic/OPTIMIZATION_NARRATIVE.md` 里 Phase B / Phase 1.26 / Phase 1.27 / Phase 1.31 的边界，以及 `tests/test_phase_1_21_recall_coverage.py`、`tests/test_hybrid_demo.py` 的 contract 断言，确认当前已经具备 promotion schema/validator、diagnostic-only execution_status、frozen-candidate equality 和 source family benchmark 模板，但还缺 family-specific ablation、frozen evidence bundle 与可晋升 gate 证据。

**解决方式：**
把这轮结论写成“继续推进可执行证据，不晋升 baseline_vNext”：保留 observation lane、模板化 execution_status 和 next_action 字段；同时明确下一执行队列应先跑 family-specific variants，再补 dedicated ablation/frozen evidence，最后才能重新判断 baseline_vNext。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py tests/test_hybrid_demo.py` 保持通过口径，且现有叙事只覆盖 recall-only observation 和 diagnostic-only 证据，没有把 baseline_vNext 写成 promoted。

**面试可讲点：**
这轮可以讲成“先把晋升证据做成机器可判定，再谈方法升级”：我没有把模板化骨架当成收益，而是先把 execution_status、validator 和 frozen evidence 的缺口显式化，避免把实验编排能力误写成模型提升。

### 解决方式

把 `item_graph` 定位成一条完成了实现和验证、但没有通过 promotion gate 的 recall 实验：保留生成和接入链路，结论写成 fail/no promotion，不把它包装成主路升级。

### 面试可讲点

这轮的重点不是“又加了一个 recall 源”，而是用 valid/test 和 LOPO 分开裁决它的价值。item_graph 证明了工程链路可以生成、接入、诊断，但也证明了它和现有 recall 在主口径上高度重叠，所以我没有把强 sanity 误写成默认晋升。

### Phase 1.17：rank_weights 冻结池调权结果

### 为什么进入这一轮

Phase 1.17 的目标不是继续扩召回，而是在固定召回候选池上验证排序权重是否还能带来稳定增益。为了避免把候选池波动误写成排序收益，这一轮使用 same-run baseline 作为对照，只看 `candidate_hit_users`、`candidate_hit_rate_at_pool`、`recall_at_pool`、`fallback_rate` 稳定时的 `hit_rate_at_k`、`ndcg_at_k`、`mrr_at_k` 和 rank 分位数变化。

### 遇到的问题

1. 这轮所有配置的候选池指标都与 baseline 完全一致，说明实验本身是池稳定的，但也意味着能否晋升只能看 Top-K 级别的排序变化。
2. 部分配置只带来 `hit_rate_at_k` 提升，部分只改善 `ndcg_at_k` / `mrr_at_k`，需要按决策规则区分 promotion、partial 和 no_gain，不能把“有一点变好”误写成晋升。
3. two_tower 相关调权没有带来增益，说明当前主路里真正可用的信号更偏向 semantic 和 popular，而不是简单放大双塔权重。

### 定位方式

以 `outputs/archive/root_files/phase_1_17_rank_weight_comparison.json` 和 `outputs/archive/root_files/phase_1_17_rank_weight_required_matrix.{json,csv}` 为主证据，逐项对比 baseline 与各权重变体，并核对 `dic/experiments/ranking/PHASE_1_17_RANK_WEIGHT_*.md` 报告中的 `ranked_hit_users`、`hit_rate_at_k`、`ndcg_at_k`、`mrr_at_k`、`candidate_hit_rank_p50/p90` 和 `promotion_status`。same-run baseline 为 `candidate_hit_users=69`、`candidate_hit_rate_at_pool=0.096774`、`recall_at_pool=0.040439`、`fallback_rate=0.0`、`candidate_count_avg=97.936752`、`hit_rate_at_k=0.019635`、`ndcg_at_k=0.005876`、`mrr_at_k=0.012202`、`rank p50=18`、`rank p90=55`。

### 结果

- **PROMOTION**：`popular_0_8`，`hit_rate_at_k=0.025245`，较 baseline 提升 `+0.005610`，同时 `ndcg_at_k` 提升 `+0.001587`、`mrr_at_k` 提升 `+0.001566`，是本轮最强候选。
- **PROMOTION**：`popular_0_9`，`hit_rate_at_k=0.021038`，提升 `+0.001403`，`ndcg_at_k` 提升 `+0.000250`、`mrr_at_k` 提升 `+0.000467`。
- **PROMOTION**：`semantic_1_3`，`hit_rate_at_k=0.021038`，提升 `+0.001403`，`ndcg_at_k` 提升 `+0.000137`，`mrr_at_k` 持平。
- **NO_GAIN**：`semantic_1_0`、`semantic_1_1`、`popular_1_1`、`two_tower_1_0`、`two_tower_1_1`、`two_tower_1_3`。
- **无 PARTIAL_DIAGNOSTIC**：说明这轮没有“Top-K 不变但其他排序指标改善”的灰区样本，决策可以直接按 promotion / no_gain 分流。

### 验证结果

比较矩阵显示所有非 baseline 配置都保持了相同的候选池命中与 fallback 统计，没有 INVALID。`popular_0_8`、`popular_0_9`、`semantic_1_3` 三组在稳定池上给出了明确 Top-K 收益，因此可以作为后续阶段的优先排序对照；其余配置未超过 same-run baseline，不应晋升。

### 面试可讲点

这轮最重要的不是“调出了一个更高的 hit@k”，而是建立了固定候选池下的权重决策纪律：先证明池稳定，再用同一门槛裁决 promotion / no_gain，避免把 recall 改动包装成排序收益。`popular_0_8` 的结果也能说明在这个阶段，适度下调 popular 权重比继续放大 semantic 或 two_tower 更有效。

### Phase 1.18：two_tower_seed item-neighbor 召回旁路验证

### 为什么进入这一轮

Phase 1.15 冻结了当前最强的 `semantic_title + YouTubeDNN pool100` 召回主路，Phase 1.16 的 `item_graph` 又证明纯结构共现旁路和现有 source 高度重叠。Phase 1.18 因此不再继续调局部权重，而是复用已有 YouTubeDNN item embedding，离线构建 item-to-item nearest-neighbor sidecar，并以默认关闭的新 source `two_tower_seed` 接入候选池，验证 learned embedding 几何关系是否能带来新的 valid/test 召回覆盖。

### 遇到的问题

1. builder 最初产出的 sidecar 是 `{item_id, neighbors}`，而 runtime loader 仍按旧的 `src_item/dst_item/score` pair schema 读取，存在合同不一致。
2. 新旁路必须独立于 `two_tower_enabled`，source label 也必须保留为 `two_tower_seed`，不能污染已有 `two_tower` 贡献统计。
3. sidecar builder 如果允许输出路径和 embedding 输入路径重合，会误删输入 artifact；manifest 和 sidecar 路径重合也会覆盖输出。
4. LOPO sanity 对该旁路很友好，但默认晋升必须只看 same-run valid/test gate。

### 实现内容

- 在 `rs_core/workflow/two_tower_training.py` 增加 deterministic two_tower_seed sidecar builder，输出 schema 为 `{item_id, neighbors:[{item_id, score, rank}]}`，manifest 标记 `phase=1.18`、`source=two_tower_seed`、`schema_version=two_tower_seed_neighbors_v1`。
- 在 `rs_core/recsys/candidate_merge.py` 增加新 schema loader、manifest 校验、seen filtering、recency decay、score floor、per-seed/per-user 限制和 `two_tower_seed` source attribution。
- 在 `rs_core/workflow/hybrid_demo.py` 中仅当 `two_tower_seed_enabled=true` 时加载 sidecar，并在 `fail_on_missing_sidecar=true` 时要求 manifest。
- 新增 `configs/recall/phase_1_18/phase_1_18_two_tower_seed_pool100.yaml` 与 `configs/recall/phase_1_18/phase_1_18_lopo_two_tower_seed_pool100.yaml`，保持 frozen 主路不变，排序增强全部 disabled。
- 新增 `scripts/run_phase_1_18_recall_gate.py`，生成 same-run baseline / experiment / LOPO 对照 JSON，避免用历史 baseline 包装实验结论。

### 验证结果

```text
./.venv/Scripts/python.exe -m pytest tests/test_two_tower_training.py tests/test_hybrid_demo.py tests/test_build_recall_views.py
75 passed

./.venv/Scripts/python.exe scripts/run_phase_1_18_recall_gate.py --skip-sidecar-build --output outputs/recall/phase_1_18_two_tower_seed_gate/comparison.json
exit 1 by gate, comparison JSON written
```

same-run frozen baseline：

```text
candidate_hit_users = 76
candidate_hit_rate_at_pool = 0.106592
recall_at_pool = 0.042219
hit_rate_at_k = 0.019635
fallback_rate = 0.0
candidate_generation_p95_seconds = 0.427404
```

two_tower_seed 接入后：

```text
candidate_hit_users = 75
candidate_hit_rate_at_pool = 0.105189
recall_at_pool = 0.041066
hit_rate_at_k = 0.019635
fallback_rate = 0.0
candidate_generation_p95_seconds = 0.452250
candidate_hit_source_coverage.two_tower_seed = 8
```

LOPO sanity：

```text
candidate_hit_users = 1323
candidate_hit_rate_at_pool = 0.957308
recall_at_pool = 0.957308
hit_rate_at_k = 0.796671
candidate_hit_source_coverage.two_tower_seed = 184
```

### 结论

`two_tower_seed` 工程链路成立：sidecar 能生成、manifest 能校验、runtime 能 opt-in 加载，且 valid/test 中确实有 `two_tower_seed` candidate-hit contribution。但 same-run valid/test 的候选覆盖低于 frozen baseline：`candidate_hit_users -1`、`candidate_hit_rate_at_pool -0.001403`、`recall_at_pool -0.001153`，因此 gate 结论是 `FAIL / no promotion`。LOPO 高分只能说明同分布 sanity 和旁路可用，不能替代默认晋升证据。

### 面试可讲点

这轮可以讲成“把双塔 item embedding 从 U2I 召回扩展成 I2I 旁路，并用严格 gate 否决了不泛化的增量”。亮点不是指标冲高，而是合同治理和实验纪律：先修 schema mismatch、manifest、路径安全和 source attribution，再用 same-run baseline 对照证明该旁路虽然有真实贡献，但整体候选池覆盖下降，所以保留为负向实验而不晋升主路。

### 决策复核结果

决策结论是 `NO_PROMOTION_KEEP_POPULAR_0_8`：在 second-order rank-weight 组合里，没有任何配置在 `hit_rate_at_k` 上超过 `popular=0.8`，因此这轮不再把组合权重继续向前推。failure attribution 显示问题主要不是排序细节，而是候选 miss 本身：`candidate miss = 644/713 (90.3226%)`，说明后续收益优先来自召回/source coverage，而不是继续做更细的 second-order rank-weight 组合。

### 面试可讲点

这轮可以讲成“把双塔 item embedding 从 U2I 召回扩展成 I2I 旁路，并用严格 gate 否决了不泛化的增量”。亮点不是指标冲高，而是合同治理和实验纪律：先修 schema mismatch、manifest、路径安全和 source attribution，再用 same-run baseline 对照证明该旁路虽然有真实贡献，但整体候选池覆盖下降，所以保留为负向实验而不晋升。最终决策复核也验证了同样的方向：`popular=0.8` 仍是当前最稳的排序基线，下一阶段应把重心转到 recall/source coverage。

### Phase 1.19：DeepWalk graph_walk_seed 结构召回旁路验证

### 为什么进入这一轮

Phase 1.18 的 `two_tower_seed` 证明 learned embedding I2I 旁路可以工程化接入，但 same-run valid/test 没有超过 frozen baseline。Phase 1.19 因此换成不依赖文本或双塔 embedding 的结构化图游走方向：从用户近期正反馈序列构建 item graph，用 DeepWalk-style random walk + skip-gram negative sampling 学到 item embedding，再离线导出 `graph_walk_seed` I2I sidecar，验证结构共现信号是否能带来新的候选覆盖。

### 遇到的问题

1. 新 source 必须默认关闭，并且不能和已有 `item_graph` 混用 source identity，否则 source contribution 会失真。
2. DeepWalk 训练产物需要可复现、可校验，不能只生成一个 sidecar 文件；manifest 必须记录 phase/source/schema/hash/device 等信息。
3. gate 需要区分“脚本崩溃”和“promotion checks failed”：本轮 smoke gate 返回 exit 1 是因为晋升门禁未通过，不是运行失败。
4. 新增 graph_walk 候选虽然大量存在，但必须看它是否带来 exclusive hit users / recall lift，而不能只看 raw candidates。

### 实现内容

- 新增 `rs_core/workflow/graph_walk_training.py`，基于正反馈相邻 item 建图，生成随机游走、skip-gram pairs，并用 PyTorch 训练 embedding；manifest 记录 `device=cuda` 或 `cpu`、输入/config/artifact hash 和 deterministic sort 约束。
- 新增 `scripts/train_graph_walk_seed.py` 与 `scripts/run_phase_1_19_graph_walk_seed_gate.py`，gate 同跑 baseline、default-off disabled、experiment、source-only、without_graph_walk，并输出 graph_walk diagnostics。
- 在 `rs_core/recsys/candidate_merge.py` 和 `rs_core/workflow/hybrid_demo.py` 接入 `graph_walk_seed`，要求 manifest + sidecar hash 校验，保持 source label 独立、seen filtering、recency decay、score floor、per-seed/per-user 限制。
- 新增 `configs/recall/phase_1_19/phase_1_19_graph_walk_seed_deepwalk.yaml`，保持排序增强关闭，gate 通过 overrides 启用实验 source。

### 验证结果

代码级验证：

```text
./.venv/Scripts/python.exe -m compileall rs_core scripts tests
通过

./.venv/Scripts/python.exe -m pytest tests/test_graph_walk_seed.py tests/test_hybrid_demo.py
69 passed
```

full gate：

```text
./.venv/Scripts/python.exe scripts/run_phase_1_19_graph_walk_seed_gate.py --output outputs/recall/phase_1_19_graph_walk_seed_gate/comparison.json
exit 1 by promotion gate, comparison JSON written
```

same-run full gate 指标：

```text
baseline candidate_hit_users = 69
baseline candidate_hit_rate_at_pool = 0.096774
baseline recall_at_pool = 0.040439
baseline hit_rate_at_k = 0.019635
baseline candidate_generation_p95_seconds = 0.49439

default-off disabled candidate_hit_users = 69
default-off disabled candidate_hit_rate_at_pool = 0.096774
default-off disabled recall_at_pool = 0.040439

experiment candidate_hit_users = 69
experiment candidate_hit_rate_at_pool = 0.096774
experiment recall_at_pool = 0.039079
experiment hit_rate_at_k = 0.019635
experiment candidate_generation_p95_seconds = 0.623431
experiment candidate_hit_source_coverage.graph_walk_seed = 2
experiment recall_source_coverage.graph_walk_seed = 22377
users_with_graph_walk_seed_hits = 1530
graph_walk_seed_raw_candidates = 1072400
graph_walk_seed_raw_unseen_candidates = 986695
candidate_share.graph_walk_seed = 0.076823
max_candidates_per_user_observed = 15

without_graph_walk candidate_hit_users = 72
without_graph_walk candidate_hit_rate_at_pool = 0.100982
without_graph_walk recall_at_pool = 0.040808
source_only candidate_hit_users = 1
source_only fallback_rate = 0.346154
lopo_sanity candidate_hit_users = 1368
lopo_sanity hit_rate_at_k = 0.800289
lopo_sanity candidate_generation_p95_seconds = 0.707052
```

gate 结果：

```text
gate.passed = false
candidate_hit_users_lift = false
candidate_hit_rate_at_pool_lift = false
recall_at_pool_lift = false
graph_walk_seed_hit_contribution = true
candidate_generation_p95_budget = false
lopo_candidate_generation_p95_budget = false
default_off_matches_baseline = true
source_identity_not_mixed_with_item_graph = true
source_cap_not_exceeded = true
fallback_rate_budget = true
exclusive_hit_users = []
displaced_baseline_hit_users = 4
```

manifest 证据显示 full training 使用 `device=cuda`，`item_count=9174`、`edge_count=9442`、`walk_count=91740`、`positive_pair_count=15595800`，说明训练链路和 artifact 生成成立。

### 结论

`graph_walk_seed` 的工程链路成立：DeepWalk-style 训练、embedding/sidecar/manifest 产物、runtime manifest hash 校验、source-only / without-source diagnostics 和 same-run gate 都已跑通。它在 smoke 中产生了大量 unseen raw candidates，并以独立 source 进入候选池，但没有带来新增 candidate-hit users、candidate hit rate 或 recall lift，因此 Phase 1.19 gate 结论是 `FAIL / no promotion`。下一步如果继续做结构召回，应优先分析 graph walk 候选和 holdout target 的重叠，而不是直接调排序权重或默认启用该 source。

### 面试可讲点

这轮可以讲成“把图游走从研究想法落成可审计召回旁路，并用严格门禁否决未泛化的结构信号”。亮点是训练 artifact 治理、source identity 隔离和 gate discipline：不仅证明模型能训练、候选能生成，还证明为什么它不能晋升主路。

## Phase 4.1：Agent 综合评估闭环与 feedback rerank tool

### 为什么调整 Phase 4 主线

原本 Phase 4 容易被理解成“直接导出 trajectory dataset，然后进入 SFT / GRPO”。但当前项目更需要先回答一个问题：Agent 的综合能力是否真的比 baseline 更强，以及强在哪里、弱在哪里、哪些交互可以沉淀成训练信号。

因此 Phase 4.1 先做评估闭环，而不是直接训练：

- baseline Agent 与 enhanced Agent 可以在同一批模拟角色上对比。
- enhanced Agent 的第一项能力是商品级 feedback rerank tool。
- 评估输出推荐效果、交互质量、反馈响应、记忆一致性、训练数据质量五维 scorecard。
- training signals 只作为 SFT / reward / preference / trajectory 的 deferred export，不宣称已经完成 SFT 或 GRPO。
- public session export 继续保持前端安全视图，internal artifact 单独保存诊断、scorecard、tool events 和训练证据。

### feedback rerank 的边界

这一步没有把 Agent 改成黑盒精排器。排序仍由传统 recommender / ranking pipeline 完成，Agent 只把用户的商品级反馈转成有限、可解释、可审计的排序调整：

- like 某商品：记录 liked item anchor，并对 ItemCF 相似候选做 soft boost。
- dislike / show_different 某商品：过滤被明确拒绝的商品，并对 ItemCF 相似候选做 soft demote。
- 每次调整都记录 `feedback_rerank_events`，进入 internal artifact 和 reward evidence。

这个设计的关键是：Agent 负责交互理解和工具调用，推荐 backbone 负责候选与最终排序，二者边界清晰。

### 验证结果

本阶段验证命令：

```text
./.venv/Scripts/python.exe -m pytest tests/test_agent_rollout_schema.py tests/test_agent_feedback.py tests/test_feedback_rerank.py tests/test_agent_scorecard.py tests/test_agent_eval_artifact.py tests/test_simulation_runner.py tests/test_serving_smoke.py
```

结果：

```text
42 passed in 0.98s
```

并运行：

```text
./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts
```

结果通过。

### 当前判断

Phase 4.1 的价值不是“模型已经训练好了”，而是把 Agent 能力评估、工具证据和训练信号导出统一成一条可复现闭环。后续如果进入 Qwen3.5-4B + QLoRA + GRPO，训练数据和 reward / preference 信号就不是凭空构造，而是来自可回放、可审计、可对比的 Agent 交互评估产物。


### 10k Phase 1.13：YouTubeDNN 进入召回主路，排序承接后置

本轮结论需要把“召回主路”和“最终 Top-K 推荐主路”分开判断。

在 `semantic_title + YouTubeDNN two_tower` 的 pool100 口径下，valid/test 候选池指标已经达到当前召回验收线：

```text
candidate_hit_rate_at_pool = 0.105189
recall_at_pool = 0.042043
candidate_hit_users = 75
fallback_rate = 0.0
```

这说明 YouTubeDNN 对“目标商品能否进入候选池”是有效的，可以作为召回主路的一部分保留。此前把它整体写成 `default-off side lane`，混淆了召回层与排序层：`hit_rate_at_k` 不达标主要是排序层没有把新增候选稳定推入 Top-K，不应该反向否定召回源本身。

排序承接实验仍然没有通过 Top-K 验收：

```text
pool100 rerank:
hit_rate_at_k = 0.015428
candidate_generation_p95_seconds = 0.407827
ranking_p95_seconds = 0.001020

pool100 conservative:
hit_rate_at_k = 0.016830
candidate_generation_p95_seconds = 0.418122
ranking_p95_seconds = 0.000917
```

因此阶段性判断更新为：

1. `semantic_title + YouTubeDNN` 可以进入召回主路，用于扩大候选池覆盖。
2. `source_aware_fusion` / `item_feature_rerank` / 旧 LTR 这类排序承接策略不能晋升为最终 Top-K 排序方案。
3. 下一阶段应把问题定义为排序阶段：在固定召回池上构造更真实的排序训练与验证，而不是继续否定 YouTubeDNN 召回。
4. candidate generation p95 约 `0.41s`，说明召回主路落地前还需要做向量检索性能优化，例如更高效的 top-k selection / ANN / artifact cache，而不是靠排序层解决。

面试叙事上，这一轮更适合表述为：先用 gate 证明 YouTubeDNN 能提升候选池覆盖，再用 Top-K 指标证明排序层承接不足。召回、排序、延迟三个问题分开决策，避免把排序失败误判成召回无效。

### 10k Phase 1.14：ranking v2 / LTR v2 固定召回池验证

本轮在 Phase 1.13 已确认的 `semantic_title + YouTubeDNN pool100` 候选池上，只验证 ranking v2 / LTR v2 是否能把已有命中候选推入 Top-K，不再用 LOPO 包装晋升结论。

valid/test 结果：

```text
candidate_hit_rate_at_pool = 0.105189
recall_at_pool = 0.042043
candidate_hit_users = 75
hit_rate_at_k = 0.001403
fallback_rate = 0.0
candidate_generation_p95_seconds = 0.472091
ranking_p95_seconds = 0.002814
```

结论是：候选池覆盖仍达到 Phase 1.14 召回验收线，但 `hit_rate_at_k=0.001403` 低于 baseline `0.019635`，也低于目标 `0.023843`，因此 ranking v2 / LTR v2 未通过 Top-K 排序晋升。`fallback_rate` 没有恶化，从 semantic_title baseline 的 `0.088889` 降到 `0.0`；但 candidate generation p95 从 `0.355698s` 增加到 `0.472091s`，排序 p95 也从 `0.000419s` 增加到 `0.002814s`，说明效果未达标且延迟成本更高。

LOPO sanity 结果：

```text
candidate_hit_rate_at_pool = 0.956585
recall_at_pool = 0.956585
candidate_hit_users = 1322
hit_rate_at_k = 0.811143
fallback_rate = 0.0
candidate_generation_p95_seconds = 0.375328
ranking_p95_seconds = 0.002832
```

LOPO 相对 semantic_title LOPO baseline 有提升，但它只说明同分布留一正样本 sanity 通过，不能替代 valid/test 晋升口径。下一步排序阶段不应继续包装 LOPO 成功，而应检查 LTR 训练样本、正负采样和 label 口径为什么把 valid/test 命中候选推得更低。

---

## Phase 1.20：recall diagnostics fallback limit500 与保护性回归核验

### 为什么进入这一轮

Phase 1.19 之后，需要把 recall 诊断从“能跑”收紧到“能稳定产出证据”。这一轮不追求全量晋升，而是验证 fallback / limited 口径、分母一致性和保护性 diff 检查是否稳定。

### 遇到的问题

1. full run 过慢，因此先用 `limit_users=500` 做 fallback 口径核验。
2. same-run 分母字段容易在不同产物间漂移，必须核对 `hit_rate_denominator`、`users_with_holdout`、`limit_users` 和 `evaluation_mode` 是否一致。
3. 需要确认 frozen 基线与 Phase 1.17 tracked diff 检查仍然保持 clean，避免诊断脚本污染主路结论。

### 定位方式

运行 `scripts/run_phase_1_20_recall_diagnostics.py --limit-users 500`，对照 `outputs/recall/phase_1_20_recall_diagnostics_large_limit500/` 下的 artifact、manifest 和保护性 diff 检查结果；再用 `compileall` 和专项测试确认脚本本身没有回归。

### 结果

```text
./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts
./.venv/Scripts/python.exe -m pytest tests/test_phase_1_20_recall_diagnostics.py tests/test_hybrid_demo.py tests/test_ltr.py
./.venv/Scripts/python.exe -m pytest tests/test_phase_1_20_recall_diagnostics.py tests/test_hybrid_demo.py tests/test_ltr.py tests/test_phase_1_20_recall_diagnostics.py tests/test_hybrid_demo.py tests/test_ltr.py
```

专项测试共 `79 passed`。`outputs/recall/phase_1_20_recall_diagnostics_large_limit500/` 生成了 limit500 diagnostic artifact，manifest `run_id=756ade477bdf7c45`，`evaluation_mode=valid_test`，`hit_rate_denominator=users_with_holdout`，`users_with_holdout=138`，`limit_users=500`。baseline hash 为 `afa923fb623402a51f17157565e204d1954fdd93814d102cf8c96e5c7a8ddff5`；CSV/JSON parity、required files、raw oracle stages 都已核验通过，保护性 frozen / Phase 1.17 tracked diff checks 也保持 clean。

### 结果判断

本轮的主瓶颈不在 pool truncation 或 top-k，而在 raw source coverage。证据是：`raw_stage_miss 121/138=87.6812%`，`raw/pre-pool coverage 17/138=12.3188%`，`pool truncation 3/138=2.1739%`，`pool_has_target_topk_miss 11/138=7.971%`，`topk_hit 3/138=2.1739%`。pool size 只在 50/100/200 时提升到 11/14/17，到了 500/1000 直接持平在 17，说明继续扩池收益已经很弱。

source 侧证据也指向同一结论：semantic 是最强的有效 source，拥有 9 个 exclusive hits；popular 只有 1 个，two_tower 只有 1 个，category/itemcf 为 0。高 volume source 之间虽然有 overlap/noise，但核心问题仍是目标商品在原始 source 里就缺失，尤其是非 popular 目标和 All Electronics、Office Products、Computers 这类 slice。

### 解决方式

把 Phase 1.20 明确定位成 fallback limit500 的诊断核验，而不是 full-run 晋升证据；下一步优先补 raw recall source 的覆盖与修复，再考虑有限的 pool 扩展。

### Phase 1.21 建议

优先做 raw recall-source 扩展/修复，重点盯 non-popular、long-tail 和弱 category；pool 扩展只作为覆盖改善后的有限 follow-up，规模可先放在约 200；ranking / top-k 继续作为次要项。

### 面试可讲点

这轮可以讲成“把诊断脚本也纳入工程门禁”：不只看脚本能不能跑完，还要同时验证分母口径、CSV/JSON 一致性、raw oracle stage 和冻结产物保护，确保诊断结论本身足够稳。

---

## Phase 1.21：recall coverage source 扩展与 pool-curve 诊断

### 为什么进入这一轮

Phase 1.20 已经把瓶颈定位到 raw source coverage，而不是简单的 Top-K 排序问题。Phase 1.21 因此只做召回覆盖侧实验：在冻结 baseline `configs/ranking/phase_1_15/phase_1_15_frozen_youtubednn_pool100.yaml` 之外，增加默认关闭的新 source 和统一 source/metrics contract，并用同一组 valid/test holdout 用户做诊断。

本轮固定口径：

```text
evaluation_mode = valid_test
limit_users = 500
users_with_holdout = 138
hit_rate_denominator = users_with_holdout
holdout_user_ids_hash = 927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2
```

### 实现与边界

新增和验证的召回侧能力包括：

- `semantic_title_category_expansion`：基于 title token 和 category overlap 的语义/类目扩展。
- `co_visit_fallback_repair`：基于训练序列共现的 fallback repair source。
- `category_long_tail_recall`：面向 long-tail slice 的类目候选补充。
- `metadata_neighbor_recall`：基于 metadata overlap 的邻居召回候选。

同时显式固化 source/metrics contract：新 source tag 必须稳定、lower_snake_case，候选合并必须保留 `sources`、`source_scores` 和 metadata；`miss_targets.csv` 与 holdout targets 只允许用于 diagnostics/evaluation，不能用于候选生成、source index construction、candidate whitelist 或参数选择。排序增强保持关闭：`ltr_model`、`ranking_v2`、`item_feature_rerank`、`source_aware_fusion` 均不参与本轮结论。

### 遇到的问题

1. 并行实现阶段出现过重复函数定义和 source config 覆盖，导致 semantic / co-visit 配置可能互相覆盖；最终收敛为单一 `_attach_phase_sources()` 和 `_phase_source_config()` 路径。
2. co-visit 噪声过滤一开始会把高频 seed 直接过滤掉，导致有效 `seed -> neighbor` 边消失；修正为允许高频 seed，但过滤高频 neighbor。
3. ablation matrix 在 `limit_users=500` 下仍超出执行窗口，尤其 metadata/source 扫描成本较高；因此不能把单 source 结果包装成晋升证据。

### 验证结果

专项回归通过：

```text
./.venv/Scripts/python.exe -m pytest tests/test_phase_1_20_recall_diagnostics.py tests/test_phase_1_21_recall_coverage.py
19 passed

./.venv/Scripts/python.exe -m pytest tests/test_phase_1_21_recall_coverage.py
18 passed
```

baseline artifact：`outputs/recall/phase_1_21_recall_coverage/baseline/manifest.json` 记录 `users_with_holdout=138`、`limit_users=500`、`raw_stage_miss=121`、`raw_pre_pool_hit_users=17`；baseline metrics 中 `candidate_hit_users=14`、`candidate_hit_rate_at_pool=0.101449`、`fallback_rate=0.0`。

pool-curve artifact：`outputs/recall/phase_1_21_recall_coverage/pool_curve/manifest.json` 校验了同一 `holdout_user_ids_hash`，并保持 ranking/rerank disabled。`pool100_vs_pool200_report.json` 的关键结果为：

| pool | candidate_hit_users | candidate_hit_rate_at_pool | recall_at_pool | hit_rate_at_k | fallback_rate | candidate_count_avg |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 14 | 0.101449 | 0.061312 | 0.021739 | 0.0 | 98.062 |
| 200 | 19 | 0.137681 | 0.069710 | 0.021739 | 0.0 | 157.112 |

pool100 到 pool200 带来 `candidate_hit_users_delta=+5`、`candidate_hit_rate_at_pool_delta=+0.036232`、`recall_at_pool_delta=+0.008398`，且 `fallback_rate=0.0`、同一 holdout hash 已验证。按本窗口只看召回指标的边界，pool200 晋升为 Phase 1.21 的 recall-side experimental baseline；pool500 / pool1000 没有继续增加 candidate-hit users，说明收益主要集中在有限扩池到 200 的诊断区间。

ablation artifact：`outputs/recall/phase_1_21_recall_coverage/ablations/manifest.json` 明确标记为 `status=inconclusive_timeout`，并记录：

```text
Ablation matrix did not complete within the execution window; do not promote any single source from ablation evidence.
```

### 结果判断

Phase 1.21 证明了两件事：

1. 召回覆盖诊断框架已经能稳定产出 source contract、metrics contract、same-holdout pool curve 和 no-leakage manifest。
2. 在组合 source + pool200 的诊断设置下，候选池命中用户从 14 增至 19，说明 raw recall 侧仍有可挖空间。

本轮晋升对象是 pool200 召回池设置，而不是单一 source：ablation 没有完成，因此不能把 `semantic_title_category_expansion`、`co_visit_fallback_repair`、`category_long_tail_recall` 或 `metadata_neighbor_recall` 单独晋升。排序 / Top-K 是否兑现由独立排序窗口承接，本窗口结论只基于 `candidate_hit_users`、`candidate_hit_rate_at_pool`、`recall_at_pool`、`fallback_rate` 和同 holdout hash 证据。

### 面试可讲点

这轮可以讲成“召回优化先看召回指标，再控制晋升边界”：同一 holdout hash、固定分母、no-leakage contract、ranking disabled gate 和 explicit inconclusive manifest 保证证据可信。pool200 在召回侧带来 +5 个候选命中用户，因此晋升为 recall-side experimental baseline；但单 source ablation 未完成，所以不晋升任何单一 source，也不把排序 / Top-K 结果混入本窗口结论。




### 2026-05-12 - Phase 1.22 pool200 source attribution 复核与 keep/prune 决策

**任务：**
基于 Phase 1.22 的 source attribution 和 keep/prune 决策，复核 pool200 recall 源。

**遇到的问题：**
本轮是 recall-only；ablation 只到 partial_time_limited，leave-one-source-out 全是 inconclusive_not_rerun；no-leakage 约束不变。

**定位方式：**
核对 contract.json、source_attribution_report.json、pool200_ablation_summary.csv、source_keep_prune_decisions.csv，确认 valid_test、limit_users=500、users_with_holdout=138、denominator=users_with_holdout、holdout hash=927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2；pool100_hit_users=14、pool200_hit_users=19、pool200_only_new_hit_users=5、lost_hit_users=0。

**解决方式：**
keep semantic_title_category_expansion / popular / semantic；reserve category_long_tail_recall、category、two_tower、co_visit_fallback_repair、itemcf_strong、itemcf_weak；prune metadata_neighbor_recall。新增 5 个命中里 popular=3、semantic_title_category_expansion=3，都是 non-exclusive attribution。

**验证结果：**
ablation 的非 baseline 行均为 time_limited_inconclusive_not_rerun，因此没有用任何 ablation delta 做结论。

**面试可讲点：**
固定合同下做 recall 源治理：先锁 holdout hash 和分母，再用归因决定 keep / reserve / prune，避免把诊断样本误读成边际证据。

---

### 2026-05-12 - Phase 1.22 pool200 å›ºå®šè¾“å…¥æŽ’åº�å¤�æ ¸

æœ¬è½®å�ªåœ¨å·²æ™‹å�‡çš„ pool200 å�¬å›žåŸºçº¿ä¹‹ä¸Šå¤�æ ¸æŽ’åº�ä¾§æ–¹æ³•ï¼Œä¸�æ”¹ recallã€�candidate generationã€�`candidate_pool_size`ã€�servingã€�simulation æˆ– frontendã€‚å¯¹ç…§æ–¹æ³•åŒ…æ‹¬ `ranking_v2`ã€�`source_aware_fusion` å’Œ `item_feature_rerank`ï¼Œä¸‰ä»½ isolated config å�‡é€šè¿‡éš”ç¦»éªŒè¯�ï¼šå�ªå¼€å�¯å�•ä¸€ ranking policyï¼Œ`candidate_pool_size=200`ï¼Œä¸”ä¸�å†�æ�ºå¸¦é¢�å¤– `rank_weights` å·®å¼‚ã€‚

å…³é”®é—®é¢˜å‡ºåœ¨è¯„ä¼°å�¯æ¯”æ€§ï¼špromoted baseline ç›®å½•æ²¡æœ‰ `recommendations.jsonl`ã€�`candidates.jsonl` æˆ– `ranking_hit_cases.jsonl`ï¼Œå�ªèƒ½å�š fixed-config deterministic rerunï¼›ä½†ä¸‰ç»„ rerun çš„å€™é€‰æ± å†»ç»“å­—æ®µä»Ž baseline çš„ `candidate_hit_users=19`ã€�`candidate_hit_rate_at_pool=0.137681`ã€�`candidate_count_avg=157.112` æ¼‚ç§»åˆ° `17`ã€�`0.123188`ã€�`152.272`ï¼Œå› æ­¤ä¸�èƒ½æŠŠ Top-K å�˜åŒ–å½’å› åˆ°æŽ’åº�ç­–ç•¥ã€‚

å®žéªŒç»“æžœä¹Ÿä¸�æ”¯æŒ�æ™‹å�‡ï¼šä¸‰ç»„å�˜ä½“çš„ `hit_rate_at_k=0.014493`ï¼Œä½ŽäºŽ promoted baseline çš„ `0.021739`ï¼›`ndcg_at_k=0.002779` ä½ŽäºŽ baseline `0.004983`ï¼›è™½ç„¶ `mrr_at_k=0.006039` ç•¥é«˜äºŽ baseline `0.005314`ï¼Œä½†åœ¨å€™é€‰æ± æ¼‚ç§»ä¸” hit/NDCG ä¸‹é™�çš„æƒ…å†µä¸‹å�ªèƒ½ä½œä¸ºæ— æ•ˆè¯Šæ–­ä¿¡å�·ã€‚case attribution è¿›ä¸€æ­¥æ˜¾ç¤ºï¼Œæ¼‚ç§»æ± å†…ä¸‰ç»„æ–¹æ³•å�ªæœ‰ç›¸å�Œçš„ 2 ä¸ª Top-K hitsï¼Œæ²¡æœ‰ entered Top-K targetï¼Œä¹Ÿæ²¡æœ‰å�¯æ™‹å�‡çš„æŽ’åº�æ”¶ç›Šã€‚

é˜¶æ®µç»“è®ºï¼š`NO PROMOTION / INVALID`ã€‚ä¿�ç•™ promoted pool200 baselineï¼Œä¸�æ™‹å�‡ `ranking_v2`ã€�`source_aware_fusion` æˆ– `item_feature_rerank`ã€‚ä¸‹ä¸€è½®æŽ’åº�æˆ– LTR ä¹‹å‰�ï¼Œå¿…é¡»å…ˆè¡¥ä¸€ä¸ªæ˜¾å¼�çš„ per-user frozen candidate exportï¼Œæˆ–åœ¨å�Œä¸€æ¬¡è¿�è¡Œä¸­å�Œæ—¶ç”Ÿæˆ� no-rerank baseline ä¸Ž ranking variantsï¼›å�¦åˆ™æŽ’åº�å±‚æ”¶ç›Šæ— æ³•ä¸Žå€™é€‰æ± æ¼‚ç§»è§£è€¦ã€‚



### 2026-05-12 - Phase 1.23 pool200 ranking isolation ä¿®å¤�ä¸Ž frozen candidate å¯¼å‡º

**ä»»åŠ¡ï¼š**
ä¿®å¤� Phase 1.22 æš´éœ²çš„æŽ’åº�éš”ç¦»ç¼ºå�£ï¼Œè¡¥é½� frozen candidate å¯¼å‡ºå’Œ same-run no-rerank baselineï¼Œç¡®ä¿�æŽ’åº�æ¯”è¾ƒå»ºç«‹åœ¨å�Œä¸€å€™é€‰æ± ä¸Šã€‚

**é�‡åˆ°çš„é—®é¢˜ï¼š**
Phase 1.22 å¤�æ ¸é‡Œï¼Œpromoted baseline ç¼ºå°‘ per-user `recommendations.jsonl` / `candidates.jsonl` / `ranking_hit_cases.jsonl`ï¼Œå�Žç»­ deterministic rerun è¿˜å‡ºçŽ°å€™é€‰æ± å†»ç»“å­—æ®µæ¼‚ç§»ï¼Œå¯¼è‡´ `candidate_hit_users` ä»Ž 19 å�˜æˆ� 17ï¼Œ`candidate_hit_rate_at_pool` å’Œ `candidate_count_avg` ä¹Ÿå�Œæ­¥å�˜åŒ–ï¼›è¿™è¯´æ˜ŽæŽ’åº�ç»“æžœå’Œå€™é€‰æ± çŠ¶æ€�æ²¡æœ‰çœŸæ­£è§£è€¦ã€‚

**å®šä½�æ–¹å¼�ï¼š**
å¯¹ç…§ Phase 1.22 çš„ comparison / metrics / hit cases è¾“å‡ºï¼Œç¡®è®¤é—®é¢˜ä¸�æ˜¯æŸ�ä¸ªæŽ’åº�ç­–ç•¥æœ¬èº«ï¼Œè€Œæ˜¯è¯„ä¼°å…¥å�£æ²¡æœ‰å›ºå®šå€™é€‰æ± ï¼›å†�æ ¸å¯¹ Phase 1.23 çš„ isolated configsã€�`scripts/run_phase_1_23_pool200_ranking_isolation.py` å’Œæ–°å¢žæµ‹è¯•ï¼Œç¡®è®¤ä¿®å¤�ç‚¹é›†ä¸­åœ¨å¯¼å‡º frozen candidates ä¸Žå�Œè·‘ baseline gateã€‚

**è§£å†³æ–¹å¼�ï¼š**
æ–°å¢ž `export_frozen_candidates/frozen_candidates.jsonl`ï¼Œè¡¥é½� Phase 1.23 é…�ç½®ç»„ï¼Œè®©å�Œä¸€æ¬¡è¿�è¡Œå�Œæ—¶äº§å‡º no-rerank baseline ä¸Ž ranking variantsï¼Œå¹¶æŠŠæ¯”è¾ƒé€»è¾‘æ”¶æ•›åˆ° frozen candidate æ± ï¼›è¿™æ ·æŽ’åº�æ–¹æ³•å�ªå½±å“�é‡�æŽ’ï¼Œä¸�å†�è¢«å€™é€‰æ± æ¼‚ç§»æ±¡æŸ“ã€‚

**éªŒè¯�ç»“æžœï¼š**
`.venv` ä¸‹ `python -m compileall -q rs_core tests scripts` é€šè¿‡ï¼›`pytest tests/test_hybrid_demo.py -k "phase_1_23 or frozen_candidate"` ç»“æžœä¸º `3 passed`ï¼›`scripts/run_phase_1_23_pool200_ranking_isolation.py --limit 20` äº§å‡ºäº† comparison.json / comparison.md å’Œå››ä»½ frozen candidate å¯¼å‡ºï¼Œæ‰€æœ‰å�˜ä½“å�‡ä¸º `VALID`ï¼Œä¸”æ²¡æœ‰å€™é€‰æ± æ¼‚ç§»ã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™è½®å�¯ä»¥è®²æˆ�â€œå…ˆä¿®è¯„ä¼°æ¡†æž¶ï¼Œå†�è°ˆæŽ’åº�æ”¶ç›Šâ€�ã€‚æˆ‘å…ˆå�‘çŽ°æŽ’åº�æ¯”è¾ƒè¢«å€™é€‰æ± æ¼‚ç§»æ±¡æŸ“ï¼Œç„¶å�ŽæŠŠ frozen candidate export å’Œ same-run no-rerank baseline gate è¡¥ä¸Šï¼Œæœ€å�Žç”¨ compileallã€�å®šå�‘ pytest å’Œ limit-20 smoke æŠŠç»“è®ºé”�æ­»åœ¨å�Œä¸€å€™é€‰æ± ä¸Šã€‚


### 2026-05-12 - Phase 1.23 sample-size LOPO å�™äº‹è¡¥å……

**ä»»åŠ¡ï¼š**
è¡¥å†™ Phase 1.23 çš„ sample-size sensitivity ä¸­æ–‡å�™äº‹ï¼Œæ˜Žç¡®å®ƒå�ªæ˜¯åœ¨ LOPO å†…éƒ¨å�š recall-only sanityï¼Œä¸�æŠŠç»“æžœè¯¯å†™æˆ� valid_test æ™‹å�‡è¯�æ�®ã€‚

**é—®é¢˜ï¼š**
100 / 1000 / 10000 ä¸‰æ¡£æ ·æœ¬ä¸‹çš„ LOPO pool200 å�¬å›žéƒ½å¾ˆé«˜ï¼Œå®¹æ˜“è¢«è¯¯è¯»æˆ�â€œä½Ž recall å�ªæ˜¯æ ·æœ¬å¤ªå°‘â€�ï¼›ä½†è¿™äº›ç»“æžœå’Œ Phase 1.21/1.22 çš„ valid_test holdout-hash baseline ä¸�å�Œå�£å¾„ï¼Œä¸�èƒ½ç›´æŽ¥å¯¹æ¯”ã€‚

**å®šä½�ï¼š**
å¯¹ç…§ `outputs/ranking/phase_1_23_sample_sensitivity/contract.json`ã€�`metrics_by_sample.json`ã€�`sample_size_sensitivity_summary.csv` å’Œ `report.json`ï¼Œæ ¸å¯¹ä¸‰æ¡£ç»“æžœåˆ†åˆ«ä¸º 12/12=1.0ã€�78/81=0.962963ã€�1314/1382=0.950796ï¼Œ`candidate_count_avg` ä¾�æ¬¡ä¸º 52.166667ã€�93.901235ã€�128.83864ï¼›å�Œæ—¶æ£€æŸ¥å‘½ä¸­æ�¥æº�ï¼Œå�‘çŽ°æ›´å¤§æ ·æœ¬ä¸‹ä¸»è¦�ç”± `itemcf_strong` / `itemcf_weak` è´¡çŒ®ï¼Œè€Œä¸�æ˜¯ Phase 1.21 é‡Œè§£é‡Š pool200-only å¢žç›Šçš„ `semantic_title_category_expansion` / `popular`ã€‚

**è§£å†³ï¼š**
æŠŠå�™äº‹è¾¹ç•Œé”�åœ¨ recall-onlyã€�pool200ã€�LOPO internal splitï¼Œå¹¶æ˜Žç¡®ä¸�å�š rankingã€�Top-Kã€�LTR rerankã€�holdout tuning æˆ– leakage è§„é�¿å¼�åŒ…è£…ï¼›ç»“è®ºå†™æˆ�â€œæ•°æ�®/åˆ‡åˆ†éš¾åº¦ä»�æ˜¯ä¸»å› ï¼ŒLOPO è¯�æ�®ä¸�è¶³ä»¥æŠŠ valid_test ä½Ž recall å½’å› ä¸ºæ ·æœ¬è§„æ¨¡â€�ã€‚

**éªŒè¯�ï¼š**
ä¸‰æ¡£ LOPO æŒ‡æ ‡å…¨éƒ¨è·‘é€šä¸” fallback_rate=0.0ï¼›æ ·æœ¬å¢žå¤§å�Žå€™é€‰ä¾›ç»™ç¡®å®žä¸Šå�‡ï¼Œä½† source å½’å› ä¸Ž valid_test åŸºçº¿ä¸�ä¸€è‡´ï¼Œè¯´æ˜Ž sample-size å�˜å¤§å¹¶ä¸�è‡ªåŠ¨ç­‰ä»·äºŽ valid_test recall æ™‹å�‡ã€‚

**é�¢è¯•å�¯è®²ç‚¹ï¼š**
è¿™è½®çš„ä»·å€¼ä¸�åœ¨â€œæŠŠ recall å�šé«˜â€�ï¼Œè€Œåœ¨â€œæŠŠè¯�æ�®è¾¹ç•Œè¯´æ¸…æ¥šâ€�ï¼šæˆ‘ç”¨å�Œä¸€ recall-only å�ˆå�ŒéªŒè¯�äº†æ ·æœ¬è§„æ¨¡ä¼šå½±å“�å€™é€‰ä¾›ç»™ï¼Œä½†ä¹Ÿè¯�æ˜Žäº† LOPO ä¸�èƒ½ç›´æŽ¥æ›¿ä»£ valid_test å�£å¾„ï¼Œå› æ­¤å�Žç»­åº”ä¼˜å…ˆå�šå�Œé£Žæ ¼ valid_test å¤§ split æˆ–æ›´ä¸¥æ ¼çš„ leakage auditã€‚


### 2026-05-12 - Phase 1.24 核心召回指标扩展

**任务：**
把工业召回的主流方法补成可观测指标框架，在冻结候选池上扩展召回侧诊断口径，作为 Phase 1.21~1.23 之后的召回观测底座。

**问题：**
如果只看单一 recall 数字，规则/热门、协同过滤、内容/语义、图召回、双塔/向量召回会被混成一个黑盒，也容易把“召回覆盖变化”误判成“排序变好”。本阶段要先把方法谱系和现有 source 对上，再区分哪些是观测指标，哪些才是算法升级。

**定位方式：**
按工业召回谱系映射现有 source：规则/热门对应 `popular`、`category`；协同过滤对应 `itemcf_strong`、`itemcf_weak`；内容/语义对应 `semantic`、`semantic_title_category_expansion`、`category_long_tail`；图召回对应 `item_graph`、`graph_walk`；双塔/向量召回对应 `two_tower`；序列/多兴趣召回先保留为后续扩展位。

**解决方式：**
把 Phase 1.24 定义为指标扩展，不改召回算法本身；只补用户覆盖、候选池规模分布、K 档候选命中/召回、catalog 覆盖、source 用户/item 覆盖、source pair Jaccard 和 source marginal candidate hit。明确不做排序、不做 Top-K promotion、不伪造线上 CTR/CVR/GMV，也不靠 holdout / miss-target 调参包装晋升。

**验证结果：**
新增指标测试已覆盖 `metrics.json` contract 和小样本端到端输出：`empty_candidate_rate`、`candidate_count_p50/p90`、`candidate_hit_rate_at_cutoffs`、`candidate_recall_at_cutoffs`、`catalog_candidate_coverage_count/rate`、`source_user_coverage`、`source_item_coverage`、`source_marginal_candidate_hit_*`、`source_overlap.source_pair_jaccard`。边界与 Phase 1.21~1.23 保持一致：只做召回侧观测，不把观测指标写成算法收益。

**面试可讲点：**
这轮可以讲成“先把召回黑盒拆成工业方法谱系，再把现有 source 放回对应位置”。价值不在立刻提分，而在让后续无论接规则、协同过滤、语义、图还是双塔，都能用统一指标判断覆盖、来源、重叠和晋升边界。


### 2026-05-13 - Phase 1.27 feature / label / leakage governance

**任务：**
把 Phase 1.27 收口到特征契约、标签切分和泄漏门禁，不把它写成召回或排序提分。

**问题：**
如果 feature contract、label split 和 leakage gate 没有被明确治理，后续 learned ranker 很容易把 holdout target、future interaction，或者 valid/test 上的 promotion evidence 误用进训练或评估，最后把治理缺口误写成模型收益。

**定位方式：**
对照 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 中 Phase 1.27 的范围，确认这里补的是 offline ranking feature contract、allowed/forbidden features、label/split/leakage gate 和 registry metadata，而不是改 `candidate_pool_size`、`top_k` 或 recall baseline。验证前先修复 `rs_core/workflow/hybrid_demo.py` 的 helper 调用不一致，再跑 Phase 1.27 相关 pytest、compileall 和真实 runner smoke。

**解决方式：**
按治理口径记录 Phase 1.27：allowed features 只保留 source、item metadata、candidate score、user history aggregates 和 near-miss diagnostics；forbidden features 明确排除 holdout target、future interaction，以及在 valid/test 上训练后再当 promotion evidence 的字段；label split leakage gate 专门覆盖 target item、future interaction 和 holdout leak；registry metadata 记录 feature contract version 与作用范围，供后续 learned ranker 复用。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_evaluation.py tests/test_ltr.py` 通过 106/106；`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过；`./.venv/Scripts/python.exe scripts/run_phase_1_25_pool200_normalized_additive.py --limit-users 50` 成功生成 `outputs/ranking/phase_1_25_pool200_normalized_additive/comparison.json`，registry 中已记录 `feature_contract_version=ranking_feature_contract_v1`、`feature_contract_gate_summary.schema_version=ranking_feature_contract_gate_v1` 和 `leakage_gate_summary.schema_version=ranking_feature_leakage_gate_v1`。非 LTR 排序变体的 feature/leakage gate 明确标记为 `NOT_APPLICABLE`，LTR 训练路径会对真实 feature rows 执行 gate；验证期间没有改 `candidate_pool_size`、`top_k` 或 recall baseline，也没有把 Phase 1.27 写成模型 lift。

**面试可讲点：**
先把 learned ranker 的输入契约和泄漏边界定清楚，再谈模型本身。这里不是追求数字上升，而是先把特征、标签和切分门禁做成可审计的治理层，保证后续排序学习的证据不会被 holdout leak 污染。

### 2026-05-13 - Phase 1.28 lightweight learned ranker 最小闭环

**任务：**
在 frozen pool200 排序口径下接入第一批 learned ranker baseline，只做 lightweight pointwise logistic 和 pairwise perceptron，不进入 GBDT、LambdaMART 或深度模型。

**遇到的问题：**
长期计划已经有很多候选排序方法，但如果第一步就上复杂模型，会让模型能力、候选池漂移、特征泄漏和训练标签来源混在一起，难以解释结果。Phase 1.27 已经建立 feature/leakage gate，因此 Phase 1.28 的关键不是追求 lift，而是证明 learned ranker 可以在生产排序路径中被约束地训练、加载、评估和注册。

**定位方式：**
检查 `rs_core/recsys/ranking.py`，确认 `ltr_model.enabled` 已经在 `rank_candidates()` 中走真实排序推理路径；检查 `rs_core/recsys/ltr.py` 和 `rs_core/workflow/ltr_training.py`，确认 pointwise logistic 与 pairwise perceptron 都输出兼容 `score_ltr()` 的线性权重，并会用真实候选 feature rows 执行 `validate_ltr_feature_contract_gate()` 与 `validate_ltr_leakage_gate()`。同时确认 baseline 配置仍来自 `configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml`，保持 `candidate_pool_size=200`、`top_k=5` 和召回参数不变。

**解决方式：**
新增并扩展 `scripts/run_phase_1_28_lightweight_learned_ranker.py`，形成 baseline → LOPO/internal LTR training → LTR variant evaluation → registry/comparison/report 的最小闭环。runner 写出 `same_run_baseline`、`pointwise_logistic_lopo_ltr` 和 `pairwise_perceptron_lopo_ltr`；两个 LTR 变体都复用 Phase 1.27 gate summary，并把 `strict_ranking_promotion_status(..., ltr_enabled=True)` 的结果写入 registry，明确标记为 `PARTIAL diagnostic-only`，不允许作为 frozen-pool promotion evidence。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k phase_1_28 -vv` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_ltr.py tests/test_hybrid_demo.py` 通过 107/107；`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过；`./.venv/Scripts/python.exe scripts/run_phase_1_28_lightweight_learned_ranker.py --limit-users 50` 生成 `outputs/ranking/phase_1_28_lightweight_learned_ranker/comparison.json` 和 `comparison.md`。artifact 摘要显示 `all_variants_valid=true`，baseline、`pointwise_logistic_lopo_ltr` 与 `pairwise_perceptron_lopo_ltr` 的 frozen candidate comparison 均匹配，`candidate_pool_size=200`、`top_k=5`、`fallback_rate=0.0`；两个 LTR 训练均为 `feature_contract_gate=PASS`、`leakage_gate=PASS`、`label_source=leave_one_positive_out_train`、`training_split=train`、`rows=4366`、`positive_rows=32`，并分别记录 `model_type=pointwise_logistic_ltr_v1` 与 `pairwise_perceptron_ltr_v1`。小样本 smoke 中 Top-K 指标未提升，两个 LTR 变体状态均保持 `PARTIAL diagnostic-only`、`promotable=false`。

**面试可讲点：**
这轮可以讲成“把 learned ranker 从概念接成可审计生产路径”：先用最轻量线性模型验证训练/推理/registry/gate/frozen equality 是否闭环，再决定是否升级到 LR、GBDT、LambdaMART 或深度排序。这样能避免把复杂模型失败误判为路线失败，也能避免把 LOPO sanity 包装成 valid/test 晋升。

### 2026-05-13 - Phase 7/8 多目标与在线学习 future-online 门禁

**任务：**
继续长期排序计划 Phase 7/8，确认 ESMM、MMoE、PLE、多目标排序、Bandit、RL/GRPO 和 Agent feedback 在当前 frozen pool200 离线阶段的边界，并防止线上指标被误写成当前 promotion 证据。

**遇到的问题：**
Phase 7/8 的方法依赖 CTR/CVR/GMV 等业务 label、线上或准线上评估链路、serving/monitoring contract、交互日志、安全探索策略和 replay/A/B 能力；当前项目只有 frozen pool200 离线 ranking 证据，不能把 P95/SLO、A/B uplift 或未来业务目标伪装成当前离线收益。

**定位方式：**
对照 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 中 Phase 7/8 的进入条件，确认当前状态分别是 `future-online` 和 `future-agent-online`；同时复用 Phase 0 后续形成的 registry/artifact inspection 结构，确保 baseline artifact 仍保持 `candidate_pool_size=200`、`top_k=5` 与 frozen candidate 可审计。

**解决方式：**
新增 `scripts/run_phase_7_8_future_online_gate.py`，只运行 same-run baseline 以保留当前离线产物完整性；将 `esmm_ctr_cvr_ranker`、`mmoe_multi_task_ranker`、`ple_multi_task_ranker`、`contextual_bandit_ranker`、`rl_grpo_preference_ranker` 等方法写入 blocked registry，lane 分别标注为 `future-online` / `future-agent-online`，并在 `future_online_readiness` 中明确缺失业务 label、线上评估、serving/monitoring、交互日志、安全探索和 replay/A/B。

**验证结果：**
`./.venv/Scripts/python.exe -m compileall scripts/run_phase_6_semantic_two_tower_ranker.py scripts/run_phase_7_8_future_online_gate.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_7_8_future_online_gate or phase_6_semantic_two_tower_ranker or phase_5_sequence_ranker"` 通过 3 个目标测试；真实 smoke `./.venv/Scripts/python.exe scripts/run_phase_7_8_future_online_gate.py --output-dir outputs/ranking/phase_7_8_future_online_gate_smoke --limit-users 200` 通过，`comparison.json` 中 artifact inspection 为 PASS，最终路线保持 `same_run_baseline`，线上指标被列为当前禁用证据。

**面试可讲点：**
这轮可以讲成“知道什么时候不该做实验”：多目标和在线学习是工业推荐系统的重要方向，但没有业务 label、线上链路和安全探索时，最专业的做法是建立 future gate 和证据边界，而不是拿离线 Top-K 指标冒充 CTR/CVR/GMV 收益。

### 2026-05-13 - Phase 6 语义 / 双塔排序特征融合门禁

**任务：**
继续长期排序计划 Phase 6，在不改变 frozen pool200 候选池的前提下，验证 semantic-title score、two-tower score、vector similarity 和 DSSM 相关特征是否能作为排序侧增益证据。

**遇到的问题：**
当前基线已经启用 semantic 和 two_tower 召回源，但 Phase 6 不能重新生成候选池，也不能把 two-tower / DSSM artifact 当成新召回收益；必须只使用候选内已有 `source_scores` 或可审计交叉特征。DSSM 和 raw vector similarity 虽有 artifact，但缺 candidate-level rerank adapter，不能伪装成可晋升排序模型。

**定位方式：**
检查 `configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml` 确认 `candidate_pool_size=200`、`top_k=5`、semantic/two_tower 源已存在且排序开关关闭；检查 `rs_core/recsys/ranking.py`、`rs_core/recsys/ltr.py` 和 two-tower artifact，确认候选内可用的是 semantic/two_tower source score 与 source cross features，而不是新的候选生成路径。

**解决方式：**
新增 `scripts/run_phase_6_semantic_two_tower_ranker.py`，在 same-run frozen pool200 baseline 上运行三个排序侧对照：`semantic_score_feature_rerank`、`two_tower_score_feature_rerank`、`semantic_two_tower_cross_feature_fusion`；同时把 `dssm_artifact_candidate_rerank` 与 `raw_vector_similarity_feature_fusion` 写入 blocked registry，原因是缺 candidate-level adapter 且不得重建候选池。

**验证结果：**
`./.venv/Scripts/python.exe -m compileall scripts/run_phase_6_semantic_two_tower_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_6_semantic_two_tower_ranker or phase_5_sequence_ranker"` 通过 2 个目标测试；真实 smoke `./.venv/Scripts/python.exe scripts/run_phase_6_semantic_two_tower_ranker.py --output-dir outputs/ranking/phase_6_semantic_two_tower_ranker_smoke --limit-users 200` 通过，`comparison.json` 中 artifact inspection 为 PASS、frozen candidate status 全部 PASS。指标上 baseline `hit_rate_at_k=0.037037`、`ndcg_at_k=0.007103`、`mrr_at_k=0.015432`；semantic score rerank 下降到 `hit_rate_at_k=0.018519`；two-tower score 与 cross-feature fusion 持平但没有减少 missed-topk users，因此全部为 diagnostic-only，最终路线保持 `same_run_baseline`。

**面试可讲点：**
这轮体现的是“向量/双塔不是万能增强”的实验纪律：已有 embedding artifact 不等于可以改变候选池，也不等于有排序收益。先把候选内可审计分数做 frozen-pool 对照，再把缺 adapter 的 DSSM/vector 路线明确 blocked，能展示对召回、排序和特征证据边界的把控。

### 2026-05-13 - Phase 5 行为序列 / 注意力排序数据门禁

**任务：**
在长期排序计划 Phase 5 中验证 DIN、DIEN、BST、SIM、session-aware reranker 和 attention over user history 的进入条件，继续保持 frozen pool200、`candidate_pool_size=200`、`top_k=5` 与不改召回语义的硬边界。

**遇到的问题：**
行为序列模型不能只因为有 `user_sequences` 就硬做。DIN/DIEN/BST/SIM 需要足够长且时间可靠的历史、明确 session/history window、无未来交互泄漏和对应 serving adapter；当前数据适合短历史诊断，但长序列覆盖不足，若直接训练会变成 toy prototype。

**定位方式：**
检查 `configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml` 指向的 `data/processed/amazon_2023_recall_clean_10000/user_sequences.train.jsonl`，统计序列质量：200 用户 smoke 中 `positive_len_ge_2_rate=0.575`、`positive_len_ge_10_rate=0.11`、`timestamp_ordered_rate=1.0`。这说明时间顺序可靠，短序列诊断可用，但长行为序列模型的数据覆盖不达标。

**解决方式：**
新增 `scripts/run_phase_5_sequence_ranker.py`：只输出 sequence data readiness、same-run baseline artifact inspection 和 method registry。`session_aware_reranker_short_history_diagnostic` 与 `attention_over_user_history_diagnostic` 标记为 diagnostic；DIN、DIEN、BST、SIM 因 `long_sequence_coverage_below_threshold` 及 adapter 缺失标记为 blocked，不进行伪训练。

**验证结果：**
`./.venv/Scripts/python.exe -m compileall scripts/run_phase_5_sequence_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_5_sequence_ranker or phase_4_neural_ranker"` 通过 2/2；真实 smoke `./.venv/Scripts/python.exe scripts/run_phase_5_sequence_ranker.py --output-dir outputs/ranking/phase_5_sequence_attention_ranker_smoke --limit-users 200` 产出 `comparison.json`，artifact inspection PASS，短序列方法 diagnostic，DIN/DIEN/BST/SIM blocked，最终路线仍为 same-run baseline。

**面试可讲点：**
这轮可以讲成“序列模型先过数据门禁”：我没有因为项目里有时间序列字段就强行堆 DIN/DIEN/BST，而是先量化历史长度、时间顺序和未来泄漏边界，把可做的短历史诊断与当前不能做的长序列模型清晰拆开。

### 2026-05-14 - Phase 5 正向收口与合同验证

**任务：**
同步 Phase 5 中文叙事，记录本轮 fine-rank / 序列正向收口结果。

**问题：**
Phase 5 smoke 能证明诊断链路和合同检查通过，但不能把序列/注意力方法写成 promotion；如果把 smoke 成功写成晋升，会越过 frozen candidate、top_k 和 online claims 的边界。

**定位：**
结合 `comparison.json` 与验证结果，核对 `candidate_pool_size=200`、`top_k=5`、`frozen_candidate_comparison.match=true`、`case_diagnostic_success=true`、`promotion_success=false`、`online_claims=[]`、`artifact_inspection=PASS`，确认本轮只有诊断证据，没有晋升证据。

**解决：**
把 Phase 5 结果明确收口为 diagnostic / blocked：短历史与注意力诊断保留，DIN / DIEN / BST / SIM 仍因序列覆盖和 adapter 条件不足维持 blocked，不把 positive push smoke 叙述成 promotion。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile scripts/run_phase_5_sequence_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_5_fine_rank_positive_push.py -q` 通过 `7 passed`；`outputs/ranking/phase_5_fine_rank_positive_push_smoke/comparison.json` 通过 contract 检查。

**面试可讲点：**
这轮可以讲成“把序列模型也放进同一套证据门禁”：不是因为模型名更高级就放松标准，而是先用合同检查证明冻结候选、诊断成功和在线承诺为空，再决定哪些方法只能留在 diagnostic lane。

### 2026-05-14 - Phase 6 工业式粗排→精排→重排默认诊断链

**任务：**
把工业推荐常见链路先实际接起来：粗排负责轻量 source/metadata 打分，精排负责 full-pool 规则与特征融合打分，重排负责 Top-K 局部约束，同时保持 frozen pool200 的排序实验边界。

**问题：**
如果直接把“工业链路”写成 champion，会绕过当前证据门禁；如果真实缩池，又会改变后续排序输入并污染召回/排序边界。首次 smoke 还发现 normalized additive 权重 `source_signal=0.24`、`item_feature=0.22` 不在 Phase 1.25 允许网格内，说明工业默认链路也必须服从已有实验底座。

**定位：**
检查 `rs_core/recsys/ranking.py`，确认已有 `coarse_rank_candidates`、`fine_rank_candidates`、`rerank_candidates` 三段可配置实现；检查 `outputs/ranking/phase_6_industrial_ranking_chain_smoke/comparison.json`，确认工业链路被记录为 `industrial_coarse_fine_rerank_chain_diagnostic`，且 `artifact_inspection=PASS`、frozen candidate match 为 true。

**解决：**
新增 Phase 6 runner：`coarse_rank` 使用 source-weighted metadata shadow score，不裁剪 pool；`fine_rank` 启用 normalized additive、source-aware fusion、item-feature rerank；`rerank` 保留 Top-5 source minimum 和 stable tie-break。GBDT/LambdaMART、神经序列和 Agent/online feedback 继续作为 blocked future route。越界权重已收回到允许网格 `0.2`。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile scripts/run_phase_6_industrial_ranking_chain.py tests/test_phase_6_industrial_ranking_chain.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_phase_6_industrial_ranking_chain.py -q` 通过 `4 passed`；真实 smoke `outputs/ranking/phase_6_industrial_ranking_chain_smoke/comparison.json` 显示 `candidate_pool_size=200`、`top_k=5`、`artifact_inspection=PASS`、`promotion_success=false`、`promotion_eligible=false`。

**面试可讲点：**
这轮亮点是“工业化不是堆模型名，而是把每个阶段放到正确证据边界里”。粗排、精排、重排都有可运行算法和 artifact，但不把 smoke 成功说成晋升；同时有限网格直接拦住越界调参，体现实验平台治理能力。

### 2026-05-13 - Phase 4 神经排序 CUDA 诊断原型

**任务：**
在 frozen pool200、`candidate_pool_size=200`、`top_k=5` 的排序实验底座上推进 Phase 4，验证 MLP / RankNet 这类神经排序原型是否能在真实 PyTorch/CUDA 环境中跑通，同时保持默认 diagnostic lane。

**遇到的问题：**
Phase 4 不能为了“深度排序”名词覆盖而直接宣称晋升。虽然当前 `.venv` 中 PyTorch CUDA 可用，但项目还没有神经排序 serving adapter、独立 valid/test promotion split、ADR 和完整 Wide&Deep/DeepFM/DCN/xDeepFM 特征交叉 schema；因此 GPU 训练只能证明训练链路可行，不能当作离线 promotion 证据。

**定位方式：**
检查依赖显示 `torch 2.11.0+cu128`、CUDA 可用、设备为 `NVIDIA GeForce RTX 4070 Ti SUPER`，但 `tensorflow/keras` 不可用；同时复用 LTR candidate rows，确认有 `features`、`label`、`user_id` 可支持 pointwise/pairwise diagnostic smoke。

**解决方式：**
新增 `scripts/run_phase_4_neural_ranker.py`：导出候选行后，用 PyTorch/CUDA 训练 `mlp_pointwise_cuda_diagnostic` 与 `ranknet_pairwise_cuda_diagnostic` 的轻量诊断模型，记录 device、loss、row count、feature count、peak CUDA memory；`lambdarank`、`listwise`、`wide_deep/deepfm/dcn/xdeepfm` 因 objective/schema/adapter 缺失写为 blocked。所有神经方法默认 `promotion_eligible=false`、`diagnostic_only=true`，baseline 仍为最终路线。

**验证结果：**
`./.venv/Scripts/python.exe -m compileall scripts/run_phase_4_neural_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_4_neural_ranker or phase_3_tree_ranker"` 通过 2/2；真实 smoke `./.venv/Scripts/python.exe scripts/run_phase_4_neural_ranker.py --output-dir outputs/ranking/phase_4_neural_ranker_smoke --limit-users 3` 产出 `comparison.json`，artifact inspection PASS，MLP/RankNet 为 diagnostic，LambdaRank/Listwise/Wide&Deep 系列为 blocked，final decision 仍是 `same_run_baseline`。

**面试可讲点：**
这轮可以讲成“GPU 不是晋升捷径，而是实验能力边界”：我用真实 CUDA 证明神经排序训练闭环可运行，但仍用 registry 和 promotion policy 锁住证据边界，只有 serving adapter、valid/test split、ADR 和稳定离线 lift 都补齐后，神经排序才可能从 diagnostic 转向 promotion。

### 2026-05-13 - Phase 3 树模型 / LambdaMART 依赖门禁

**任务：**
在 Phase 0/1/2 的统一排序底座上推进 Phase 3，检查 GBDT、XGBoost LambdaMART、LightGBM LambdaMART 是否具备真实训练和晋升条件，并在 frozen pool200、`candidate_pool_size=200`、`top_k=5` 边界下输出可审计状态。

**遇到的问题：**
当前虚拟环境缺少 `sklearn`、`xgboost`、`lightgbm` 依赖，现有 `rs_core/workflow/ltr_training.py` 只支持 pointwise logistic / pairwise perceptron。若用规则或浅层 LTR stand-in 冒充树模型，会破坏长期计划的证据可信度，也会把 GPU/依赖不足误写成模型收益。

**定位方式：**
用项目默认 `.venv` 检查依赖状态，确认三类树模型依赖均不可用；同时检查 LTR 训练链路，确认它能导出候选行作为未来树模型训练数据，但不能训练真实 GBDT/LambdaMART。对照 Phase 3 的目标，决定本阶段只做 dependency gate、candidate-row export 和 blocked registry，不做虚假 promotion。

**解决方式：**
新增 `scripts/run_phase_3_tree_ranker.py`：运行 same-run baseline 与候选训练行导出；把 `sklearn_gbdt_valid_test_promotion`、`xgboost_lambdamart_gpu_promotion`、`lightgbm_lambdamart_gpu_promotion` 写入 `method_registry` 的 blocked 状态；GPU 相关方法写入 `blocked-gpu-unavailable`；`candidate_row_export` 明确标记为 diagnostic-only、not a tree ranker model。

**验证结果：**
`./.venv/Scripts/python.exe -m compileall scripts/run_phase_3_tree_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_3_tree_ranker or phase_2_shallow_learned_runner"` 通过 2/2。新增测试验证 Phase 3 保持 pool200/top_k/frozen candidate equality，缺失依赖方法全部 blocked，候选行导出不具备 promotion eligibility。

**面试可讲点：**
这轮可以讲成“复杂模型不满足工程前置条件时，先把失败变成可审计资产”：不是为了覆盖 GBDT/LambdaMART 名词而伪造模型收益，而是明确依赖、GPU、训练 adapter、valid/test split 的缺口，并产出未来真实树模型可复用的候选行数据。

### 2026-05-13 - Phase 2 浅层 learned ranker 诊断闭环

**任务：**
在 Phase 0/1 底座之上推进 Phase 2：复用 frozen pool200、`candidate_pool_size=200`、`top_k=5`，运行 pointwise logistic 与 pairwise perceptron 浅层学习排序，并显式区分 LOPO diagnostic 与 valid/test promotion。

**遇到的问题：**
现有 Phase 1.28 已经能训练轻量 LTR，但它的训练口径是 leave-one-positive-out。LOPO 可以验证训练/推理链路，却不能当作当前 valid/test 晋升证据；同时项目里还没有独立 valid/test promotion 训练 split 的线性 ranker，因此不能为了补方法矩阵而伪造“线性模型已晋升”。

**定位方式：**
检查 `scripts/run_phase_1_28_lightweight_learned_ranker.py` 与 `rs_core/workflow/ltr_training.py`，确认可复用 `train_ltr_ranker()`、feature contract gate 与 leakage gate，但只支持 pointwise logistic / pairwise perceptron 的 LOPO 诊断训练。对照长期计划 Phase 2 的要求，决定把 pointwise/pairwise 纳入 diagnostic lane，把 valid/test promotion 线性 ranker 标记为 blocked。

**解决方式：**
新增 `scripts/run_phase_2_shallow_learned_ranker.py`：输出 Phase 0 风格的 `method_registry`、`artifact_inspection`、`gpu_resource_strategy`、`ranking_experiment_registry` 和 `final_decision`；pointwise/pairwise LTR 即使指标提升，也强制写入 `lopo_training_diagnostic_only` 与 `phase_2_valid_test_promotion_split_missing`，不允许晋升；`linear_ranker_valid_test_promotion` 作为 blocked method 写入 registry。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile scripts/run_phase_2_shallow_learned_ranker.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_2_shallow_learned_runner or phase_1_rule_ranking_runner or phase_0"` 通过 6/6；`./.venv/Scripts/python.exe scripts/run_phase_2_shallow_learned_ranker.py --output-dir outputs/ranking/phase_2_shallow_learned_ranker_smoke --limit-users 20` 成功生成 comparison。smoke 产物显示 artifact inspection PASS，pool/top_k 为 200/5，baseline 为 champion，pointwise/pairwise 为 diagnostic，linear ranker promotion 为 blocked，两个训练 gate 均为 PASS，最终仍为 `BASELINE_FINAL_ROUTE`。

**面试可讲点：**
这轮可以讲成“把浅层学习排序接进治理体系，但不放松证据门槛”：我验证了 pointwise/pairwise 的训练、推理、feature contract 和 leakage gate 都能跑通，同时明确 LOPO 只是诊断，valid/test promotion 训练 split 缺失时必须 blocked，而不是为了覆盖方法矩阵强行宣布模型有效。

### 2026-05-13 - Phase 1 规则排序 champion/challenger 复验

**任务：**
在 Phase 0 底座之上推进 Phase 1：用 frozen pool200、`candidate_pool_size=200`、`top_k=5` 复验可解释规则排序方法，包括 normalized additive、source-aware fusion、item feature rerank 和保守 coordinate rule combo。

**遇到的问题：**
Phase 1 不能只是复用旧 Phase 1.23/1.25 的零散 runner；长期计划要求每个方法族都进入同一套 method registry、artifact inspection 和 champion/challenger 状态机。否则规则排序即使无提升，也很难被清晰地标记为 retired/diagnostic，并与后续线性、树模型、深度排序公平比较。

**定位方式：**
检查 `scripts/run_phase_1_23_pool200_ranking_isolation.py`、`scripts/run_phase_1_25_pool200_normalized_additive.py` 与 `rs_core/recsys/ranking.py`，确认现有规则能力已经存在，但缺少一个 Phase 1 专用入口把这些方法放进 Phase 0 的统一底座里。硬边界继续保持 fixed recall base，不改召回语义、不改 pool200/top_k，不使用线上指标做当前离线 promotion evidence。

**解决方式：**
新增 `scripts/run_phase_1_rule_ranking_champion.py`：以 `configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml` 为固定输入，只叠加排序层 overrides；输出 `method_registry`、`artifact_inspection`、`gpu_resource_strategy`、`ranking_experiment_registry`、`stability_summary` 和 `final_decision`。规则方法当前都走 promotion lane，但必须过 frozen candidate equality、strict promotion gate 和 multi-run consistency 才能成为 challenger。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile scripts/run_phase_1_rule_ranking_champion.py tests/test_hybrid_demo.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_1_rule_ranking_runner or phase_0 or phase_1_29_terminal_runner"` 通过 6/6；`./.venv/Scripts/python.exe scripts/run_phase_1_rule_ranking_champion.py --output-dir outputs/ranking/phase_1_rule_ranking_champion_smoke --limit-users 20 --runs 1` 成功生成 comparison。smoke 产物显示 artifact inspection 为 PASS，`candidate_pool_size=200`、`top_k=5`，baseline 为 champion，四个规则候选均为 retired，最终仍选择 `same_run_baseline` / `BASELINE_FINAL_ROUTE`。

**面试可讲点：**
这轮可以讲成“把可解释规则排序纳入长期实验治理，而不是靠手调权重碰运气”：规则方法虽然没有晋升，但它们被统一放进 registry、artifact gate 和 champion/challenger 体系，为后续线性、GBDT/LambdaMART、深度排序提供了可比较的强基线和 no-promote 证据。

### 2026-05-13 - Phase 0 长期排序实验底座复用化

**任务：**
把长期排序计划的 Phase 0 从文档目标推进到可复用实验底座：在 `rs_core/recsys/evaluation.py` 中沉淀 method registry、artifact inspection 和 GPU resource summary，并让 Phase 1.29 terminal runner 复用这些底座能力。

**遇到的问题：**
已有 Phase 1.29 runner 能输出 terminal route 对照，但底座能力还散落在 runner 内部；如果后续 GBDT、LambdaMART、RankNet、DIN/DIEN 或 GPU 方法各自实现一套检查逻辑，容易再次出现候选池漂移、diagnostic-only 被误晋升、CPU toy smoke 被包装成真实收益等问题。

**定位方式：**
沿 `scripts/run_phase_1_29_terminal_ranking_route.py` 的输出链路检查 comparison 结构，确认缺少跨阶段可复用的 `method_registry`、`gpu_resource_strategy` 和统一 artifact inspection；再对照 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 的硬边界，确认 Phase 0 只做排序实验治理底座，不改召回语义、不改 frozen pool200、`candidate_pool_size=200`、`top_k=5`。

**解决方式：**
新增 `build_ranking_method_registry_entry()`、`build_ranking_gpu_resource_summary()`、`inspect_ranking_run_artifacts()`：统一记录方法状态（champion/challenger/diagnostic/retired/blocked 等）、GPU 是否必需及不可用时的 blocked/diagnostic 状态、artifact 路径完整性、pool200/top_k 边界、frozen candidate match 和 diagnostic promotion violation。Phase 1.29 runner 现在输出 `method_registry` 与 `gpu_resource_strategy`，并复用统一 artifact inspection。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile rs_core/recsys/evaluation.py scripts/run_phase_1_29_terminal_ranking_route.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -k "phase_0 or phase_1_29_terminal_runner"` 通过 5/5。测试覆盖 method registry 状态、未知状态拒绝、GPU blocked / diagnostic-cpu-smoke 语义、artifact inspection 对路径/边界/frozen mismatch/diagnostic 晋升违规的拦截，以及 Phase 1.29 runner 输出 `method_registry` 和 `gpu_resource_strategy`。

**面试可讲点：**
这轮可以讲成“先做排序实验操作系统，再堆模型”：把主流排序方法都接入同一套 registry、artifact gate、GPU 资源策略和 promotion 边界，后续每个方法是 champion、challenger、diagnostic 还是 blocked 都能被证据化管理，而不是靠口头判断。

### 2026-05-13 - Phase 1.31 final offline route selection

**任务：**
把 frozen pool200 的终局收口到最终离线排序路线，并明确 no-promote 理由。

**遇到的问题：**
Phase 1.23 / 1.24 / 1.25 / 1.28 都没有形成稳定 lift；如果把 LOPO 训练或轻量 LTR 的 gate PASS 误写成 promotion evidence，会把治理和收益混在一起。

**定位方式：**
对照 `dic/phases/RANKING_LONG_RUNNING_EXPLORATION_PLAN.md` 的 Phase 1.31 选择规则，复核 `rs_core/recsys/evaluation.py` 里的 `terminal_ranking_promotion_gate()`、`strict_ranking_promotion_status()`，以及 `outputs/ranking/phase_1_28_lightweight_learned_ranker/comparison.json` / `.md`。

**解决方式：**
最终离线路线定为 `same_run_baseline`；`normalized_additive`、`source-aware fusion`、`item_feature_rerank`、`pointwise_logistic_lopo_ltr` 和 `pairwise_perceptron_lopo_ltr` 保持 `diagnostic-only / no-promote`。ADR 中显式写出 excluded invalid evidence、underpowered segment 边界和 frozen pool200 约束。

**验证结果：**
`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_evaluation.py tests/test_ltr.py tests/test_two_tower_training.py` 通过 117/117；`./.venv/Scripts/python.exe -m compileall rs_core scripts tests` 通过；`./.venv/Scripts/python.exe scripts/run_phase_1_28_lightweight_learned_ranker.py --limit-users 5` 成功生成 `outputs/ranking/phase_1_28_lightweight_learned_ranker/comparison.json` 和 `comparison.md`，其中 `all_variants_valid=true`，baseline 与两个 LTR 变体的 frozen candidate comparison 均匹配，两个 LTR 变体均保持 `PARTIAL diagnostic-only`。

**面试可讲点：**
先把证据边界固定住，再做路线选择；没有 promote 就明确写 no-promote，而不是把诊断性结果包装成收益。

### 2026-05-13 - Phase 1.30 物理流水线证据与晋升边界收口

**任务：**
把 Phase 1.30 收口成“物理流水线证据”，明确它只证明 recall→coarse→fine→rerank 的链路可复验，不等于 promotion evidence。

**遇到的问题：**
这轮 smoke 已经能证明 stage 闭环、artifact 完整和 frozen candidate match，但如果把 pipeline trace、artifact inspection 或 smoke PASS 直接写成晋升结果，就会把系统可观测性和模型收益混在一起；同时线上指标当前还没有进入离线证据链，不能提前写入结论。

**定位方式：**
对照 `outputs/verification/verification_phase_1_30_smoke/comparison.json` 与 `outputs/verification/verification_phase_1_26_regression/comparison.json`，复核 `candidate_pool_size=200`、`top_k=5`、`artifact_inspection=PASS`、`physical_pipeline_inspection=PASS`、`frozen_candidate_match=true`、coarse/fine/rerank stage counts 均为 3225，以及 `online_metric_claims=[]`；再确认 Phase 1.26 regression 的 LTR LOPO 仍是 `diagnostic-only`、`promotion_eligible=false`，tree/LambdaMART 仍 blocked。

**解决方式：**
把 Phase 1.30 写成物理流水线收口而不是晋升收口：明确这组证据只能证明 stage 闭环、artifact 完整和 frozen candidate match，不代表当前存在 promotion evidence；同时把 online metrics 继续留在 future-only 边界，把 LOPO/gate/smoke 统一标成 diagnostic-only。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_evaluation.py tests/test_ltr.py` 通过 130/130；Phase 1.30 smoke PASS，Phase 1.26 regression PASS。

**面试可讲点：**
这轮可以讲成“先把物理流水线和晋升证据分开治理”：系统层面我已经证明 stage 能闭环、artifact 能对齐、frozen candidate 能匹配，但我没有把这些可观测性结果伪装成模型提升，而是把它们归为诊断资产，为后续模型晋升保留干净证据边界。

### 2026-05-13 - Phase 1.26 典型排序链路与真实训练实验底座

**任务：**
把长期排序路线从“治理底座”推进到可讲清楚的典型排序链路：目标架构按 `recall → coarse_rank → fine_rank → rerank` 组织，但当前离线实现只落在 `frozen pool200 → learned fine ranker → bounded rerank trace`，不把粗排缩池或线上业务指标伪造成当前证据。

**遇到的问题：**
前一轮排序工作容易把 gate、smoke、依赖 blocked 或 diagnostic-only 记录误讲成“主流排序方法真实实验”。这会导致两个风险：一是把缺 GPU / 缺 serving adapter 的 LambdaMART、GBDT 状态包装成效果结论；二是把 LOPO 训练或 LTR gate PASS 误当成 valid/test promotion evidence。

**定位方式：**
沿 `rs_core/recsys/ranking.py`、`rs_core/workflow/ltr_training.py`、`scripts/run_phase_1_26_real_ranking_experiments.py` 和 `outputs/ranking/phase_1_26_real_ranking_experiments_smoke/comparison.json` 复核证据链，重点检查 `candidate_pool_size=200`、`top_k=5`、frozen candidate match、训练配置、训练日志、模型 artifact、candidate rows、case diff、registry state 与 diagnostic-only reasons 是否齐全。

**解决方式：**
在 ranking 输出中补齐 coarse/fine/rerank 三段 `score_trace`、stage rank 与 rank movement，让当前单阶段排序也能按工业链路解释；新增 Phase 1.26 runner，真实训练 pointwise logistic LOPO LTR 与 pairwise perceptron LOPO LTR，并输出 `training_config.json`、`training_log.json`、`ltr_model.json`、`ltr_candidate_rows.jsonl` 与 case diff。对 `sklearn_gbdt_fine_ranker`、`xgboost_lambdamart_fine_ranker`、`lightgbm_lambdamart_fine_ranker`，在依赖、GPU 或候选级 serving adapter 不满足时明确标记 `blocked`，不生成虚假的 promotion 结论。

**验证结果：**
`./.venv/Scripts/python.exe -m py_compile scripts/run_phase_1_26_real_ranking_experiments.py rs_core/recsys/ranking.py` 通过；`./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py -q -k "score_trace or phase_1_26_real_ranking_runner_contract"` 通过 3/3；`./.venv/Scripts/python.exe scripts/run_phase_1_26_real_ranking_experiments.py --output-dir outputs/ranking/phase_1_26_real_ranking_experiments_smoke --limit-users 20 --seed 20260513` 成功生成 smoke comparison。产物中 `artifact_inspection.status=PASS`，baseline 与两个 LTR 变体均保持 pool200/top_k=5/frozen candidate match；两个 LTR 变体为真实训练但仍是 `diagnostic`，tree/LambdaMART 方法为 `blocked`。

**面试可讲点：**
这轮可以讲成“把排序从手写权重实验升级为可审计的工业排序实验链路”：先明确粗排、精排、重排的目标架构，再在 frozen pool200 上真实训练轻量 learned ranker，并用 score trace、artifact inspection、case diff 和 registry 约束证据边界。没有收益或条件不足的方法被如实标记为 diagnostic/blocked，而不是为了项目叙事包装成成功。

### 2026-05-13 - Phase 1.32 metadata_neighbor_recall 机会门与专项 ablation

**任务：**
继续 baseline_vNext 之后的新召回 source 探索，对 `metadata_neighbor_recall` 做机会门、性能修复和同合同专项 ablation，判断它是否能替代或补充 `semantic_title_category_expansion`。

**问题：**
miss-user audit 显示 metadata 机会覆盖很高，但这只是聚合诊断，不是边际命中证据；原始 metadata neighbor 实现还会对每个 seed 扫描完整 metadata index，导致 ablation 成本过高。如果不先加机会门和性能边界，容易在长跑中既得不到结论，也把诊断 target 误用成实验参数。

**定位方式：**
固定 `valid_test`、`limit_users=500`、`users_with_holdout=138`、`candidate_pool_size=200` 和 holdout hash `927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2`。`source_opportunity_summary.json` 显示 `baseline_miss_users=132`，metadata opportunity users 为 132，超过门槛 14；随后读取 `metadata_only_capped/metadata_neighbor/metrics.json` 与已完成的 baseline/semantic lane 对比，只看 recall-only candidate pool 指标和 source marginal contribution。

**解决方式：**
把 metadata neighbor 改成 bucketed train-visible metadata index：按 token/category 建桶，按 seed 取候选集合，并用 `metadata_neighbor_max_bucket_candidates` 做 per-seed 上限；ablation runner 支持 `ablation_experiments`，可以只跑 metadata lane，避免被无关 source 长跑阻塞。no-leakage contract 明确 holdout/miss target id 只用于 diagnostics/evaluation，不参与候选生成、query construction、target-driven source index construction/filtering、candidate whitelist 或参数选择；静态商品 catalog metadata 可作为非 holdout-label 派生的 train-visible item feature 建索引，但不能由 target 列表驱动筛选或调参。

**验证结果：**
`metadata_only_capped` run 完成且 same holdout verified。metadata lane `candidate_hit_users=17`、`candidate_hit_rate_at_pool=0.123188`、`recall_at_pool=0.064151`、`candidate_count_avg=132.2`；metadata source 覆盖 454 个用户、272 个 item、2870 个 recall candidates，但没有出现在 `source_marginal_candidate_hit_users` 或 `candidate_hit_source_coverage`。对照 baseline_only 为 17 个 candidate-hit users，`semantic_title_category` 为 19 个且有 2 个 marginal candidate-hit users。结论是 metadata neighbor 可运行但不晋升，当前 baseline_vNext 继续保持 semantic/title-category。

**面试可讲点：**
这轮的价值是把“看起来有机会”的 source 变成可证伪实验：先用 miss-user gate 判断值得跑，再用索引化降低工程成本，最后用边际 candidate-hit 证据否决晋升。它体现的是召回实验治理，而不是盲目增加更多 source。

### 2026-05-13 - Phase 4 三阶段实验计划与弱指标收口

**任务：**

把 Phase 4 从“只看 Top-5 成败”改成“coarse shadow / fine / rerank / future-online”四路对照的可执行计划，并说明 `coarse_rank` 从占位符变成 shadow 主路。

**遇到的问题：**

`top_k=5` 只有五个位置，天然命中稀疏；单个位置的波动会把 coarse/fine/rerank 的真实变化放大成“成败结论”。如果只盯 Top-5，很容易把诊断能力误写成晋升结论，也容易忽略 `rank movement`、`near-miss rescue`、`source coverage`、`candidate_hit_rate_at_pool` 这类更早出现的弱信号。

**定位方式：**

对照 `outputs/ranking/phase_1_26_real_ranking_experiments_smoke/comparison.json`、`outputs/verification/verification_phase_1_30_smoke/comparison.json`、`outputs/ranking/phase_1_31_ranking_algorithm_scaffold_smoke/comparison.json`、`outputs/ranking/phase_4_neural_ranker_smoke/comparison.json` 和 `outputs/ranking/phase_7_8_future_online_gate_smoke/comparison.json`，复核 `candidate_pool_size=200`、`top_k=5`、`frozen_candidate_match=true`、`artifact_inspection=PASS`，以及 coarse/fine/rerank stage counts 的物理流水线证据；再检查 Phase 7/8 gate，确认 future-online 仍只能保留门禁，不能晋升。

**解决方式：**

把 `coarse_rank` 改写成 shadow coarse main lane：继续计算 coarse score / trace / rank movement，但不缩池、不改变召回语义；同时把弱指标写成诊断口径，只用于解释和选路，而不是 promotion evidence。三阶段主线明确为 coarse shadow、fine learned ranker、rerank bounded trace，另把 CTR/CVR/GMV、bandit、RL、Agent feedback 留到 future-online。

**验证结果：**

已有 smoke 证据表明 stage artifact、frozen candidate match 和 comparison registry 能稳定复现；Phase 4 神经排序 smoke 仍只保留 diagnostic/blocked，Phase 7/8 仍是 future-online / future-agent-online。相关证据文件包括 `outputs/ranking/phase_1_26_real_ranking_experiments_smoke/comparison.json`、`outputs/verification/verification_phase_1_30_smoke/comparison.json`、`outputs/ranking/phase_1_31_ranking_algorithm_scaffold_smoke/comparison.json`、`outputs/ranking/phase_4_neural_ranker_smoke/comparison.json`、`outputs/ranking/phase_7_8_future_online_gate_smoke/comparison.json`。

**面试可讲点：**

这轮可以讲成“把排序实验从单点 Top-5 成败，升级为分层诊断体系”：我把 coarse/fine/rerank/future-online 分开治理，用弱指标解释为什么某些方法值得继续跑、为什么某些方法只能诊断，避免把短期 smoke 误当成模型晋升。

### 2026-05-13 - Phase 4 stage shadow metrics 最终回填

**任务：**

把 Phase 4 的最终验证收口到可复述的证据段：补充 stage shadow metrics、弱指标和主路矩阵的最终结果，并证明它们仍然只属于 diagnostic/supporting。

**遇到的问题：**

如果只看 `top_k=5`，很容易把 coarse shadow 的 `rank movement`、`coarse shadow retention`、`would_drop_positive` 这类弱信号忽略掉；但这些信号也不能被当作 promotion evidence，否则会把诊断能力包装成模型晋升。

**定位方式：**

对照 `scripts/run_phase_4_stage_shadow_metrics.py`、`tests/test_phase_4_stage_shadow_metrics.py` 和 `outputs/ranking/phase_4_stage_shadow_metrics_smoke/comparison.json`，核对 `candidate_pool_size=200`、`top_k=5`、`artifact_inspection=PASS`、`frozen match/hash` 未变，以及 recall / merge 语义未变。

**解决方式：**

把弱指标明确限定为 diagnostic/supporting，把 coarse shadow 仅作为 retained main lane 记录；在 comparison 中同时保留 stage main-lane matrix、coarse shadow retention 和 would_drop_positive 的证据，但不把它们提升为 promotion gate。

**验证结果：**

`py_compile` 通过，相关 pytest 共 `11 passed`，smoke 输出稳定生成；comparison 继续保持 `candidate_pool_size=200`、`top_k=5`、`artifact_inspection=PASS`、`frozen match/hash` 不变，且没有 online promotion evidence。

**面试可讲点：**

这轮可以讲成“把深层排序路线的最终收口做成证据分层”：我没有拿弱指标替代晋升证据，而是把它们限定成诊断信号，用来解释 coarse shadow 为什么继续保留、为什么某些方法仍然只能留在 diagnostic lane。
