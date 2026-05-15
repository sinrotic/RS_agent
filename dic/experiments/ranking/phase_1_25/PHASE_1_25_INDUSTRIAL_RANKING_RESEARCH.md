# Phase 1.25 工业排序研究报告

## 1. 工业指标 / 算法概览

本轮只讨论排序侧，不动召回、不改 `candidate_pool_size`、不做模型训练或集成，不把 LOPO 当成晋升证据。研究目标是把当前 frozen pool200 的问题拆成“候选是否进池”“是否排进 Top-K”“是否存在可解释的 source 冲突”。

| 层级 | 工业职责 | 主要指标 | 这轮的判断含义 |
| --- | --- | --- | --- |
| 候选池边界诊断（只读） | 确认候选是否已在 frozen pool 内 | `candidate_hit_rate_at_pool`, `recall_at_pool`, `candidate_count_avg`, `fallback_rate` | 只确认池边界稳定，不扩池、不改召回，再谈排序收益 |
| 精排 / 重排 | 把命中推进 Top-K | `hit_rate_at_k`, `ndcg_at_k`, `mrr_at_k`, `map_at_k` | Top-K 没涨时，优先看排序分隔度而不是扩大候选池 |
| 诊断指标 | 解释失败模式 | `candidate_hit_missed_topk_users`, `candidate_hit_rank_p50/p90`, `top1_score_gap_avg`, `source_coverage`, `per_source_topk_contribution` | 用来判断是权重失衡、特征弱信号，还是 source 冲突 |
| 工程约束 | 控制可比性 | `freeze_fields`, `all_variants_valid`, `drift` | frozen-pool 同跑比较成立，才允许讨论排序策略 |

工业上常见的排序链路可以粗分为三段：

1. **粗排 / 召回层（仅作工业背景）**：负责 coverage，核心是“能不能进池”，本轮不调整这一层。
2. **精排层**：负责精细排序，核心是“能不能排到前面”。
3. **重排层**：负责局部约束与业务偏好，核心是“在不破坏主指标的前提下调顺序”。

在这条链路上，`recall_at_pool` 高不代表 `hit_rate_at_k` 一定高；如果 `candidate_hit_missed_topk_users` 很多，说明问题更像是 **near-miss 没有被推进 Top-K**，而不是候选压根没进池。

---

## 2. 项目失败模式映射表

| 项目证据 | 工业失败模式 | 当前含义 | 对下一步的要求 |
| --- | --- | --- | --- |
| 1.23 / 1.24 都是 `all_variants_valid=true`，`drift={}`，freeze 字段完全一致 | 候选池稳定，问题不在池漂移 | 排序层是主责任边界 | 后续实验必须继续 frozen-pool 同跑 |
| `no_rerank_baseline`、`ranking_v2`、`item_feature_rerank`、`source_aware_fusion` 的 `hit_rate_at_k=0.014493`、`ndcg_at_k=0.002779`、`mrr_at_k=0.006039` 全相同 | 排序增量饱和 / 特征信号太弱 | 现有手写权重没有形成有效分隔 | 不能再默认加权就会涨分 |
| `candidate_hit_rate_at_pool=0.123188`，但 `candidate_hit_missed_topk_users=15`，`ranked_hit_users=2` | near-miss 救援失败 | 候选进池了，但没被推进前 5 | 需要 rank-gap aware 的局部策略，而不是扩大池 |
| `candidate_hit_rank_p50=26.0`、`candidate_hit_rank_p90=68.0` | 排序 margin 不够 | 命中项分布太靠后，score separation 不够 | 需要检查权重、归一化、tie-break 逻辑 |
| 1.24 里 `semantic_only +0.8` 仍然 `VALID / NO PROMOTION`，delta 全为 0 | 单源语义 boosting 失效 | 说明语义侧不是简单“权重太小”，而更像信号已饱和 | 不应继续只加 semantic 权重 |
| 1.23 里 `ranking_v2` / `item_feature_rerank` / `source_aware_fusion` 同样无提升 | source-level 调参到边界 | 源融合已经覆盖了主要可用收益 | 下一步应转向更细粒度的 feature / rank-gap 诊断 |

---

## 3. Phase 1.23 / 1.24 复盘

### Phase 1.23：pool200 same-run ranking isolation

- 产物：`outputs/ranking/phase_1_23_pool200_ranking_isolation/comparison.json`、`comparison.md`
- 结论：所有变体都 `VALID`，没有 freeze drift，说明候选池边界干净。
- 基线指标：
  - `candidate_hit_rate_at_pool=0.123188`
  - `candidate_count_avg=152.272`
  - `fallback_rate=0.0`
  - `hit_rate_at_k=0.014493`
  - `ndcg_at_k=0.002779`
  - `mrr_at_k=0.006039`
  - `map_at_k=0.001208`
  - `candidate_hit_missed_topk_users=15`
- 关键现象：`ranking_v2`、`item_feature_rerank`、`source_aware_fusion` 与 no-rerank baseline 完全一致，delta 全为 0。
- 结论落点：这是一次干净的 **VALID but NO PROMOTION**，证明当前排序增量还不足以把稀疏正例推入 Top-K。

### Phase 1.24：pool200 semantic near-miss rescue

- 产物：`outputs/ranking/phase_1_24_pool200_semantic_near_miss_rescue/comparison.json`、`comparison.md`
- 结论：`no_rerank_baseline` 与 `semantic_near_miss_rescue` 同样都 `VALID`，`drift={}`，freeze 字段一致。
- 指标结果：
  - `hit_rate_at_k=0.014493`
  - `ndcg_at_k=0.002779`
  - `mrr_at_k=0.006039`
  - `recall_at_pool=0.065962`
- 关键现象：`semantic_only +0.8` 没有带来任何 Top-K、NDCG、MRR 的改善。
- 结论落点：语义单源轻量加权没有解决 near-miss，说明问题不是“再多加一点 semantic”，而是排序层的分隔逻辑本身不够强。

### 合并复盘

两轮合起来看，最重要的不是“跑通了实验”，而是把责任边界缩清楚了：

1. **候选池是稳定的**，所以不是 recall 漂移。
2. **Top-K 没有改善**，所以不是简单的 source-level 手调问题。
3. **near-miss 很多但推进失败**，所以下一步应该围绕 rank gap、feature 强度、局部 tie-break 做轻量诊断，而不是直接跳到新模型训练。

---

## 4. 下一实验候选

### 候选 A：现有 source 权重再标定

**目标**：只在当前 source-aware / ranking 配置的已有旋钮上做小范围重标定，观察能否把 `candidate_hit_missed_topk_users` 中的 near-miss 推进 Top-5。

**冻结池基线**：
- `candidate_hit_rate_at_pool=0.123188`
- `candidate_count_avg=152.272`
- `fallback_rate=0.0`
- `hit_rate_at_k=0.014493`
- `ndcg_at_k=0.002779`
- `mrr_at_k=0.006039`
- `map_at_k=0.001208`
- `candidate_hit_missed_topk_users=15`

**valid/test 报告**：
- 单独报告 frozen pool200 上的 `hit_rate_at_k`、`ndcg_at_k`、`mrr_at_k`、`map_at_k`、`recall_at_pool`、`candidate_hit_missed_topk_users`。
- 只要这些指标没有明显改善，就按 `NO PROMOTION` 处理。

**LOPO 报告**：
- 只作为泛化诊断单独汇报同一组指标。
- LOPO 只看“是否和 valid/test 同方向”，不作为晋升依据。

**promotion / stop gate**：
- promotion：`hit_rate_at_k`、`ndcg_at_k`、`mrr_at_k` 至少一项稳定提升，同时 `map_at_k` 不退化，`candidate_hit_missed_topk_users` 明显下降。
- stop：四个主指标基本持平，或 `candidate_hit_rank_p50/p90` 没有下移。

**风险**：过度偏向 popular 或 semantic，导致局部排序更“顺眼”但总体 hit 不变。

**预期失败信号**：`delta=0` 再次出现，或 Top-5 结果只是换序没有新增命中。

---

### 候选 B：item_feature rerank 的阈值 / 归一化重标定

**目标**：不引入训练，只检查现有 item_feature 路径是否存在过硬的阈值、归一化或组合特征压扁问题，让 item-level 特征真正参与 near-miss 救援。

**冻结池基线**：同上，重点观察 `candidate_hit_rank_p50=26.0`、`candidate_hit_rank_p90=68.0` 这类深尾分布是否能收缩。

**valid/test 报告**：
- 报告 `hit_rate_at_k`、`ndcg_at_k`、`mrr_at_k`、`map_at_k`、`candidate_hit_rank_p50/p90`、`candidate_hit_missed_topk_users`。
- 若只有 rank 分布改善但 Top-K 不变，不算晋升。

**LOPO 报告**：
- 单独输出同样指标，验证是否只是把 LOPO 排名推顺，而没有真正改善 valid/test。

**promotion / stop gate**：
- promotion：至少把一部分 `candidate_hit_missed_topk_users` 转成 topk hit。
- stop：Top-K 命中数仍停留在 2，或者 rank 分布不变。

**风险**：特征阈值微调可能只是在少数样本上制造局部过拟合。

**预期失败信号**：`item_feature_rerank` 继续与 baseline 同分，或者仅出现 `category_diversity` 变化而主指标不动。

---

### 候选 C：near-miss rank-gap tie-break

**目标**：在不改召回的前提下，为候选池内排名接近的条目加一个轻量 tie-break 规则，专门处理“已进池但掉出 Top-5”的样本。

**冻结池基线**：
- 继续使用 frozen pool200。
- 重点对照 `candidate_hit_missed_topk_users=15`、`ranked_hit_users=2` 和 `top1_score_gap_avg`。

**valid/test 报告**：
- 单独报告 Top-K 命中、NDCG/MRR、`candidate_hit_rank_avg`、`candidate_hit_rank_p50/p90`。
- 如果只提升多样性或解释性，不提升 hit，不算晋升。

**LOPO 报告**：
- 同样单独报告，用于检查 tie-break 是否只是把 LOPO 排序“润色”。

**promotion / stop gate**：
- promotion：`candidate_hit_missed_topk_users` 减少，且 `hit_rate_at_k`、`ndcg_at_k`、`mrr_at_k` 至少一项上升。
- stop：只有 source coverage 变好，但 Top-K 没动。

**风险**：tie-break 过强会挤掉本来就稳定的高分项，造成局部修正、全局回退。

**预期失败信号**：命中项位置没变，但非命中项排序被频繁扰动。

---

## 5. 结论

Phase 1.23 / 1.24 已经把边界收紧到一个很清楚的结论：**当前问题是排序分隔度不足，不是候选池不稳，也不是简单地再加一点 semantic 或 source 权重就能解决。**

下一轮只值得做轻量、可停、可解释的排序诊断实验；如果这些实验仍然不能压低 `candidate_hit_missed_topk_users`，就应把结论明确写成“当前手工排序已到边界”，再考虑更强的学习排序路径，但那已经超出这次研究范围。