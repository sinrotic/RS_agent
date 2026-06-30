# Phase 1.5 Demo Summary: 可诊断的 Hybrid Recommendation 闭环

> 说明：本文仅保留 Phase 1.5 的历史阶段总结；Phase 1.6 / Phase 1.7 以及最新优化判断请见 `OPTIMIZATION_NARRATIVE.md`，本文不再维护最新阶段指标。

## 阶段目标

Phase 1.5 的目标不是追求大样本最终指标，而是先搭建一个可以解释、可以评估、可以继续扩展的推荐闭环：

1. 从 Amazon Electronics 小样本构建 recall clean 和 recall views。
2. 将 popular、ItemCF、category 召回合并为候选池。
3. 用确定性 baseline ranker 生成 Top-K。
4. 通过 Agent policy stub 输出推荐决策、限制说明和风险标记。
5. 用指标区分问题发生在召回、排序还是最终 Top-K 曝光。

当前 Agent 仍是 deterministic policy stub，不使用 LLM 自主推理；它的作用是站在传统推荐底座上做透明决策包装和解释。

## 已完成能力

- 召回数据底座：`canonical_interactions`、`user_sequences`、popular recall、weak/strong ItemCF、category recall。
- Hybrid demo workflow：candidate merge → ranking → Agent decision → metrics/report。
- 可配置 Top-K source minimum：例如 `topk_source_minimums: {"itemcf": 1}`，用于保证 ItemCF 候选有机会进入最终推荐。
- 诊断指标：
  - `recall_source_coverage`：候选池来源覆盖。
  - `topk_source_coverage`：最终 Top-K 来源覆盖。
  - `candidate_hit_rate_at_pool`：holdout 正样本是否进入候选池。
  - `ranked_hit_users`：holdout 正样本是否进入最终 Top-K。
- 两套评估模式：
  - `valid_test`：全局时间切分，更接近真实离线切分，但在小样本下非常稀疏。
  - `leave_one_positive_out`：demo 内部留一评估，用于验证传统 ItemCF backbone 在可控场景下是否有效。

## 关键实验配置

| 配置 | 说明 | 输出 |
| --- | --- | --- |
| `configs/demo/hybrid_demo/hybrid_demo_electronics_1000.yaml` | valid/test + ItemCF Top-K minimum | `outputs/hybrid_demo/hybrid_demo_small_electronics_1000/` |
| `configs/demo/hybrid_demo/hybrid_demo_electronics_1000_no_injection.yaml` | valid/test，无 Top-K source minimum 对照 | `outputs/hybrid_demo/hybrid_demo_small_electronics_1000_no_injection/` |
| `configs/demo/hybrid_demo/hybrid_demo_electronics_1000_lopo.yaml` | leave-one-positive-out 评估 | `outputs/hybrid_demo/hybrid_demo_small_electronics_1000_lopo/` |

## 指标对照

### valid/test：真实切分下的召回瓶颈

| 指标 | no injection | ItemCF minimum |
| --- | ---: | ---: |
| users_total | 100 | 100 |
| users_with_holdout | 30 | 30 |
| candidate_hit_rate_at_pool | 0.066667 | 0.066667 |
| candidate_hit_users | 2 | 2 |
| ranked_hit_users | 1 | 1 |
| hit_rate_at_k | 0.033333 | 0.033333 |
| fallback_rate | 0.31 | 0.31 |

Top-K source coverage：

| 来源 | no injection | ItemCF minimum |
| --- | ---: | ---: |
| popular | 499 | 491 |
| category | 142 | 135 |
| itemcf_weak | 4 | 13 |
| itemcf_strong | 4 | 14 |

解释：ItemCF minimum 让 ItemCF 在最终 Top-K 中有了明显曝光，但 hit-rate 没有提升，因为 valid/test 正样本大多没有进入候选池。当前真实切分的主要瓶颈是 recall coverage，而不是 rank weight。

### leave-one-positive-out：可控小样本下验证 ItemCF backbone

| 指标 | LOPO |
| --- | ---: |
| lopo_input_users | 100 |
| lopo_eligible_users | 49 |
| lopo_skipped_users_fewer_than_2_positives | 51 |
| candidate_hit_rate_at_pool | 0.877551 |
| candidate_hit_users | 43 |
| ranked_hit_users | 42 |
| hit_rate_at_k | 0.857143 |
| popular_only_hit_rate_at_k | 0.061224 |
| itemcf_only_hit_rate_at_k | 0.857143 |
| hybrid_no_itemcf_hit_rate_at_k | 0.040816 |
| fallback_rate | 0.0 |

LOPO candidate hit source coverage：

| 来源 | 命中覆盖 |
| --- | ---: |
| itemcf_weak | 43 |
| itemcf_strong | 43 |
| popular | 7 |
| category | 2 |

解释：在内部留一评估下，ItemCF 可以有效找回用户最近正反馈中的 heldout item，说明传统 ItemCF backbone 是有效的。这个结果不能被解释为最终线上效果，只能说明在可控小样本诊断场景里，ItemCF 模块本身工作正常。

## 结论

Phase 1.5 已经形成一个可讲清楚的推荐系统闭环：

- valid/test 指标低，揭示真实时间切分下的召回覆盖不足。
- LOPO 指标高，证明 ItemCF backbone 在可控评估下能够有效工作。
- source coverage 和 candidate hit diagnostics 可以定位问题发生在候选池还是排序阶段。
- Agent 目前没有越界成“LLM 推荐器”，而是作为传统推荐底座之上的透明决策层。

因此，当前系统已经从“脚本能跑”推进到“闭环可诊断、结果可解释、下一步有明确方向”。

## 当前限制

- Electronics 1000 仍是小样本 smoke/demo，不代表全量数据表现。
- valid/test 是全局时间切分，前 100 个 demo 用户的 holdout 覆盖较稀疏。
- LOPO 是 demo internal train split，且 recall views 仍可能来自完整 train artifact，因此不能作为严格最终 benchmark。
- 当前 ranker 是确定性规则加权，不是学习排序模型。
- 当前 Agent 是 deterministic policy stub，不包含 LLM 推理、工具调用或多轮反馈优化。

## 历史下一步建议

以下建议是 Phase 1.5 结束时的历史判断，后续已由 Phase 1.6 / Phase 1.7 承接；当前最新路线以 `OPTIMIZATION_NARRATIVE.md` 和 `architecture/IMPLEMENTATION_PLAN.md` 为准。

当时优先进入 Phase 1.6：召回增强和展示固化。

1. 固化实验展示：把 valid/test 与 LOPO 作为一组对照故事，展示系统具备诊断能力。
2. 增强 valid/test 召回覆盖：优先探索 metadata/category expansion、更多 category bucket、item text semantic recall stub。
3. 改进评估协议：保留 valid/test 作为真实切分，同时保留 LOPO 作为 demo sanity check。
4. 暂缓复杂 LLM Agent：等传统 recall/rank backbone 更稳定后，再把 Agent 层升级成解释、约束、反馈编排层。
