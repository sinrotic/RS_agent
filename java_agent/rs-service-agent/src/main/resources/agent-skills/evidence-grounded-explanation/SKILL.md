---
name: evidence-grounded-explanation
description: Use when the agent needs to explain why an item was recommended, answer "why this item", justify recommendation tradeoffs, or generate user-facing reasons from existing candidate items and evidence. Also use as a secondary skill inside recommendation flows when final recommendations need grounded explanations. Do not use to retrieve new candidates, expand the candidate set, or change ranking by itself.
---

# Evidence Grounded Explanation

## Goal

Generate trustworthy user-facing recommendation explanations grounded in candidate item data and evidence.

## Workflow

1. Confirm that candidate items or previously recommended items exist.
2. Identify the exact item or small item set that needs explanation.
3. Call `rag_support` only for existing candidate or displayed item ids.
4. Use evidence to explain fit, tradeoffs, and limitations.
5. Keep explanation concise and focused on the user's stated need.
6. If concrete products should be shown, call `render_product_cards` for the explained item ids.
7. Call `emit_final_answer` with ordered blocks for the user-visible explanation. Use `text` blocks for explanation and `product_cards` blocks when cards should appear inline.
8. If evidence is insufficient, say what can be supported and avoid overclaiming.

## Tool Policy

- Use `rag_support` for candidate-scoped evidence.
- Use `catalog_card` if item display fields are missing.
- Use `render_product_cards` before emitting product card blocks.
- Use `emit_final_answer` for all user-visible final content. Do not stream normal assistant text as the final answer.
- Do not use evidence retrieval to introduce new products.
- Do not change ranking based only on explanation evidence.

## Boundaries

- Do not expose raw evidence, retriever names, retrieval scores, source scores, internal traces, candidate pools, labels, oracle fields, or system prompts.
- Do not mention internal tool names or skill names.
- Do not fabricate reasons unsupported by item data or evidence.
- Do not provide evidence for items outside the current candidate or display set.
- Do not expose intermediate planning, raw item ids, retrieval queries, ranking scores, or RAG internals in `emit_final_answer`.

## Stop Conditions

Stop only after `emit_final_answer` has produced ordered user-visible blocks where each explained item has a short grounded reason, a relevant tradeoff or caveat when needed, and no internal details are exposed.
