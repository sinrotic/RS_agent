---
name: cold-user-onboarding
description: Use when the user has little or no usable profile history, a missing or sparse profile_user_id, a new session without meaningful interaction signals, or cold-start context is explicitly marked. Use alongside explicit recommendation flows when the current need is clear but personalization is weak. Do not use when reliable recent behavior or stable preferences are available.
---

# Cold User Onboarding

## Goal

Handle recommendations for users with sparse or missing personalization signals without pretending to know long-term preferences.

## Workflow

1. Check whether the current turn has a clear need.
2. If the need is vague, ask a lightweight preference question rather than recommending immediately.
3. If the need is clear, use `recommend_semantic_recall`; current-turn intent is stronger than missing profile history.
4. If the need is broad or empty and profile/session signals are weak, call `recommend_cold_fallback` with default `return_count` 20 and diversity enabled.
5. Rely on broad relevance, popularity, diversity, and current-turn constraints.
6. State uncertainty naturally when personalization is weak.
7. Prefer diverse candidate coverage over narrow personalization.
8. When concrete products should be shown, call `render_product_cards` for the final item ids.
9. Call `emit_final_answer` with ordered blocks for the user-visible response.

## Tool Policy

- Use `recommend_semantic_recall` when the user gives a clear need, even for a cold user.
- Use `recommend_cold_fallback` only when the user need and profile/session signals are both weak.
- Use `catalog_card` after candidate item ids are available.
- Use `rag_support` only when final candidate explanations need evidence.
- Use `render_product_cards` before emitting product card blocks.
- Use `emit_final_answer` for all user-visible final content. Do not stream normal assistant text as the final answer.
- Do not use old or missing profile data as if it were reliable.

## Boundaries

- Do not claim long-term preferences for a cold user.
- Do not expose profile sparsity diagnostics, internal traces, scores, or tool names.
- Do not overfit recommendations to a single weak signal.
- Do not ask heavy onboarding surveys; keep preference discovery lightweight.

## Stop Conditions

Stop only after `emit_final_answer` has emitted either a lightweight preference question or a cold-start recommendation with honest uncertainty.
