from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_lab.experiments.recall.pool500.fallback_completion.config import FALLBACK_SOURCE_TO_CANONICAL_SOURCE
from rs_lab.experiments.recall.pool500.governance.fallback_completion_contract import FallbackSource

PASS_GUARDED_FALLBACK_REPAIR = "PASS_GUARDED_FALLBACK_REPAIR"
DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
STOP = "STOP"
CO_VISIT_FALLBACK_SOURCE = FallbackSource.SEED_METADATA_NEIGHBOR.value
CO_VISIT_CANONICAL_SOURCE = FALLBACK_SOURCE_TO_CANONICAL_SOURCE[CO_VISIT_FALLBACK_SOURCE]
GOVERNANCE_FLAGS = (
    "candidate_generation_allowed",
    "ranking_input_replacement_allowed",
    "ranking_replacement_allowed",
    "promotion_allowed",
    "pool1000_allowed",
    "final_pool500_ready_claimed",
    "full_pool500_ready_declared",
)


def build_co_visit_fallback_repair_task_audit(
    *,
    fallback_completion_audit: dict[str, Any],
    fallback_completion_validation: dict[str, Any] | None = None,
    underfill_audit: dict[str, Any] | None = None,
    source_contribution_audit: dict[str, Any] | None = None,
    source_overlap_audit: dict[str, Any] | None = None,
    route_manifest: dict[str, Any] | None = None,
    require_co_visit_contribution: bool = True,
) -> dict[str, Any]:
    fallback_completion_validation = fallback_completion_validation or {}
    underfill_audit = underfill_audit or {}
    source_contribution_audit = source_contribution_audit or {}
    source_overlap_audit = source_overlap_audit or {}
    route_manifest = route_manifest or {}

    global_audit = fallback_completion_audit.get("global") if isinstance(fallback_completion_audit.get("global"), dict) else {}
    contribution = global_audit.get("fallback_source_contribution") if isinstance(global_audit.get("fallback_source_contribution"), dict) else {}
    co_visit_added_count = int(contribution.get(CO_VISIT_FALLBACK_SOURCE, 0) or 0)
    fallback_added_count = sum(int(value or 0) for source, value in contribution.items() if source != FallbackSource.PERSONALIZED_PRIMARY.value)
    user_count = int(global_audit.get("target_user_count", 0) or 0)
    users_with_target = int(global_audit.get("users_with_target_candidates", 0) or 0)
    underfilled_after = int(global_audit.get("underfilled_user_count", 0) or 0)
    duplicate_user_count = int(global_audit.get("duplicate_item_per_user_count", 0) or 0)
    over_target_count = int(global_audit.get("per_user_over_target_count", 0) or 0)
    avg_popular_ratio = float(global_audit.get("average_popular_ratio", 0.0) or 0.0)
    avg_fallback_ratio = float(global_audit.get("average_fallback_ratio", 0.0) or 0.0)

    co_visit_users = [
        str(user.get("user_id"))
        for user in fallback_completion_audit.get("per_user", [])
        if isinstance(user, dict) and int((user.get("source_mix") or {}).get(CO_VISIT_FALLBACK_SOURCE, 0) or 0) > 0
    ]
    completion_status_counts: dict[str, int] = {}
    for user in fallback_completion_audit.get("per_user", []) if isinstance(fallback_completion_audit.get("per_user"), list) else []:
        status = str(user.get("completion_status") or "UNKNOWN")
        completion_status_counts[status] = completion_status_counts.get(status, 0) + 1

    blockers: list[str] = []
    diagnostics: list[str] = []
    if fallback_completion_validation and fallback_completion_validation.get("valid") is not True:
        blockers.append("fallback_completion_validation_invalid")
    if duplicate_user_count:
        blockers.append("duplicate_item_per_user_count_positive")
    if over_target_count:
        blockers.append("per_user_over_target_count_positive")
    if _governance_flag_violations(route_manifest):
        blockers.append("route_manifest_governance_flag_open")
    if user_count and users_with_target < user_count:
        diagnostics.append("guarded_sample_still_has_underfilled_users")
    if fallback_added_count <= 0:
        diagnostics.append("fallback_added_count_zero")
    if co_visit_added_count <= 0:
        diagnostics.append("co_visit_seed_metadata_neighbor_contribution_zero")
    if require_co_visit_contribution and co_visit_added_count <= 0:
        diagnostics.append("co_visit_required_for_guarded_merge_but_absent")
    if avg_popular_ratio >= 0.8 and fallback_added_count > 0:
        diagnostics.append("popular_ratio_high_check_fallback_quality")

    decision = STOP if blockers else DIAGNOSTIC_ONLY if diagnostics else PASS_GUARDED_FALLBACK_REPAIR
    return {
        "schema_version": "co_visit_fallback_repair_task_audit_v1",
        "created_at": datetime.now(UTC).isoformat(),
        "source": CO_VISIT_CANONICAL_SOURCE,
        "fallback_source": CO_VISIT_FALLBACK_SOURCE,
        "task_role": "underfill_fallback_repair_not_single_source_recall",
        "primary_acceptance_metric": "fallback_underfill_repair_completion",
        "not_primary_metrics": ["HitRate", "Recall"],
        "decision": decision,
        "status": "PASS" if decision == PASS_GUARDED_FALLBACK_REPAIR else decision,
        "global": {
            "target_user_count": user_count,
            "users_with_target_candidates": users_with_target,
            "underfilled_user_count_after_fallback": underfilled_after,
            "fallback_added_count": fallback_added_count,
            "co_visit_fallback_added_count": co_visit_added_count,
            "co_visit_user_count": len(co_visit_users),
            "average_fallback_ratio": avg_fallback_ratio,
            "average_popular_ratio": avg_popular_ratio,
            "duplicate_item_per_user_count": duplicate_user_count,
            "per_user_over_target_count": over_target_count,
            "completion_status_counts": completion_status_counts,
        },
        "source_contribution_snapshot": (source_contribution_audit.get("sources") or {}).get(CO_VISIT_CANONICAL_SOURCE, {}),
        "source_overlap_available": bool(source_overlap_audit.get("pairwise_user_item_overlap_count")),
        "underfill_audit_snapshot": {
            "status": underfill_audit.get("status"),
            "remaining_underfilled_user_count": underfill_audit.get("remaining_underfilled_user_count"),
            "users_with_500_candidates": underfill_audit.get("users_with_500_candidates"),
        },
        "co_visit_users": co_visit_users[:100],
        "blockers": blockers,
        "diagnostics": diagnostics,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
    }


def write_co_visit_fallback_repair_task_audit(
    *,
    route_output_dir: Path,
    output_path: Path,
    require_co_visit_contribution: bool = True,
) -> dict[str, Any]:
    audit = build_co_visit_fallback_repair_task_audit(
        fallback_completion_audit=_read_json(route_output_dir / "fallback_completion_audit.json"),
        fallback_completion_validation=_read_optional_json(route_output_dir / "fallback_completion_validation.json"),
        underfill_audit=_read_optional_json(route_output_dir / "underfill_audit.json"),
        source_contribution_audit=_read_optional_json(route_output_dir / "source_contribution_audit.json"),
        source_overlap_audit=_read_optional_json(route_output_dir / "source_overlap_audit.json"),
        route_manifest=_read_optional_json(route_output_dir / "manifest.json"),
        require_co_visit_contribution=require_co_visit_contribution,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit


def _governance_flag_violations(payload: dict[str, Any]) -> list[str]:
    return [flag for flag in GOVERNANCE_FLAGS if payload.get(flag) is True]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _read_optional_json(path: Path) -> dict[str, Any]:
    return _read_json(path) if path.is_file() else {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit co_visit_fallback_repair as a pool500 fallback/underfill repair task source.")
    parser.add_argument("--route-output-dir", type=Path, required=True)
    parser.add_argument("--output-path", type=Path, required=True)
    parser.add_argument("--allow-zero-co-visit-contribution", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audit = write_co_visit_fallback_repair_task_audit(
        route_output_dir=args.route_output_dir,
        output_path=args.output_path,
        require_co_visit_contribution=not args.allow_zero_co_visit_contribution,
    )
    print(json.dumps({"decision": audit["decision"], "status": audit["status"], "output_path": str(args.output_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
