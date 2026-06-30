# Phase 1.31 Final Offline Ranking Route ADR

- 日期：2026-05-13
- 状态：Accepted
- 决策范围：冻结 pool200 的离线排序路线选择

## 背景

当前终局选择只允许在 frozen pool200 上做排序侧判断，不改召回语义，不改 `candidate_pool_size=200`，不改 `top_k=5`，也不把 serving、frontend、display 或线上指标纳入本次证据。

## 决策

最终离线排序路线选择 `same_run_baseline` 作为当前阶段的默认最终路线。

`normalized_additive`、`source-aware fusion`、`item_feature_rerank`、`pointwise_logistic_lopo_ltr`、`pairwise_perceptron_lopo_ltr` 保持 `diagnostic-only / no-promote`，不作为当前阶段的最终离线路线。

## 证据摘要

1. Phase 1.23 / 1.24 / 1.25 的 frozen-pool 比较没有形成稳定 lift，`hit_rate_at_k`、`ndcg_at_k`、`mrr_at_k` 没有出现可晋升的持续改善。
2. Phase 1.28 的轻量 learned ranker 已经打通训练、推理、registry、gate 和 frozen equality，但两个 LTR 变体仍然是 `PARTIAL diagnostic-only`，且没有把 Top-K 指标推到可晋升区间。
3. `terminal_ranking_promotion_gate()` 已经把 `minimum_runs=3`、`required_consistent_runs=2`、`minimum_segment_users=30`、`minimum_segment_positive_users=5` 和 invalid/stop 排除写成硬门禁；当前证据没有满足 Promote 条件。

## No-Promote Rationale

- 没有任何候选在相同 frozen pool200 口径下形成稳定的 Promote 证据。
- LOPO 训练成功、feature/leakage gate PASS，只能说明训练路径可审计，不等于可晋升。
- invalid/stop 证据必须从 promotion 里排除，不能拿来凑正向结论。
- underpowered segment 只保留诊断，不进入 promotion 计数。

## invalid / excluded evidence

- `INVALID/STOP` run 及其 freeze drift 不参与 promotion 判断。
- `ltr_enabled=true` 的轻量 LTR 评估属于 `PARTIAL diagnostic-only`，不作为晋升证据。
- low-sample / underpowered segment 只用于诊断，不作为 Promote 依据。
- LOPO 训练 gate PASS 只证明训练契约成立，不证明离线路线应晋升。

## 边界未破坏说明

- 不改召回语义。
- 不改 `candidate_pool_size=200`。
- 不改 `top_k=5`。
- 不把线上 CTR / CVR / GMV / P95 / SLO 写成这轮的离线晋升证据。
- 不把 serving / frontend / display 集成混进本次 ADR。

## 验证证据

- `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_evaluation.py tests/test_ltr.py tests/test_two_tower_training.py`
- `./.venv/Scripts/python.exe -m compileall rs_core scripts tests`
- `./.venv/Scripts/python.exe scripts/experiments/ranking/run_phase_1_28_lightweight_learned_ranker.py --limit-users 5`

### 产物

- `D:\sinrotic_code\python_project\summer\RS_agent\outputs\phase_1_28_lightweight_learned_ranker\comparison.json`
- `D:\sinrotic_code\python_project\summer\RS_agent\outputs\phase_1_28_lightweight_learned_ranker\comparison.md`

## 面试可讲点

- 先冻结候选池和排序边界，再做路线选择，避免把召回漂移误判成排序收益。
- 把 `No-Promote` 当成显式结论，而不是失败掩饰，能让路线收口更可审计。
- LOPO、门禁、registry、frozen equality 必须先串成证据链，再决定是否升级到更复杂的 learned ranker。