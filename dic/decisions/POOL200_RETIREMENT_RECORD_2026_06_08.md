# Pool200 Retirement Record - 2026-06-08

## Decision

The old pool200 recall/ranking experiment artifacts are retired. Pool200 is no longer treated as an active recall route artifact in the route registry.

This record keeps the historical evidence boundary while allowing the obsolete pool200 configs and generated outputs to be removed from the working tree.

## Retired Artifact Families

- `configs/recall/phase_1_21/`
- `configs/recall/phase_1_23/`
- `configs/recall/phase_1_32/`
- `configs/ranking/phase_1_22/`
- `configs/ranking/phase_1_23/`
- `configs/ranking/phase_1_24/`
- `configs/ranking/phase_1_25/`
- `outputs/recall/phase_1_21_recall_coverage/`
- `outputs/recall/phase_1_25_pool200_recall_health/`

## Historical Summary

The final pool200 source-balanced recall evidence was diagnostic/historical only after this retirement.

Key historical metrics from `outputs/recall/phase_1_21_recall_coverage/current_main_route_pool200_source_balanced/metrics.json` before removal:

- `empty_candidate_rate`: `0.0`
- `fallback_rate`: `0.0`
- `candidate_hit_rate_at_pool`: `0.137681`
- `recall_at_pool`: `0.069227`
- `users_with_holdout`: `138`
- `candidate_pool_size`: `200`

## Current Boundary

- Pool200 configs and generated outputs should not be used as current route inputs.
- Pool500 remains governed by its own recall-only gate and registry contracts.
- Historical docs under `dic/` may continue to mention pool200 as evidence history, but those references are records, not active artifacts.
- Source code and tests may still contain pool200 guardrail terminology where needed to protect old boundary assumptions or negative cases.
