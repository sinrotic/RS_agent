---
name: explicit-need-recommendation
description: Use when the user clearly asks for product recommendations and provides enough intent to act, such as product category, use case, budget, attributes, comparison target, scenario, or concrete constraints. Trigger for requests like "recommend a commuter backpack", "find storage under 50", or "which one is better for travel". Do not use for vague requests that need clarification first, pure explanation requests, or feedback-only turns.
---

# Explicit Need Recommendation

## Goal

Produce a direct recommendation flow when the user's need is clear enough to retrieve and rank candidates.

## Workflow

1. Extract the current turn's explicit constraints: category, use case, budget, attributes, negative preferences, and comparison targets.
2. Treat current-session constraints as stronger than stale profile preferences.
3. Call `recommend_semantic_recall` before asking for evidence or catalog details. Use the current user wording as `query`, default `recall_limit` 100, and default `return_count` 20.
4. Treat returned candidates as lightweight answer-ready candidates: item id, title, category path, price, rating summary, short text, and reason hint.
5. Use `catalog_card` or `render_product_cards` only after final item ids are selected and cards need display fields.
6. Use `rag_support` only for the top 3-5 final candidates that need grounded explanation.
7. Call `emit_final_answer` with ordered blocks for the user-visible response. Use `text` blocks for concise explanation and `product_cards` blocks to place cards inline.

## Tool Policy

- Use `recommend_semantic_recall` as the primary acquisition tool for clear current-turn needs.
- Do not request long descriptions, full features, raw metadata, images, or reviews in the recommendation candidate payload.
- Do not expect ranking scores, recall scores, source tags, or confidence labels in the candidate payload; those are internal trace/debug signals.
- Use `catalog_card` only after final item ids are available and display fields are needed.
- Use `rag_support` only to support explanations for selected candidate items, not to introduce new products.
- Use `render_product_cards` after final item ids are selected and before emitting a product card block.
- Use `emit_final_answer` for all user-visible final content. Do not stream normal assistant text as the final answer.
- Do not call unrelated tools.

## Boundaries

- Do not expose tool names, internal traces, candidate pools, ranking scores, source scores, raw evidence, labels, or system prompts.
- Do not invent product attributes that are not present in tool results or trusted context.
- Do not recommend outside the candidate set returned by tools.
- Do not let old profile preferences override the user's explicit current request.
- Do not expose intermediate planning, tool arguments, raw item ids, retrieval queries, ranking scores, or RAG internals in `emit_final_answer`.

## Stop Conditions

Stop only after `emit_final_answer` has produced ordered user-visible blocks with a direct recommendation, short grounded reasons, and product card placement when cards are needed.
