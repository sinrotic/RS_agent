from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_core.common.runtime import enforce_project_venv
from rs_core.workflow.pool500_ranking_adapter import POOL500_DIAGNOSTIC_EXTRA_SOURCES, POOL500_LINEAGE_KEY, adapt_pool500_rows_to_candidates
from rs_lab.experiments.ranking.build_cold_deepfm_ranking_training_dataset import (
    TRAIN_HISTORY_FEATURE_NAMES,
    _positive_events,
    _train_history_feature_index,
    _train_history_features,
    _format_time,
    _parse_time,
    build_screening_plan,
    screen_positive_events,
)

SCHEMA_VERSION = "pool500_frozen_candidate_eval_dataset_v1"
ROW_SCHEMA_VERSION = "pool500_frozen_candidate_eval_row_v1"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "ranking" / "datasets" / "pool500_frozen_candidate_eval"
PASS = "PASS"
STOP = "STOP"
STOP_FOR_RANKING_EFFECT = "STOP_FOR_RANKING_EFFECT"
LABEL_FIELDS = ("label_binary", "label", "clicked", "purchased", "is_hit")
TIME_FIELDS = ("label_event_time", "event_time", "timestamp", "unix_timestamp", "review_time", "unixReviewTime")
CANDIDATE_FORBIDDEN_LABEL_FIELDS = set(LABEL_FIELDS) | set(TIME_FIELDS) | {"holdout_hit", "label_used_for"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a non-oracle frozen pool500 candidate evaluation dataset.")
    parser.add_argument("--pool500-candidates", required=True)
    parser.add_argument("--eval-label-artifact", required=True)
    parser.add_argument("--train-interactions", "--train-interactions-for-features", dest="train_interactions", default="", help="Optional train-only interactions path used to enrich eval rows with train-history features.")
    parser.add_argument("--feature-contract", default="")
    parser.add_argument("--eval-feature-cutoff-time", default="", help="Optional explicit train-end cutoff for eval history features; defaults to train max event time plus epsilon.")
    parser.add_argument("--history-feature-version", default="cold_deepfm_training_features_v2")
    parser.add_argument("--screening-policy", default="none", choices=["none", "user_first", "item_first"])
    parser.add_argument("--min-user-train-positive-count", type=int, default=2)
    parser.add_argument("--min-item-train-positive-user-count", type=int, default=2)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--eval-split", default="")
    parser.add_argument("--eval-user-allowlist", default="", help="Optional file of user_id values used to filter eval labels before joining.")
    parser.add_argument("--candidate-users-from-eval-labels", action="store_true", help="Keep only candidate rows whose user_id appears in filtered eval labels.")
    parser.add_argument("--limit-users", type=int, default=None)
    parser.add_argument("--max-candidate-rows", type=int, default=None, help="Bounded preflight read limit for large candidate files.")
    parser.add_argument("--max-candidate-users", type=int, default=None, help="Stop reading candidate rows after this many users have been collected.")
    parser.add_argument("--fast-source-fingerprint", action="store_true", help="Use path/size/mtime fingerprints instead of full-file sha256 for large-file preflight.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_pool500_frozen_candidate_eval_dataset_from_files(
        pool500_candidates_path=Path(args.pool500_candidates),
        eval_label_artifact_path=Path(args.eval_label_artifact),
        output_dir=Path(args.output_dir),
        train_interactions_path=Path(args.train_interactions) if args.train_interactions else None,
        feature_contract_path=Path(args.feature_contract) if args.feature_contract else None,
        eval_feature_cutoff_time=args.eval_feature_cutoff_time or None,
        history_feature_version=args.history_feature_version,
        screening_policy=args.screening_policy,
        min_user_train_positive_count=args.min_user_train_positive_count,
        min_item_train_positive_user_count=args.min_item_train_positive_user_count,
        eval_split=args.eval_split or None,
        eval_user_allowlist_path=Path(args.eval_user_allowlist) if args.eval_user_allowlist else None,
        candidate_users_from_eval_labels=args.candidate_users_from_eval_labels,
        limit_users=args.limit_users,
        max_candidate_rows=args.max_candidate_rows,
        max_candidate_users=args.max_candidate_users,
        fast_source_fingerprint=args.fast_source_fingerprint,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps(manifest["output_paths"], ensure_ascii=False, indent=2))


def build_pool500_frozen_candidate_eval_dataset_from_files(
    *,
    pool500_candidates_path: Path,
    eval_label_artifact_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    train_interactions_path: Path | None = None,
    feature_contract_path: Path | None = None,
    eval_feature_cutoff_time: str | None = None,
    history_feature_version: str = "cold_deepfm_training_features_v2",
    screening_policy: str = "none",
    min_user_train_positive_count: int = 2,
    min_item_train_positive_user_count: int = 2,
    eval_split: str | None = None,
    eval_user_allowlist_path: Path | None = None,
    candidate_users_from_eval_labels: bool = False,
    limit_users: int | None = None,
    max_candidate_rows: int | None = None,
    max_candidate_users: int | None = None,
    fast_source_fingerprint: bool = False,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    pool500_candidates_path = pool500_candidates_path.resolve()
    eval_label_artifact_path = eval_label_artifact_path.resolve()
    train_interactions_path = train_interactions_path.resolve() if train_interactions_path else None
    feature_contract_path = feature_contract_path.resolve() if feature_contract_path else None
    output_dir = output_dir.resolve()
    eval_user_allowlist_path = eval_user_allowlist_path.resolve() if eval_user_allowlist_path else None
    output_paths = _output_paths(output_dir)
    _precheck(pool500_candidates_path, eval_label_artifact_path, output_paths, overwrite, train_interactions_path=train_interactions_path, feature_contract_path=feature_contract_path)
    feature_contract = read_json(feature_contract_path) if feature_contract_path else {}
    feature_contract_gate = _feature_contract_gate(
        feature_contract,
        requested_screening_policy=screening_policy,
        min_user_train_positive_count=min_user_train_positive_count,
        min_item_train_positive_user_count=min_item_train_positive_user_count,
    )
    if feature_contract:
        history_feature_version = str(feature_contract.get("feature_version") or history_feature_version)

    history_feature_context = _history_feature_context(
        train_interactions_path,
        eval_feature_cutoff_time=eval_feature_cutoff_time,
        history_feature_version=history_feature_version,
        fast_source_fingerprint=fast_source_fingerprint,
        feature_contract=feature_contract,
        requested_screening_policy=screening_policy,
        min_user_train_positive_count=min_user_train_positive_count,
        min_item_train_positive_user_count=min_item_train_positive_user_count,
    )
    eval_user_allowlist = _read_user_allowlist(eval_user_allowlist_path) if eval_user_allowlist_path else None
    eval_label_rows, eval_filter_audit = _read_eval_label_rows(
        eval_label_artifact_path,
        eval_user_allowlist=eval_user_allowlist,
        eval_split=eval_split,
    )
    candidate_user_filter = _positive_user_ids(eval_label_rows) if candidate_users_from_eval_labels else None
    candidate_rows, candidate_read_audit = _read_candidate_rows(
        pool500_candidates_path,
        max_candidate_rows=max_candidate_rows,
        max_candidate_users=max_candidate_users,
        user_filter=candidate_user_filter,
    )
    adapter_result = adapt_pool500_rows_to_candidates(
        candidate_rows,
        extra_allowed_sources=POOL500_DIAGNOSTIC_EXTRA_SOURCES,
        allow_score_fallback=True,
    )
    candidates_by_user = adapter_result.get("candidates_by_user", {}) if adapter_result.get("status") == PASS else {}
    candidates_by_user, screening_audit = _apply_feature_contract_screening(candidates_by_user, feature_contract)
    if limit_users is not None:
        candidates_by_user = {user_id: candidates_by_user[user_id] for user_id in list(candidates_by_user)[: max(0, int(limit_users))]}

    candidate_artifact_sha256 = _source_fingerprint(pool500_candidates_path, fast=fast_source_fingerprint)
    eval_label_source_sha256 = _source_fingerprint(eval_label_artifact_path, fast=fast_source_fingerprint)
    label_by_pair = _positive_label_by_pair(eval_label_rows)
    coverage_gate = compute_candidate_coverage_gate(candidates_by_user, label_by_pair)
    oracle_gate = _oracle_injection_gate(
        candidate_rows,
        pool500_candidates_path=pool500_candidates_path,
        eval_label_artifact_path=eval_label_artifact_path,
        candidate_artifact_sha256=candidate_artifact_sha256,
        eval_label_source_sha256=eval_label_source_sha256,
    )

    rows = [] if adapter_result.get("status") != PASS else _build_eval_rows(
        candidates_by_user,
        label_by_pair,
        candidate_artifact_path=pool500_candidates_path,
        candidate_artifact_sha256=candidate_artifact_sha256,
        eval_label_source_path=eval_label_artifact_path,
        eval_label_source_sha256=eval_label_source_sha256,
        full_label_denominator=coverage_gate["full_label_denominator"],
        in_candidate_denominator=coverage_gate["in_candidate_denominator"],
        eval_split=eval_split,
        history_feature_context=history_feature_context,
    )
    blockers = []
    if adapter_result.get("status") != PASS:
        blockers.append({"code": "POOL500_ADAPTER_NOT_PASS", "severity": "blocker", "evidence": adapter_result.get("blockers", [])})
    if oracle_gate["status"] != PASS:
        blockers.append({"code": "FROZEN_EVAL_ORACLE_INJECTION_RISK", "severity": "blocker", "evidence": oracle_gate})
    if feature_contract_gate["status"] != PASS:
        blockers.append({"code": "FEATURE_CONTRACT_GATE_NOT_PASS", "severity": "blocker", "evidence": feature_contract_gate})
    history_feature_audit = _history_feature_audit(history_feature_context, rows, eval_label_rows)
    if history_feature_audit["status"] == STOP:
        blockers.append({"code": "EVAL_HISTORY_FEATURE_GATE_NOT_PASS", "severity": "blocker", "evidence": history_feature_audit})

    dataset_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": PASS if not blockers else STOP,
        "generated_at": datetime.now(UTC).isoformat(),
        "label_used_for": "evaluation_only",
        "candidate_generation_allowed": False,
        "candidate_label_injection_allowed": False,
        "ranking_effect_conclusion_allowed": coverage_gate["status"] == PASS and not blockers,
        "candidate_coverage_hard_gate": coverage_gate,
        "oracle_injection_gate": oracle_gate,
        "adapter_summary": _adapter_summary(adapter_result, candidates_by_user),
        "adapter_diagnostic_summary": _adapter_diagnostic_summary(adapter_result, candidate_rows),
        "history_feature_audit": history_feature_audit,
        "screening_audit": screening_audit,
        "feature_contract_gate": feature_contract_gate,
        "valid_test_used_for_feature_stats": False,
        "valid_test_used_for_negative_sampling": False,
        "source_manifest": {
            "candidate_artifact_path": str(pool500_candidates_path),
            "candidate_artifact_sha256": candidate_artifact_sha256,
            "eval_label_source_path": str(eval_label_artifact_path),
            "eval_label_source_sha256": eval_label_source_sha256,
            "eval_label_rows": len(eval_label_rows),
            "raw_eval_label_rows": eval_filter_audit["raw_eval_label_rows"],
            "eval_label_split_counts": _split_counts(eval_label_rows),
            "candidate_rows_read": candidate_read_audit["candidate_rows_read"],
            "raw_candidate_rows_seen": candidate_read_audit["raw_candidate_rows_seen"],
            "candidate_rows_filtered_by_user": candidate_read_audit["candidate_rows_filtered_by_user"],
            "adapter_extra_allowed_sources": sorted(POOL500_DIAGNOSTIC_EXTRA_SOURCES),
            "adapter_score_fallback_allowed": True,
            "max_candidate_rows": max_candidate_rows,
            "max_candidate_users": max_candidate_users,
            "fingerprint_mode": "path_size_mtime" if fast_source_fingerprint else "sha256",
            "eval_label_positive_pairs": len(label_by_pair),
            "label_join_key": "user_id,item_id|parent_asin",
            "feature_contract_path": str(feature_contract_path) if feature_contract_path else "",
            "feature_contract_hash": feature_contract.get("feature_contract_hash"),
        },
        "alignment_audit": _alignment_audit(
            eval_filter_audit,
            candidate_read_audit,
            candidates_by_user,
            label_by_pair,
            eval_user_allowlist_path=eval_user_allowlist_path,
            candidate_users_from_eval_labels=candidate_users_from_eval_labels,
        ),
        "dataset_summary": _row_summary(rows),
        "blockers": blockers,
        "recall_window_handoff": _recall_window_handoff(coverage_gate),
    }

    write_jsonl(output_paths["eval_rows"], rows)
    write_json(output_paths["coverage_gate"], coverage_gate)
    write_json(output_paths["oracle_injection_gate"], oracle_gate)
    write_json(output_paths["dataset_audit"], dataset_audit)
    manifest = {
        "schema_version": "pool500_frozen_candidate_eval_manifest_v1",
        "status": dataset_audit["status"],
        "screening_audit": screening_audit,
        "feature_contract_gate": feature_contract_gate,
        "generated_at": dataset_audit["generated_at"],
        "output_dir": str(output_dir),
        "output_paths": {name: str(path) for name, path in output_paths.items()},
        "label_used_for": "evaluation_only",
        "candidate_generation_allowed": False,
        "ranking_effect_conclusion_allowed": dataset_audit["ranking_effect_conclusion_allowed"],
        "candidate_coverage_hard_gate_status": coverage_gate["status"],
    }
    write_json(output_paths["manifest"], manifest)
    return manifest


def compute_candidate_coverage_gate(candidates_by_user: dict[str, list[Any]], label_by_pair: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    full_positive_pairs = set(label_by_pair)
    full_positive_users = {user_id for user_id, _ in full_positive_pairs}
    candidate_pairs = {(str(user_id), str(candidate.item_id)) for user_id, candidates in candidates_by_user.items() for candidate in candidates}
    in_candidate_pairs = full_positive_pairs & candidate_pairs
    in_candidate_positive_users = {user_id for user_id, _ in in_candidate_pairs}
    full_label_positive_users = len(full_positive_users)
    full_label_denominator = len(full_positive_pairs)
    user_gate_threshold = max(100, math.ceil(0.05 * full_label_positive_users))
    positive_gate_threshold = max(500, math.ceil(0.01 * full_label_denominator))
    status = PASS if len(in_candidate_positive_users) >= user_gate_threshold and len(in_candidate_pairs) >= positive_gate_threshold else STOP_FOR_RANKING_EFFECT
    return {
        "schema_version": "pool500_candidate_coverage_hard_gate_v1",
        "status": status,
        "candidate_coverage_hard_gate": status,
        "full_label_positive_users": full_label_positive_users,
        "full_label_denominator": full_label_denominator,
        "full_label_positives": full_label_denominator,
        "in_candidate_positive_users": len(in_candidate_positive_users),
        "in_candidate_positives": len(in_candidate_pairs),
        "in_candidate_denominator": len(in_candidate_pairs),
        "candidate_users": len(candidates_by_user),
        "candidate_rows": sum(len(candidates) for candidates in candidates_by_user.values()),
        "user_gate_threshold": user_gate_threshold,
        "positive_gate_threshold": positive_gate_threshold,
        "formula": "PASS iff in_candidate_positive_users >= max(100, ceil(0.05 * full_label_positive_users)) AND in_candidate_positives >= max(500, ceil(0.01 * full_label_denominator))",
        "failure_semantics": "small smoke / runner handoff only; no ranking-effect conclusion" if status != PASS else "ranking-effect evaluation allowed by coverage gate",
    }


def _output_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "manifest": output_dir / "manifest.json",
        "eval_rows": output_dir / "eval_rows.jsonl",
        "coverage_gate": output_dir / "coverage_gate.json",
        "oracle_injection_gate": output_dir / "oracle_injection_gate.json",
        "dataset_audit": output_dir / "dataset_audit.json",
    }


def _precheck(
    pool500_candidates_path: Path,
    eval_label_artifact_path: Path,
    output_paths: dict[str, Path],
    overwrite: bool,
    *,
    train_interactions_path: Path | None = None,
    feature_contract_path: Path | None = None,
) -> None:
    for path, name in ((pool500_candidates_path, "pool500_candidates"), (eval_label_artifact_path, "eval_label_artifact")):
        if not path.is_file():
            raise FileNotFoundError(f"{name} path does not exist or is not a file: {path}")
    if train_interactions_path is not None and not train_interactions_path.is_file():
        raise FileNotFoundError(f"train_interactions path does not exist or is not a file: {train_interactions_path}")
    if feature_contract_path is not None and not feature_contract_path.is_file():
        raise FileNotFoundError(f"feature_contract path does not exist or is not a file: {feature_contract_path}")
    if not overwrite:
        existing = [str(path) for path in output_paths.values() if path.exists()]
        if existing:
            raise FileExistsError(f"Output files already exist: {existing}")


def _feature_contract_gate(
    feature_contract: dict[str, Any],
    *,
    requested_screening_policy: str,
    min_user_train_positive_count: int,
    min_item_train_positive_user_count: int,
) -> dict[str, Any]:
    if not feature_contract:
        return {"schema_version": "pool500_eval_feature_contract_gate_v1", "status": PASS, "enabled": False}
    threshold_context = _screening_threshold_context(
        feature_contract,
        min_user_train_positive_count=min_user_train_positive_count,
        min_item_train_positive_user_count=min_item_train_positive_user_count,
        require_contract_thresholds=True,
    )
    reasons = list(threshold_context["reasons"])
    if feature_contract.get("screening_policy") != requested_screening_policy:
        reasons.append("screening_policy_mismatch")
    if not feature_contract.get("feature_names"):
        reasons.append("missing_feature_names")
    return {
        "schema_version": "pool500_eval_feature_contract_gate_v1",
        "status": PASS if not reasons else STOP,
        "enabled": True,
        "requested_screening_policy": requested_screening_policy,
        "contract_screening_policy": feature_contract.get("screening_policy"),
        "requested_thresholds": threshold_context["expected_thresholds"],
        "contract_thresholds": threshold_context["raw_thresholds"],
        "observed_thresholds": threshold_context["observed_thresholds"],
        "feature_version": feature_contract.get("feature_version"),
        "expected_feature_names": feature_contract.get("feature_names") or [],
        "feature_contract_hash": feature_contract.get("feature_contract_hash"),
        "reasons": reasons,
    }


def _screening_threshold_context(
    screening_source: dict[str, Any],
    *,
    min_user_train_positive_count: int,
    min_item_train_positive_user_count: int,
    require_contract_thresholds: bool,
) -> dict[str, Any]:
    expected_thresholds = {
        "min_user_train_positive_count": max(1, int(min_user_train_positive_count)),
        "min_item_train_positive_user_count": max(1, int(min_item_train_positive_user_count)),
    }
    thresholds = screening_source.get("thresholds") if isinstance(screening_source.get("thresholds"), dict) else {}
    reasons = []
    observed_thresholds: dict[str, int] = {}
    if not thresholds:
        if require_contract_thresholds:
            reasons.append("missing_screening_thresholds")
    else:
        try:
            observed_thresholds = {key: int(thresholds.get(key, -1)) for key in expected_thresholds}
        except (TypeError, ValueError):
            reasons.append("invalid_screening_threshold_type")
        if observed_thresholds and observed_thresholds != expected_thresholds:
            reasons.append("screening_threshold_mismatch")
    return {
        "thresholds": observed_thresholds or expected_thresholds,
        "expected_thresholds": expected_thresholds,
        "raw_thresholds": thresholds,
        "observed_thresholds": observed_thresholds,
        "reasons": reasons,
    }


def _apply_feature_contract_screening(candidates_by_user: dict[str, list[Any]], feature_contract: dict[str, Any]) -> tuple[dict[str, list[Any]], dict[str, Any]]:
    if not feature_contract:
        candidate_items = {str(candidate.item_id) for candidates in candidates_by_user.values() for candidate in candidates}
        return candidates_by_user, {
            "schema_version": "pool500_eval_screening_audit_v1",
            "screening_policy": "none",
            "contract_enabled": False,
            "candidate_users_before": len(candidates_by_user),
            "candidate_rows_before": sum(len(candidates) for candidates in candidates_by_user.values()),
            "candidate_users_after": len(candidates_by_user),
            "candidate_rows_after": sum(len(candidates) for candidates in candidates_by_user.values()),
            "eligible_users": sorted(candidates_by_user),
            "eligible_items": sorted(candidate_items),
        }
    eligible_users = set(str(value) for value in feature_contract.get("eligible_users") or [])
    eligible_items = set(str(value) for value in feature_contract.get("eligible_items") or [])
    filtered: dict[str, list[Any]] = {}
    before_rows = 0
    after_rows = 0
    for user_id, candidates in candidates_by_user.items():
        before_rows += len(candidates)
        if str(user_id) not in eligible_users:
            continue
        kept = [candidate for candidate in candidates if str(candidate.item_id) in eligible_items]
        if kept:
            filtered[user_id] = kept
            after_rows += len(kept)
    return filtered, {
        "schema_version": "pool500_eval_screening_audit_v1",
        "screening_policy": feature_contract.get("screening_policy", "none"),
        "contract_enabled": True,
        "candidate_users_before": len(candidates_by_user),
        "candidate_rows_before": before_rows,
        "candidate_users_after": len(filtered),
        "candidate_rows_after": after_rows,
        "eligible_users": sorted(eligible_users),
        "eligible_items": sorted(eligible_items),
    }


def _read_candidate_rows(
    path: Path,
    *,
    max_candidate_rows: int | None,
    max_candidate_users: int | None,
    user_filter: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = []
    seen_users = set()
    raw_rows_seen = 0
    filtered_by_user = 0
    for index, row in enumerate(iter_jsonl(path), start=1):
        raw_rows_seen = index
        if max_candidate_rows is not None and index > max(0, int(max_candidate_rows)):
            raw_rows_seen = index - 1
            break
        user_id = str(row.get("user_id") or "")
        if user_filter is not None and user_id not in user_filter:
            filtered_by_user += 1
            continue
        if max_candidate_users is not None and user_id and user_id not in seen_users and len(seen_users) >= max(0, int(max_candidate_users)):
            break
        if user_id:
            seen_users.add(user_id)
        rows.append(row)
    return rows, {
        "candidate_rows_read": len(rows),
        "raw_candidate_rows_seen": raw_rows_seen,
        "candidate_rows_filtered_by_user": filtered_by_user,
        "candidate_users_read": len(seen_users),
        "candidate_user_filter_enabled": user_filter is not None,
        "candidate_user_filter_size": len(user_filter) if user_filter is not None else None,
    }


def _read_user_allowlist(path: Path) -> set[str]:
    users: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value:
            continue
        if value.startswith("{"):
            payload = json.loads(value)
            value = str(payload.get("user_id") or "").strip()
        if value:
            users.add(value)
    return users


def _read_eval_label_rows(
    path: Path,
    *,
    eval_user_allowlist: set[str] | None,
    eval_split: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    filtered = []
    raw_rows = 0
    split_filtered = 0
    user_filtered = 0
    for row in iter_jsonl(path):
        raw_rows += 1
        if eval_split and str(row.get("split") or row.get("label_split") or "").lower() != eval_split.lower():
            split_filtered += 1
            continue
        user_id = str(row.get("user_id") or "")
        if eval_user_allowlist is not None and user_id not in eval_user_allowlist:
            user_filtered += 1
            continue
        filtered.append(row)
    return filtered, {
        "raw_eval_label_rows": raw_rows,
        "eval_label_rows_after_filter": len(filtered),
        "eval_label_rows_filtered_by_split": split_filtered,
        "eval_label_rows_filtered_by_allowlist": user_filtered,
        "eval_user_allowlist_enabled": eval_user_allowlist is not None,
        "eval_user_allowlist_size": len(eval_user_allowlist) if eval_user_allowlist is not None else None,
        "eval_split_filter": eval_split,
    }


def _positive_user_ids(label_rows: list[dict[str, Any]]) -> set[str]:
    return {str(row.get("user_id") or "") for row in label_rows if _positive(row) and row.get("user_id")}


def _build_eval_rows(
    candidates_by_user: dict[str, list[Any]],
    label_by_pair: dict[tuple[str, str], dict[str, Any]],
    *,
    candidate_artifact_path: Path,
    candidate_artifact_sha256: str,
    eval_label_source_path: Path,
    eval_label_source_sha256: str,
    full_label_denominator: int,
    in_candidate_denominator: int,
    eval_split: str | None,
    history_feature_context: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for user_id, candidates in candidates_by_user.items():
        for candidate in candidates:
            pair = (str(user_id), str(candidate.item_id))
            label_payload = label_by_pair.get(pair)
            label = 1 if label_payload else 0
            feature_payload = _eval_history_feature_payload(str(user_id), str(candidate.item_id), history_feature_context)
            rows.append(
                {
                    "schema_version": ROW_SCHEMA_VERSION,
                    "user_id": str(user_id),
                    "item_id": str(candidate.item_id),
                    "split": str((label_payload or {}).get("split") or eval_split or "eval"),
                    "candidate_rank": _candidate_rank(candidate),
                    "candidate_sources": list(candidate.sources),
                    "candidate_artifact_path": str(candidate_artifact_path),
                    "candidate_artifact_sha256": candidate_artifact_sha256,
                    "eval_label_source_path": str(eval_label_source_path),
                    "eval_label_source_sha256": eval_label_source_sha256,
                    "label": label,
                    "label_used_for": "evaluation_only",
                    "label_event_time": (label_payload or {}).get("label_event_time") if label else None,
                    "in_candidate_denominator": in_candidate_denominator,
                    "full_label_denominator": full_label_denominator,
                }
                | feature_payload
            )
    return rows


def _history_feature_context(
    train_interactions_path: Path | None,
    *,
    eval_feature_cutoff_time: str | None,
    history_feature_version: str,
    fast_source_fingerprint: bool,
    feature_contract: dict[str, Any] | None = None,
    requested_screening_policy: str = "none",
    min_user_train_positive_count: int = 2,
    min_item_train_positive_user_count: int = 2,
) -> dict[str, Any]:
    if train_interactions_path is None:
        return {
            "enabled": False,
            "status": PASS,
            "history_feature_version": history_feature_version,
            "feature_names": [],
            "valid_test_labels_used_for_features": False,
            "eval_label_event_time_used_for_features": False,
        }
    train_rows = list(iter_jsonl(train_interactions_path))
    train_split_gate = _train_interactions_split_gate(train_rows)
    raw_positive_events = _positive_events(train_rows) if train_split_gate["status"] == PASS else []
    screening_source = feature_contract or {}
    screening_policy = str(screening_source.get("screening_policy") or requested_screening_policy or "none")
    threshold_context = _screening_threshold_context(
        screening_source,
        min_user_train_positive_count=min_user_train_positive_count,
        min_item_train_positive_user_count=min_item_train_positive_user_count,
        require_contract_thresholds=bool(feature_contract),
    )
    screening_plan = build_screening_plan(
        raw_positive_events,
        screening_policy=screening_policy,
        min_user_train_positive_count=threshold_context["thresholds"]["min_user_train_positive_count"],
        min_item_train_positive_user_count=threshold_context["thresholds"]["min_item_train_positive_user_count"],
    )
    positive_events = screen_positive_events(raw_positive_events, screening_plan)
    parsed_times = [_parse_time(event.get("event_time")) for event in positive_events]
    parsed_times = [value for value in parsed_times if value is not None]
    explicit_cutoff = _parse_time(eval_feature_cutoff_time) if eval_feature_cutoff_time else None
    cutoff = explicit_cutoff or ((max(parsed_times) + timedelta(microseconds=1)) if parsed_times else None)
    cutoff_source = "explicit_eval_feature_cutoff_time" if explicit_cutoff else "derived_from_train_max_event_time_plus_epsilon"
    train_events_at_or_after_cutoff = []
    if cutoff is not None:
        for index, event in enumerate(positive_events, start=1):
            event_time = _parse_time(event.get("event_time"))
            if event_time is not None and event_time >= cutoff and len(train_events_at_or_after_cutoff) < 20:
                train_events_at_or_after_cutoff.append({"event_index": index, "user_id": event.get("user_id"), "item_id": event.get("item_id"), "event_time": event.get("event_time")})
    return {
        "enabled": True,
        "status": PASS if train_split_gate["status"] == PASS and cutoff is not None and not train_events_at_or_after_cutoff and not threshold_context["reasons"] else STOP,
        "threshold_gate_reasons": threshold_context["reasons"],
        "train_split_gate": train_split_gate,
        "train_interactions_path": str(train_interactions_path),
        "train_interactions_fingerprint": _source_fingerprint(train_interactions_path, fast=fast_source_fingerprint),
        "train_rows_read": len(train_rows),
        "train_positive_events": len(positive_events),
        "raw_train_positive_events": len(raw_positive_events),
        "screening_audit": screening_plan,
        "eval_feature_cutoff_time": _format_time(cutoff),
        "eval_feature_cutoff_time_source": cutoff_source,
        "history_feature_version": history_feature_version,
        "feature_names": TRAIN_HISTORY_FEATURE_NAMES,
        "feature_index": _train_history_feature_index(positive_events),
        "valid_test_labels_used_for_features": train_split_gate.get("valid_test_labels_used_for_features", False),
        "eval_label_event_time_used_for_features": False,
        "train_events_at_or_after_cutoff": train_events_at_or_after_cutoff,
    }


def _train_interactions_split_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    split_counts = Counter(str(row.get("split") or row.get("label_split") or "unknown").lower() for row in rows)
    rejected = sorted(split for split in split_counts if split not in {"train", "train_dev", "train_final", "unknown", ""})
    return {
        "schema_version": "pool500_eval_history_train_split_gate_v1",
        "status": STOP if rejected else PASS,
        "split_counts": dict(sorted(split_counts.items())),
        "rejected_splits": rejected,
        "valid_test_labels_used_for_features": bool(rejected),
        "allowed_training_splits": ["train", "train_dev", "train_final", "unknown"],
    }


def _eval_history_feature_payload(user_id: str, item_id: str, history_feature_context: dict[str, Any]) -> dict[str, Any]:
    if not history_feature_context.get("enabled"):
        return {}
    cutoff_time = history_feature_context.get("eval_feature_cutoff_time")
    return {
        "feature_version": history_feature_context.get("history_feature_version"),
        "feature_cutoff_time": cutoff_time,
        "feature_cutoff_time_source": history_feature_context.get("eval_feature_cutoff_time_source"),
        "features": _train_history_features(user_id, item_id, cutoff_time, history_feature_context["feature_index"]),
    }


def _history_feature_audit(history_feature_context: dict[str, Any], rows: list[dict[str, Any]], eval_label_rows: list[dict[str, Any]]) -> dict[str, Any]:
    observed_feature_names = sorted({str(name) for row in rows for name in (row.get("features") or {}) if isinstance(row.get("features"), dict)})
    missing_expected = sorted(set(TRAIN_HISTORY_FEATURE_NAMES) - set(observed_feature_names)) if history_feature_context.get("enabled") and rows else []
    empty_feature_rows = [index for index, row in enumerate(rows) if history_feature_context.get("enabled") and not row.get("features")]
    non_numeric_feature_rows = []
    missing_positive_label_event_time_rows = []
    unparseable_positive_label_event_time_rows = []
    feature_cutoff_after_label_event_time_rows = []
    if history_feature_context.get("enabled"):
        for index, label_row in enumerate(eval_label_rows, start=1):
            if not _positive(label_row):
                continue
            user_id = str(label_row.get("user_id") or "")
            item_id = str(label_row.get("parent_asin") or label_row.get("item_id") or "")
            label_event_time = _label_event_time(label_row)
            if not label_event_time:
                missing_positive_label_event_time_rows.append({"label_row_index": index, "user_id": user_id, "item_id": item_id})
            elif _parse_time(label_event_time) is None:
                unparseable_positive_label_event_time_rows.append({"label_row_index": index, "user_id": user_id, "item_id": item_id, "label_event_time": label_event_time})
    for index, row in enumerate(rows):
        features = row.get("features") if isinstance(row.get("features"), dict) else {}
        for name, value in features.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                non_numeric_feature_rows.append({"row_index": index, "feature_name": str(name)})
        if history_feature_context.get("enabled") and row.get("label") == 1:
            feature_cutoff = _parse_time(row.get("feature_cutoff_time"))
            label_time = _parse_time(row.get("label_event_time"))
            if feature_cutoff is not None and label_time is not None and feature_cutoff > label_time:
                feature_cutoff_after_label_event_time_rows.append({"row_index": index, "user_id": row.get("user_id"), "item_id": row.get("item_id"), "feature_cutoff_time": row.get("feature_cutoff_time"), "label_event_time": row.get("label_event_time")})
    context_status = history_feature_context.get("status", PASS)
    status = PASS if context_status == PASS and not missing_expected and not empty_feature_rows and not non_numeric_feature_rows and not missing_positive_label_event_time_rows and not unparseable_positive_label_event_time_rows and not feature_cutoff_after_label_event_time_rows else STOP
    public_context = {key: value for key, value in history_feature_context.items() if key != "feature_index"}
    return {
        "schema_version": "pool500_eval_train_history_feature_audit_v1",
        "status": status,
        "enabled": bool(history_feature_context.get("enabled")),
        "context": public_context,
        "feature_generation_scope": "train_only_interactions" if history_feature_context.get("enabled") else "not_enabled",
        "expected_feature_names": TRAIN_HISTORY_FEATURE_NAMES if history_feature_context.get("enabled") else [],
        "observed_feature_names": observed_feature_names,
        "missing_expected_features": missing_expected,
        "empty_feature_rows": empty_feature_rows[:20],
        "non_numeric_feature_rows": non_numeric_feature_rows[:20],
        "missing_positive_label_event_time_rows": missing_positive_label_event_time_rows[:20],
        "unparseable_positive_label_event_time_rows": unparseable_positive_label_event_time_rows[:20],
        "feature_cutoff_after_label_event_time_rows": feature_cutoff_after_label_event_time_rows[:20],
        "valid_test_labels_used_for_features": bool(history_feature_context.get("valid_test_labels_used_for_features", False)),
        "eval_label_event_time_used_for_features": False,
    }


def _positive_label_by_pair(label_rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    labels: dict[tuple[str, str], dict[str, Any]] = {}
    for row in label_rows:
        if not _positive(row):
            continue
        user_id = str(row.get("user_id") or "")
        item_id = str(row.get("parent_asin") or row.get("item_id") or "")
        if not user_id or not item_id:
            continue
        labels[(user_id, item_id)] = {"split": str(row.get("split") or row.get("label_split") or "eval"), "label_event_time": _label_event_time(row)}
    return labels


def _positive(row: dict[str, Any]) -> bool:
    for field in LABEL_FIELDS:
        if field in row:
            value = row.get(field)
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "positive"}
            return bool(value)
    return False


def _label_event_time(row: dict[str, Any]) -> Any:
    for field in TIME_FIELDS:
        value = row.get(field)
        if value not in (None, ""):
            return value
    return None


def _candidate_rank(candidate: Any) -> int:
    lineage = candidate.metadata.get(POOL500_LINEAGE_KEY, []) if isinstance(candidate.metadata, dict) else []
    ranks = [int(entry["rank"]) for entry in lineage if isinstance(entry, dict) and str(entry.get("rank", "")).isdigit()]
    return min(ranks, default=1)


def _oracle_injection_gate(
    candidate_rows: list[dict[str, Any]],
    *,
    pool500_candidates_path: Path,
    eval_label_artifact_path: Path,
    candidate_artifact_sha256: str,
    eval_label_source_sha256: str,
) -> dict[str, Any]:
    forbidden_rows = []
    for index, row in enumerate(candidate_rows, start=1):
        present = sorted(CANDIDATE_FORBIDDEN_LABEL_FIELDS & set(row))
        if present:
            forbidden_rows.append({"row_index": index, "forbidden_label_fields": present})
    same_source = pool500_candidates_path == eval_label_artifact_path or candidate_artifact_sha256 == eval_label_source_sha256
    reasons = []
    if same_source:
        reasons.append("candidate_artifact_matches_eval_label_source")
    if forbidden_rows:
        reasons.append("candidate_rows_contain_label_fields")
    return {
        "schema_version": "pool500_frozen_eval_oracle_injection_gate_v1",
        "status": STOP if reasons else PASS,
        "candidate_generation_reads_eval_labels": False,
        "candidate_label_injection_allowed": False,
        "candidate_artifact_path": str(pool500_candidates_path),
        "eval_label_source_path": str(eval_label_artifact_path),
        "candidate_artifact_sha256": candidate_artifact_sha256,
        "eval_label_source_sha256": eval_label_source_sha256,
        "same_source": same_source,
        "candidate_rows_with_forbidden_label_fields": forbidden_rows,
        "reasons": reasons,
    }


def _adapter_summary(adapter_result: dict[str, Any], candidates_by_user: dict[str, list[Any]]) -> dict[str, Any]:
    candidate_counts = [len(candidates) for candidates in candidates_by_user.values()]
    return {
        "schema_version": adapter_result.get("schema_version") if isinstance(adapter_result, dict) else None,
        "status": adapter_result.get("status") if isinstance(adapter_result, dict) else STOP,
        "users": len(candidates_by_user),
        "candidate_count_min": min(candidate_counts, default=0),
        "candidate_count_max": max(candidate_counts, default=0),
        "candidate_count_avg": round(sum(candidate_counts) / len(candidate_counts), 6) if candidate_counts else 0.0,
        "blocker_count": len(adapter_result.get("blockers", [])) if isinstance(adapter_result, dict) else 0,
        "diagnostic_count": len(adapter_result.get("diagnostics", [])) if isinstance(adapter_result, dict) else 0,
    }


def _adapter_diagnostic_summary(adapter_result: dict[str, Any], candidate_rows: list[dict[str, Any]], *, sample_limit: int = 20) -> dict[str, Any]:
    diagnostics = adapter_result.get("diagnostics", []) if isinstance(adapter_result, dict) else []
    diagnostic_codes = Counter(str(diagnostic.get("code") or "UNKNOWN") for diagnostic in diagnostics if isinstance(diagnostic, dict))
    fallback_reason_counts: Counter[str] = Counter()
    fallback_source_counts: Counter[str] = Counter()
    fallback_samples = []
    extra_source_counts: Counter[str] = Counter()
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict):
            continue
        evidence = diagnostic.get("evidence") if isinstance(diagnostic.get("evidence"), dict) else {}
        code = str(diagnostic.get("code") or "")
        source = str(evidence.get("source") or "")
        if source in POOL500_DIAGNOSTIC_EXTRA_SOURCES:
            extra_source_counts[source] += 1
        if code != "POOL500_SCORE_FALLBACK_USED":
            continue
        reason = str(evidence.get("reason") or "unknown")
        fallback_reason_counts[reason] += 1
        if source:
            fallback_source_counts[source] += 1
        if len(fallback_samples) < sample_limit:
            sample = dict(evidence)
            row_index = sample.get("row_index")
            if isinstance(row_index, int) and 1 <= row_index <= len(candidate_rows):
                row = candidate_rows[row_index - 1]
                sample["row_missing_score"] = "score" not in row
                sample["row_has_source_scores"] = isinstance(row.get("source_scores"), dict) or isinstance((row.get("metadata") or {}).get("source_scores") if isinstance(row.get("metadata"), dict) else None, dict)
            fallback_samples.append(sample)
    return {
        "schema_version": "pool500_adapter_diagnostic_summary_v1",
        "diagnostic_codes": dict(sorted(diagnostic_codes.items())),
        "score_fallback_counts_by_reason": dict(sorted(fallback_reason_counts.items())),
        "score_fallback_counts_by_source": dict(sorted(fallback_source_counts.items())),
        "score_fallback_sample_rows": fallback_samples,
        "diagnostic_extra_source_counts": dict(sorted(extra_source_counts.items())),
        "sample_limit": sample_limit,
    }


def _alignment_audit(
    eval_filter_audit: dict[str, Any],
    candidate_read_audit: dict[str, Any],
    candidates_by_user: dict[str, list[Any]],
    label_by_pair: dict[tuple[str, str], dict[str, Any]],
    *,
    eval_user_allowlist_path: Path | None,
    candidate_users_from_eval_labels: bool,
) -> dict[str, Any]:
    candidate_users = set(candidates_by_user)
    label_users = {user_id for user_id, _ in label_by_pair}
    overlap_users = candidate_users & label_users
    candidate_pairs = {(str(user_id), str(candidate.item_id)) for user_id, candidates in candidates_by_user.items() for candidate in candidates}
    overlap_pairs = set(label_by_pair) & candidate_pairs
    return {
        "schema_version": "pool500_frozen_candidate_eval_alignment_audit_v1",
        "eval_user_allowlist_path": str(eval_user_allowlist_path) if eval_user_allowlist_path else None,
        "eval_user_allowlist_enabled": eval_filter_audit["eval_user_allowlist_enabled"],
        "candidate_users_from_eval_labels": candidate_users_from_eval_labels,
        "candidate_user_filter_enabled": candidate_read_audit["candidate_user_filter_enabled"],
        "raw_eval_label_rows": eval_filter_audit["raw_eval_label_rows"],
        "eval_label_rows_after_filter": eval_filter_audit["eval_label_rows_after_filter"],
        "eval_label_rows_filtered_by_split": eval_filter_audit["eval_label_rows_filtered_by_split"],
        "eval_label_rows_filtered_by_allowlist": eval_filter_audit["eval_label_rows_filtered_by_allowlist"],
        "candidate_rows_read": candidate_read_audit["candidate_rows_read"],
        "raw_candidate_rows_seen": candidate_read_audit["raw_candidate_rows_seen"],
        "candidate_rows_filtered_by_user": candidate_read_audit["candidate_rows_filtered_by_user"],
        "candidate_users": len(candidate_users),
        "eval_positive_users": len(label_users),
        "overlap_users": len(overlap_users),
        "eval_positive_pairs": len(label_by_pair),
        "overlap_positive_pairs": len(overlap_pairs),
        "label_source_used_for_candidate_generation": False,
        "label_source_used_for_candidate_filtering_only": candidate_users_from_eval_labels,
        "label_injection_allowed": False,
        "time_window_boundary": "2y1m3m labels are filtered only by explicit split/user allowlist; candidate generation remains frozen",
    }


def _row_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    positive_rows = [row for row in rows if row.get("label") == 1]
    return {
        "rows": len(rows),
        "users": len({row["user_id"] for row in rows}),
        "positive_rows": len(positive_rows),
        "positive_users": len({row["user_id"] for row in positive_rows}),
        "positive_rate": round(len(positive_rows) / len(rows), 8) if rows else 0.0,
    }


def _split_counts(label_rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(row.get("split") or row.get("label_split") or "unknown").lower() for row in label_rows)
    return dict(sorted(counts.items()))


def _recall_window_handoff(coverage_gate: dict[str, Any]) -> dict[str, Any]:
    return {
        "required": coverage_gate["status"] != PASS,
        "target": "recall-window",
        "reason": "frozen pool500 candidate coverage below hard gate" if coverage_gate["status"] != PASS else "not_required",
        "evidence": {
            "in_candidate_positive_users": coverage_gate["in_candidate_positive_users"],
            "user_gate_threshold": coverage_gate["user_gate_threshold"],
            "in_candidate_positives": coverage_gate["in_candidate_positives"],
            "positive_gate_threshold": coverage_gate["positive_gate_threshold"],
            "full_label_denominator": coverage_gate["full_label_denominator"],
        },
    }


def _source_fingerprint(path: Path, *, fast: bool) -> str:
    if not fast:
        return _sha256_file(path)
    stat = path.stat()
    payload = {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
