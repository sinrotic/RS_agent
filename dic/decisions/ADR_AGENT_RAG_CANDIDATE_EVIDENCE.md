# Agent RAG 候选内证据选择器 ADR

- 日期：2026-05-26
- 状态：implemented（2026-05-26）
- 决策范围：把 RAG 固化为候选内证据选择器与解释上下文层

## 背景

RAG 已进入可用闭环，但它的职责必须保持清晰：只为 Agent 提供候选内证据和可追溯上下文，不改候选集合治理，也不改排序结果。

## 决策

采用 `rag.evidence_mode=off|shadow|explain` 作为唯一显式开关，配合可选的 `rag.max_evidence_per_item` 控制证据上限。

- `off`：不构建 `rag_context`，保持旧链路。
- `shadow`：构建并记录 `rag_context`，但解释输出不变。
- `explain`：解释链路消费 display-safe 的候选证据。

## 不变性边界

- 不修改 `candidates`
- 不修改 `ranking`
- 不修改 `final_items`
- 不修改 `scores`

RAG 只影响解释上下文与证据消费，不作为新的召回或排序主路。

## provenance gate

证据净化在来源侧完成，拦截以下类型：

- `label`
- `holdout`
- `oracle`
- `ground_truth`
- `test_truth`
- `diagnostic_label`
- `eval_label`
- `target`
- future-like evidence

拦截维度覆盖 `source`、`provenance`、`source_path` 和 `artifact_scope`。

## 为什么这样做

- 解释需要真实商品证据，但不能把诊断产物带进前台。
- shadow 模式可以先验收上下文质量，再决定是否启用解释消费。
- 通过模式开关和证据门禁，回滚路径简单，风险边界清晰。

## 备选方案

- 直接把 item knowledge card 并入主路：范围过大，容易把解释层和召回层耦合。
- 直接上 embedding / BM25 索引：可扩展性更强，但不适合作为第一版收口方式。
- 先只做 explain：缺少 shadow 观测层，不利于验证证据质量。

当前选择是先把候选内证据选择器做成可用、可回滚、可审计的第一版，再按需扩展 item_knowledge、BM25 或 embedding 检索。

## 诊断与验证

- `pytest tests/test_rag_core.py tests/test_agent_dialogue.py tests/test_agent_rollout_schema.py tests/test_agent_runtime.py tests/test_display_contract.py`：`45 passed in 0.59s`
- `py_compile` 通过涉及模块
- 最小脚本验证：`shadow` / `explain` 均满足 `rag_context_exists=true`、`kept_evidence_count=3`
- 最小脚本验证：`explain` 的 why 消费了 Audio evidence，display payload 未暴露 `rag_context` / diagnostics

## 回滚

如需回退，只要把 `rag.evidence_mode` 设为 `off` 即可恢复旧链路。

## 面试可讲点

- 先把 RAG 限定为候选内证据层，再通过模式开关、证据门禁和展示边界把它做成可审计能力。
- 这类设计能避免解释层污染候选层，也让 shadow 到 explain 的升级路径足够平滑。