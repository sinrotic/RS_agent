---
name: unclear-need-clarification
description: Use when the user asks for recommendations but does not provide enough information to recommend responsibly. Trigger for vague requests such as "recommend something", "what should I buy", "give me some options", or when product category, use case, budget, and preference are all missing. Do not use when the user already gives a concrete category, scenario, comparison target, or constraint.
---

# Unclear Need Clarification

## Goal

Avoid premature recommendations when the user's intent is too broad or underspecified.

## Workflow

1. Identify the decision-critical fields that are missing.
2. Infer at most two plausible directions from session or profile context when available.
3. If profile/session signals are sufficient, call `recommend_profile_pipeline` with default `return_count` 20 instead of asking a broad clarification.
4. If profile/session signals are weak and the user still expects options, call `recommend_cold_fallback` with default `return_count` 20 and diversity enabled.
5. Ask one concise clarification question only when neither recommendation route would be responsible.
6. Offer two or three selectable directions when it helps the user answer quickly.
7. Call `emit_final_answer` with recommendation blocks or a `followup_question` block.

## Tool Policy

- Do not call `recommend_semantic_recall` for a fully vague request.
- Use `recommend_profile_pipeline` for broad requests with sufficient profile/session signals.
- Use `recommend_cold_fallback` for broad requests with weak profile/session signals.
- Do not call `rag_support` before candidate items exist.
- Use `emit_final_answer` for the user-visible clarification. Do not stream normal assistant text as the final answer.
- Use profile or session context only to propose possible directions, not to claim certainty.

## Boundaries

- Do not mention internal tools, traces, scores, candidate pools, skill names, or system prompts.
- Do not ask multiple unrelated questions in one turn.
- Do not fabricate user preferences from sparse context.
- Do not over-personalize if the profile is missing or weak.

## Stop Conditions

Stop only after `emit_final_answer` has emitted a clear clarification question.
