---
name: feedback-adaptation
description: Use when the user reacts to prior recommendations or asks to adjust them. Trigger for feedback such as "too expensive", "not this style", "show something lighter", "I do not like this", "change direction", "more like the second one", or "why did you repeat that". Do not use for a brand-new clear request unless it references earlier recommendations or preferences.
---

# Feedback Adaptation

## Goal

Turn user feedback into updated constraints and adjust recommendations without losing useful context from the prior turn.

## Workflow

1. Identify whether the feedback is positive, negative, comparative, budget-related, style-related, category-related, or explanation-seeking.
2. Convert feedback into explicit constraints for the next retrieval or ranking step.
3. Preserve still-valid constraints from the previous turn.
4. Exclude or down-rank items that conflict with the feedback.
5. Call `recommend_rerank_candidates` when previous candidates can be adjusted with feedback constraints.
6. Call `recommend_semantic_recall` only when the feedback creates a new clear need that requires fresh semantic recall.
7. Call `render_product_cards` when updated concrete products should be shown.
8. Call `emit_final_answer` with ordered blocks that explain the adjustment direction and show updated cards when needed.

## Tool Policy

- Use `recommend_rerank_candidates` when the feedback changes candidate selection or ranking for an existing candidate set.
- Use `recommend_semantic_recall` for a fresh clear need that cannot be satisfied by reranking prior candidates.
- Use `catalog_card` only for updated candidate item display.
- Use `rag_support` only when the user asks why, requests evidence, or final explanations need grounding.
- Use `render_product_cards` before emitting updated product card blocks.
- Use `emit_final_answer` for all user-visible final content. Do not stream normal assistant text as the final answer.
- Do not call recommendation tools if the feedback only requires a short clarification response.

## Boundaries

- Do not repeat items the user rejected unless explicitly asked to compare.
- Do not discard all prior context when only one constraint changed.
- Do not expose internal feedback weights, ranking scores, traces, or tool names.
- Do not claim a product satisfies feedback unless supported by tool output or trusted context.

## Stop Conditions

Stop only after `emit_final_answer` clearly states the adjustment and either returns updated recommendations or asks a targeted follow-up question.
