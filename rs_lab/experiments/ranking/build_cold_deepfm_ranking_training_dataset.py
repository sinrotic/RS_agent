from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, write_json, write_jsonl
from rs_core.common.runtime import enforce_project_venv

PASS = "PASS"
STOP = "STOP"
SCHEMA_VERSION = "cold_deepfm_ranking_training_dataset_v1"
ROW_SCHEMA_VERSION = "cold_deepfm_ranking_training_row_v1"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "ranking" / "datasets" / "cold_deepfm_ranking_training"
DEFAULT_2Y1M3M_DATASET_DIR = ROOT / "data" / "processed" / "amazon_2023_recall_recent_2y_1m_3m"
DEFAULT_2Y1M3M_TRAIN_INTERACTIONS = DEFAULT_2Y1M3M_DATASET_DIR / "canonical_interactions.train.jsonl"
DEFAULT_2Y1M3M_VALID_INTERACTIONS = DEFAULT_2Y1M3M_DATASET_DIR / "canonical_interactions.valid.jsonl"
DEFAULT_2Y1M3M_TEST_INTERACTIONS = DEFAULT_2Y1M3M_DATASET_DIR / "canonical_interactions.test.jsonl"
ALLOWED_TRAINING_SPLITS = {"train", "train_dev", "train_final", "unknown", ""}
FORBIDDEN_TRAINING_SPLITS = {"valid", "validation", "dev_eval", "test", "test_final", "holdout"}
LABEL_FIELDS = ("label_binary", "label", "clicked", "purchased", "is_hit")
ITEM_FIELDS = ("item_id", "parent_asin", "asin")
TIME_FIELDS = ("event_time", "timestamp", "unix_timestamp", "review_time", "label_event_time")
REQUIRED_ROW_FIELDS = [
    "user_id",
    "item_id",
    "label",
    "label_semantics",
    "split",
    "event_time",
    "label_event_time",
    "negative_sampling_cutoff_time",
    "feature_cutoff_time",
    "event_time_source",
    "label_event_time_source",
    "negative_sampling_strategy",
    "negative_sampling_seed",
    "item_universe_source",
    "feature_version",
    "source_manifest_hash",
    "features",
]
TRAIN_HISTORY_FEATURE_NAMES = [
    "score_item_train_positive_count_log1p",
    "score_item_train_positive_user_count_log1p",
    "score_user_train_positive_count_log1p",
    "score_user_train_distinct_item_count_log1p",
    "has_item_train_history",
    "has_user_train_history",
]
FORBIDDEN_FEATURE_NAME_TOKENS = ("label", "target", "holdout", "future", "candidate_rank", "source_")
SCREENING_POLICIES = {"none", "user_first", "item_first"}
DEFAULT_MIN_USER_TRAIN_POSITIVE_COUNT = 2
DEFAULT_MIN_ITEM_TRAIN_POSITIVE_USER_COUNT = 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build positive-rich COLD/DeepFM ranking training rows from train-only interactions.")
    parser.add_argument("--train-interactions", default=str(DEFAULT_2Y1M3M_TRAIN_INTERACTIONS), help="Train-only interactions path; defaults to 2y1m3m train split.")
    parser.add_argument("--valid-interactions", default=str(DEFAULT_2Y1M3M_VALID_INTERACTIONS), help="Evaluation-only valid split path recorded for audit; never used for training.")
    parser.add_argument("--test-interactions", default=str(DEFAULT_2Y1M3M_TEST_INTERACTIONS), help="Evaluation-only test split path recorded for audit; never used for training.")
    parser.add_argument("--dataset-id", default="amazon_2023_recall_recent_2y_1m_3m")
    parser.add_argument("--dataset-window", default="2y1m3m")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--item-universe", default="")
    parser.add_argument("--negatives-per-positive", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260602)
    parser.add_argument("--split", default="train_dev", choices=["train_dev", "train_final"])
    parser.add_argument("--run-scope", default="smoke", choices=["smoke", "formal"])
    parser.add_argument("--feature-version", default="cold_deepfm_training_features_v2")
    parser.add_argument("--screening-policy", default="none", choices=sorted(SCREENING_POLICIES))
    parser.add_argument("--min-user-train-positive-count", type=int, default=DEFAULT_MIN_USER_TRAIN_POSITIVE_COUNT)
    parser.add_argument("--min-item-train-positive-user-count", type=int, default=DEFAULT_MIN_ITEM_TRAIN_POSITIVE_USER_COUNT)
    parser.add_argument("--threshold-override", action="store_true")
    parser.add_argument("--override-reason", default="")
    parser.add_argument("--approved-scope", default="smoke", choices=["smoke", "formal"])
    parser.add_argument("--limit-users", type=int, default=None)
    parser.add_argument("--max-rows", type=int, default=None, help="Bounded preflight read limit for large train-only files.")
    parser.add_argument("--fast-source-fingerprint", action="store_true", help="Use path/size/mtime fingerprints instead of full-file sha256 for large-file preflight.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_cold_deepfm_ranking_training_dataset_from_files(
        train_interactions_path=Path(args.train_interactions),
        output_dir=Path(args.output_dir),
        item_universe_path=Path(args.item_universe) if args.item_universe else None,
        valid_interactions_path=Path(args.valid_interactions) if args.valid_interactions else None,
        test_interactions_path=Path(args.test_interactions) if args.test_interactions else None,
        dataset_id=args.dataset_id,
        dataset_window=args.dataset_window,
        negatives_per_positive=args.negatives_per_positive,
        seed=args.seed,
        split=args.split,
        run_scope=args.run_scope,
        feature_version=args.feature_version,
        screening_policy=args.screening_policy,
        min_user_train_positive_count=args.min_user_train_positive_count,
        min_item_train_positive_user_count=args.min_item_train_positive_user_count,
        threshold_override=args.threshold_override,
        override_reason=args.override_reason,
        approved_scope=args.approved_scope,
        limit_users=args.limit_users,
        max_rows=args.max_rows,
        fast_source_fingerprint=args.fast_source_fingerprint,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps(manifest["output_paths"], ensure_ascii=False, indent=2))


def build_cold_deepfm_ranking_training_dataset_from_files(
    *,
    train_interactions_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    item_universe_path: Path | None = None,
    valid_interactions_path: Path | None = None,
    test_interactions_path: Path | None = None,
    dataset_id: str = "amazon_2023_recall_recent_2y_1m_3m",
    dataset_window: str = "2y1m3m",
    negatives_per_positive: int = 2,
    seed: int = 20260602,
    split: str = "train_dev",
    run_scope: str = "smoke",
    feature_version: str = "cold_deepfm_training_features_v2",
    screening_policy: str = "none",
    min_user_train_positive_count: int = DEFAULT_MIN_USER_TRAIN_POSITIVE_COUNT,
    min_item_train_positive_user_count: int = DEFAULT_MIN_ITEM_TRAIN_POSITIVE_USER_COUNT,
    threshold_override: bool = False,
    override_reason: str = "",
    approved_scope: str = "smoke",
    limit_users: int | None = None,
    max_rows: int | None = None,
    fast_source_fingerprint: bool = False,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    train_interactions_path = train_interactions_path.resolve()
    item_universe_path = item_universe_path.resolve() if item_universe_path else None
    valid_interactions_path = valid_interactions_path.resolve() if valid_interactions_path else None
    test_interactions_path = test_interactions_path.resolve() if test_interactions_path else None
    output_dir = output_dir.resolve()
    output_paths = _output_paths(output_dir)
    _precheck(train_interactions_path, item_universe_path, output_paths, overwrite)

    source_rows = _read_source_rows(train_interactions_path, max_rows=max_rows)
    dataset_source_audit = _dataset_source_audit(
        train_interactions_path=train_interactions_path,
        valid_interactions_path=valid_interactions_path,
        test_interactions_path=test_interactions_path,
        dataset_id=dataset_id,
        dataset_window=dataset_window,
        train_rows_read=len(source_rows),
    )
    if limit_users is not None:
        allowed_users = []
        seen_users = set()
        for row in source_rows:
            user_id = _string(row.get("user_id"))
            if user_id and user_id not in seen_users:
                allowed_users.append(user_id)
                seen_users.add(user_id)
            if len(allowed_users) >= max(0, int(limit_users)):
                break
        allowed_user_set = set(allowed_users)
        source_rows = [row for row in source_rows if _string(row.get("user_id")) in allowed_user_set]

    source_manifest_hash = _source_manifest_hash(
        train_interactions_path,
        item_universe_path,
        max_rows=max_rows,
        fast_source_fingerprint=fast_source_fingerprint,
    )
    split_gate = _training_split_gate(source_rows)
    raw_positive_events = _positive_events(source_rows)
    screening_audit = build_screening_plan(
        raw_positive_events,
        screening_policy=screening_policy,
        min_user_train_positive_count=min_user_train_positive_count,
        min_item_train_positive_user_count=min_item_train_positive_user_count,
    )
    positive_events = screen_positive_events(raw_positive_events, screening_audit)
    item_universe, item_universe_source, item_universe_rows = _item_universe(source_rows, item_universe_path)
    eligible_item_set = set(screening_audit["eligible_items"])
    if screening_audit["screening_policy"] != "none":
        item_universe = sorted(item_id for item_id in item_universe if item_id in eligible_item_set)
    train_history_feature_index = _train_history_feature_index(positive_events)
    feature_contract = _feature_contract(
        feature_names=TRAIN_HISTORY_FEATURE_NAMES,
        feature_version=feature_version,
        screening_audit=screening_audit,
        source_manifest_hash=source_manifest_hash,
    )
    feature_contract_digest = feature_contract_hash(feature_contract)
    feature_contract["feature_contract_hash"] = feature_contract_digest
    dataset_rows = [] if split_gate["status"] != PASS else _build_rows(
        positive_events=positive_events,
        item_universe=item_universe,
        split=split,
        negatives_per_positive=max(0, int(negatives_per_positive)),
        seed=int(seed),
        item_universe_source=item_universe_source,
        feature_version=feature_version,
        source_manifest_hash=source_manifest_hash,
        train_history_feature_index=train_history_feature_index,
    )

    schema_gate = _schema_gate(dataset_rows)
    feature_gate = _feature_gate(dataset_rows)
    positive_rich_gate = _positive_rich_gate(
        dataset_rows,
        run_scope=run_scope,
        threshold_override=threshold_override,
        override_reason=override_reason,
        approved_scope=approved_scope,
    )
    weak_negative_gate = _weak_negative_gate(
        dataset_rows,
        source_rows=source_rows,
        item_universe_source=item_universe_source,
        item_universe_rows=item_universe_rows,
        negatives_per_positive=max(0, int(negatives_per_positive)),
        seed=int(seed),
    )
    leakage_gate = _row_level_time_leakage_gate(dataset_rows, train_split_gate=split_gate)
    blockers = []
    for code, gate in (
        ("TRAINING_SPLIT_NOT_TRAIN_ONLY", split_gate),
        ("SCHEMA_GATE_NOT_PASS", schema_gate),
        ("FEATURE_GATE_NOT_PASS", feature_gate),
        ("POSITIVE_RICH_GATE_NOT_PASS", positive_rich_gate),
        ("WEAK_NEGATIVE_GATE_NOT_PASS", weak_negative_gate),
        ("ROW_LEVEL_TIME_LEAKAGE_GATE_NOT_PASS", leakage_gate),
    ):
        if gate.get("status") != PASS:
            blockers.append({"code": code, "severity": "blocker", "evidence": gate})

    stats = _dataset_stats(dataset_rows)
    gate_report = {
        "schema_version": "cold_deepfm_ranking_training_gate_report_v1",
        "status": PASS if not blockers else STOP,
        "schema_gate": schema_gate,
        "feature_gate": feature_gate,
        "positive_rich_training_gate": positive_rich_gate,
        "weak_negative_gate": weak_negative_gate,
        "row_level_time_leakage_gate": leakage_gate,
        "training_split_gate": split_gate,
        "screening_audit": screening_audit,
        "feature_contract_hash": feature_contract_digest,
        "blockers": blockers,
    }
    report = {
        "schema_version": "cold_deepfm_ranking_training_report_v1",
        "status": gate_report["status"],
        "rows": stats["rows"],
        "positive_rows": stats["positive_rows"],
        "negative_rows": stats["negative_rows"],
        "positive_users": stats["positive_users"],
        "positive_ratio": stats["positive_ratio"],
        "sampling_source": "train_only_interactions",
        "positive_negative_ratio": stats["positive_negative_ratio"],
        "negative_sampling_seed": int(seed),
        "item_universe": {"source": item_universe_source, "items": len(item_universe)},
        "feature_version": feature_version,
        "feature_policy": _feature_policy_summary(feature_gate),
        "cold_bucket_summary": _cold_bucket_summary(dataset_rows),
        "time_window": _time_window(source_rows),
        "exclusion_rules": ["exclude_user_observed_positive_items", "sample_without_full_item_universe_shuffle", "forbid_valid_test_holdout_training_rows"],
        "label_semantics": {"positive": "observed_positive", "negative": "weak_negative"},
        "source_manifest_hash": source_manifest_hash,
        "screening_policy": screening_audit["screening_policy"],
        "screening_order": screening_audit["order"],
        "screening_thresholds": screening_audit["thresholds"],
        "screening_audit": screening_audit,
        "eligible_users": screening_audit["eligible_users"],
        "eligible_items": screening_audit["eligible_items"],
        "feature_contract_hash": feature_contract_digest,
        "dataset_source_audit": dataset_source_audit,
        "weak_negative_disclaimer": "No exposure log is available; weak negatives are unobserved-as-positive proxy rows and must not be interpreted as true CTR or online click negatives.",
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": gate_report["status"],
        "generated_at": datetime.now(UTC).isoformat(),
        "output_dir": str(output_dir),
        "output_paths": {name: str(path) for name, path in output_paths.items()},
        "train_interactions_path": str(train_interactions_path),
        "valid_interactions_path": str(valid_interactions_path) if valid_interactions_path else "",
        "test_interactions_path": str(test_interactions_path) if test_interactions_path else "",
        "item_universe_path": str(item_universe_path) if item_universe_path else "",
        "dataset_id": dataset_id,
        "dataset_window": dataset_window,
        "dataset_source_audit": dataset_source_audit,
        "run_scope": run_scope,
        "split": split,
        "source_manifest_hash": source_manifest_hash,
        "screening_policy": screening_audit["screening_policy"],
        "screening_order": screening_audit["order"],
        "screening_thresholds": screening_audit["thresholds"],
        "screening_audit": screening_audit,
        "eligible_users": screening_audit["eligible_users"],
        "eligible_items": screening_audit["eligible_items"],
        "feature_contract_hash": feature_contract_digest,
        "max_rows": max_rows,
        "fast_source_fingerprint": bool(fast_source_fingerprint),
        "stats": stats,
        "gate_report": gate_report,
        "report": report,
        "offline_training_only": True,
        "uses_valid_test_holdout_for_training": False,
        "uses_valid_test_holdout_for_negative_sampling": False,
        "true_ctr_claim_allowed": False,
    }

    rows_to_write = dataset_rows if split_gate["status"] == PASS else []
    write_jsonl(output_paths["ranking_training_dataset"], rows_to_write)
    write_json(output_paths["manifest"], manifest)
    write_json(output_paths["gate_report"], gate_report)
    write_json(output_paths["dataset_report"], report)
    write_json(output_paths["screening_audit"], screening_audit)
    write_json(output_paths["feature_contract"], feature_contract)
    return manifest


def build_screening_plan(
    positive_events: list[dict[str, Any]],
    screening_policy: str,
    min_user_train_positive_count: int,
    min_item_train_positive_user_count: int,
) -> dict[str, Any]:
    policy = str(screening_policy or "none")
    if policy not in SCREENING_POLICIES:
        raise ValueError(f"Unsupported screening_policy: {screening_policy}")
    user_counts = Counter(event["user_id"] for event in positive_events)
    item_users: dict[str, set[str]] = defaultdict(set)
    for event in positive_events:
        item_users[event["item_id"]].add(event["user_id"])
    raw_users = set(user_counts)
    raw_items = set(item_users)
    min_user = max(1, int(min_user_train_positive_count))
    min_item_users = max(1, int(min_item_train_positive_user_count))
    if policy == "none":
        eligible_users = raw_users
        eligible_items = raw_items
        order = []
    elif policy == "user_first":
        first_pass_users = {user_id for user_id, count in user_counts.items() if count >= min_user}
        retained_item_users: dict[str, set[str]] = defaultdict(set)
        for event in positive_events:
            if event["user_id"] in first_pass_users:
                retained_item_users[event["item_id"]].add(event["user_id"])
        eligible_items = {item_id for item_id, users in retained_item_users.items() if len(users) >= min_item_users}
        eligible_users = first_pass_users
        order = ["user_min_positive_count", "item_min_distinct_positive_users"]
    else:
        first_pass_items = {item_id for item_id, users in item_users.items() if len(users) >= min_item_users}
        retained_user_counts = Counter(event["user_id"] for event in positive_events if event["item_id"] in first_pass_items)
        eligible_users = {user_id for user_id, count in retained_user_counts.items() if count >= min_user}
        eligible_items = first_pass_items
        order = ["item_min_distinct_positive_users", "user_min_retained_positive_count"]
    retained_events = [event for event in positive_events if event["user_id"] in eligible_users and event["item_id"] in eligible_items]
    retained_user_counts = Counter(event["user_id"] for event in retained_events)
    retained_item_users: dict[str, set[str]] = defaultdict(set)
    for event in retained_events:
        retained_item_users[event["item_id"]].add(event["user_id"])
    return {
        "schema_version": "cold_deepfm_screening_audit_v1",
        "status": PASS,
        "screening_policy": policy,
        "order": order,
        "thresholds": {
            "min_user_train_positive_count": min_user,
            "min_item_train_positive_user_count": min_item_users,
        },
        "raw_stats": {
            "positive_events": len(positive_events),
            "eligible_users": len(raw_users),
            "eligible_items": len(raw_items),
            "user_train_positive_count_min": min(user_counts.values(), default=0),
            "item_train_positive_user_count_min": min((len(users) for users in item_users.values()), default=0),
        },
        "retained_stats": {
            "positive_events": len(retained_events),
            "eligible_users": len(eligible_users),
            "eligible_items": len(eligible_items),
            "user_train_positive_count_min": min(retained_user_counts.values(), default=0),
            "item_train_positive_user_count_min": min((len(users) for users in retained_item_users.values()), default=0),
        },
        "eligible_users": sorted(eligible_users),
        "eligible_items": sorted(eligible_items),
        "valid_test_used_for_screening": False,
    }


def screen_positive_events(positive_events: list[dict[str, Any]], screening_plan: dict[str, Any]) -> list[dict[str, Any]]:
    eligible_users = set(screening_plan.get("eligible_users") or [])
    eligible_items = set(screening_plan.get("eligible_items") or [])
    return [event for event in positive_events if event["user_id"] in eligible_users and event["item_id"] in eligible_items]


def _feature_contract(*, feature_names: list[str], feature_version: str, screening_audit: dict[str, Any], source_manifest_hash: str) -> dict[str, Any]:
    return {
        "schema_version": "cold_deepfm_feature_contract_v1",
        "feature_names": sorted(feature_names),
        "feature_version": feature_version,
        "screening_policy": screening_audit["screening_policy"],
        "screening_order": screening_audit["order"],
        "thresholds": screening_audit["thresholds"],
        "eligible_users": screening_audit["eligible_users"],
        "eligible_items": screening_audit["eligible_items"],
        "source_manifest_hash": source_manifest_hash,
        "valid_test_used_for_feature_stats": False,
        "valid_test_used_for_negative_sampling": False,
    }


def feature_contract_hash(feature_contract: dict[str, Any]) -> str:
    payload = {key: value for key, value in feature_contract.items() if key != "feature_contract_hash"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _dataset_source_audit(
    *,
    train_interactions_path: Path,
    valid_interactions_path: Path | None,
    test_interactions_path: Path | None,
    dataset_id: str,
    dataset_window: str,
    train_rows_read: int,
) -> dict[str, Any]:
    return {
        "schema_version": "cold_deepfm_dataset_source_audit_v1",
        "dataset_id": dataset_id,
        "dataset_window": dataset_window,
        "default_dataset_dir": str(DEFAULT_2Y1M3M_DATASET_DIR),
        "train_interactions_path": str(train_interactions_path),
        "valid_interactions_path": str(valid_interactions_path) if valid_interactions_path else "",
        "test_interactions_path": str(test_interactions_path) if test_interactions_path else "",
        "train_rows_read": train_rows_read,
        "train_used_for": "training",
        "valid_used_for": "evaluation_only",
        "test_used_for": "evaluation_only",
        "valid_used_for_training": False,
        "test_used_for_training": False,
        "valid_test_used_for_negative_sampling": False,
        "valid_test_used_for_training_stats": False,
        "valid_test_used_for_candidate_generation": False,
        "oracle_injection_allowed": False,
    }


def _output_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "manifest": output_dir / "manifest.json",
        "ranking_training_dataset": output_dir / "ranking_training_dataset.jsonl",
        "gate_report": output_dir / "gate_report.json",
        "dataset_report": output_dir / "dataset_report.json",
        "screening_audit": output_dir / "screening_audit.json",
        "feature_contract": output_dir / "feature_contract.json",
    }


def _precheck(train_interactions_path: Path, item_universe_path: Path | None, output_paths: dict[str, Path], overwrite: bool) -> None:
    if not train_interactions_path.is_file():
        raise FileNotFoundError(f"train_interactions path does not exist or is not a file: {train_interactions_path}")
    if item_universe_path is not None and not item_universe_path.is_file():
        raise FileNotFoundError(f"item_universe path does not exist or is not a file: {item_universe_path}")
    if not overwrite:
        existing = [str(path) for path in output_paths.values() if path.exists()]
        if existing:
            raise FileExistsError(f"Output files already exist: {existing}")


def _positive_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events = []
    for row in rows:
        user_id = _string(row.get("user_id"))
        item_id = _item_id(row)
        if not user_id or not item_id or not _positive(row):
            continue
        event_time, event_time_source = _event_time(row)
        events.append(
            {
                "user_id": user_id,
                "item_id": item_id,
                "event_time": event_time,
                "event_time_source": event_time_source,
                "source_row": row,
            }
        )
    events.sort(key=lambda event: (event["user_id"], event["event_time"], event["item_id"]))
    return events


def _build_rows(
    *,
    positive_events: list[dict[str, Any]],
    item_universe: list[str],
    split: str,
    negatives_per_positive: int,
    seed: int,
    item_universe_source: str,
    feature_version: str,
    source_manifest_hash: str,
    train_history_feature_index: dict[str, Any],
) -> list[dict[str, Any]]:
    user_positive_prefix_index = _user_positive_prefix_index(positive_events)
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    for event in positive_events:
        row_base = {
            "schema_version": ROW_SCHEMA_VERSION,
            "user_id": event["user_id"],
            "split": split,
            "negative_sampling_strategy": "train_item_universe_exclude_user_positives",
            "negative_sampling_seed": seed,
            "item_universe_source": item_universe_source,
            "feature_version": feature_version,
            "source_manifest_hash": source_manifest_hash,
        }
        rows.append(
            row_base
            | {
                "item_id": event["item_id"],
                "label": 1,
                "label_semantics": "observed_positive",
                "event_time": event["event_time"],
                "label_event_time": event["event_time"],
                "negative_sampling_cutoff_time": None,
                "feature_cutoff_time": event["event_time"],
                "event_time_source": event["event_time_source"],
                "label_event_time_source": event["event_time_source"],
                "features": _train_history_features(event["user_id"], event["item_id"], event["event_time"], train_history_feature_index),
            }
        )
        for negative_item_id in _sample_negative_items(
            item_universe,
            _user_positive_items_at_or_before(user_positive_prefix_index, event["user_id"], event["event_time"], event["item_id"]),
            count=negatives_per_positive,
            rng=rng,
        ):
            rows.append(
                row_base
                | {
                    "item_id": negative_item_id,
                    "label": 0,
                    "label_semantics": "weak_negative",
                    "event_time": event["event_time"],
                    "label_event_time": event["event_time"],
                    "negative_sampling_cutoff_time": event["event_time"],
                    "feature_cutoff_time": event["event_time"],
                    "event_time_source": "negative_sampling_cutoff_time",
                    "label_event_time_source": "negative_sampling_cutoff_time",
                    "features": _train_history_features(event["user_id"], negative_item_id, event["event_time"], train_history_feature_index),
                }
            )
    return rows


def _user_positive_prefix_index(positive_events: list[dict[str, Any]]) -> dict[str, Any]:
    events_by_user: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    for event in positive_events:
        event_time = _parse_time(event.get("event_time"))
        if event_time is None:
            continue
        events_by_user[event["user_id"]].append((event_time, event["item_id"]))
    prefix_index: dict[str, dict[str, Any]] = {}
    for user_id, user_events in events_by_user.items():
        sorted_events = sorted(user_events, key=lambda value: (value[0], value[1]))
        times = []
        prefix_items = []
        seen_items: set[str] = set()
        for event_time, item_id in sorted_events:
            seen_items.add(item_id)
            times.append(event_time)
            prefix_items.append(set(seen_items))
        prefix_index[user_id] = {"times": times, "prefix_items": prefix_items}
    return prefix_index


def _user_positive_items_at_or_before(prefix_index: dict[str, Any], user_id: str, cutoff_time: Any, current_item_id: str) -> set[str]:
    cutoff = _parse_time(cutoff_time)
    user_index = prefix_index.get(user_id) or {}
    times = user_index.get("times") or []
    prefix_items = user_index.get("prefix_items") or []
    excluded = set()
    if cutoff is not None:
        index = bisect_right(times, cutoff)
        if index > 0:
            excluded.update(prefix_items[index - 1])
    if current_item_id:
        excluded.add(current_item_id)
    return excluded


def _train_history_feature_index(positive_events: list[dict[str, Any]]) -> dict[str, Any]:
    item_event_times: dict[str, list[datetime]] = defaultdict(list)
    user_event_times: dict[str, list[datetime]] = defaultdict(list)
    item_distinct_user_times: dict[str, list[datetime]] = defaultdict(list)
    item_distinct_user_counts: dict[str, list[int]] = defaultdict(list)
    user_distinct_item_times: dict[str, list[datetime]] = defaultdict(list)
    user_distinct_item_counts: dict[str, list[int]] = defaultdict(list)
    seen_users_by_item: dict[str, set[str]] = defaultdict(set)
    seen_items_by_user: dict[str, set[str]] = defaultdict(set)

    sorted_events = sorted(
        positive_events,
        key=lambda event: (_parse_time(event.get("event_time")) or datetime.min.replace(tzinfo=UTC), event["user_id"], event["item_id"]),
    )
    for event in sorted_events:
        event_time = _parse_time(event.get("event_time"))
        if event_time is None:
            continue
        user_id = event["user_id"]
        item_id = event["item_id"]
        item_event_times[item_id].append(event_time)
        user_event_times[user_id].append(event_time)
        if user_id not in seen_users_by_item[item_id]:
            seen_users_by_item[item_id].add(user_id)
            item_distinct_user_times[item_id].append(event_time)
            item_distinct_user_counts[item_id].append(len(seen_users_by_item[item_id]))
        if item_id not in seen_items_by_user[user_id]:
            seen_items_by_user[user_id].add(item_id)
            user_distinct_item_times[user_id].append(event_time)
            user_distinct_item_counts[user_id].append(len(seen_items_by_user[user_id]))
    return {
        "item_event_times": dict(item_event_times),
        "user_event_times": dict(user_event_times),
        "item_distinct_user_times": dict(item_distinct_user_times),
        "item_distinct_user_counts": dict(item_distinct_user_counts),
        "user_distinct_item_times": dict(user_distinct_item_times),
        "user_distinct_item_counts": dict(user_distinct_item_counts),
    }


def _train_history_features(user_id: str, item_id: str, cutoff_time: Any, feature_index: dict[str, Any]) -> dict[str, float]:
    cutoff = _parse_time(cutoff_time)
    item_positive_count = _count_before(feature_index["item_event_times"].get(item_id, []), cutoff)
    user_positive_count = _count_before(feature_index["user_event_times"].get(user_id, []), cutoff)
    item_positive_user_count = _prefix_count_before(
        feature_index["item_distinct_user_times"].get(item_id, []),
        feature_index["item_distinct_user_counts"].get(item_id, []),
        cutoff,
    )
    user_distinct_item_count = _prefix_count_before(
        feature_index["user_distinct_item_times"].get(user_id, []),
        feature_index["user_distinct_item_counts"].get(user_id, []),
        cutoff,
    )
    return {
        "score_item_train_positive_count_log1p": round(math.log1p(item_positive_count), 10),
        "score_item_train_positive_user_count_log1p": round(math.log1p(item_positive_user_count), 10),
        "score_user_train_positive_count_log1p": round(math.log1p(user_positive_count), 10),
        "score_user_train_distinct_item_count_log1p": round(math.log1p(user_distinct_item_count), 10),
        "has_item_train_history": 1.0 if item_positive_count > 0 else 0.0,
        "has_user_train_history": 1.0 if user_positive_count > 0 else 0.0,
    }


def _count_before(times: list[datetime], cutoff: datetime | None) -> int:
    if cutoff is None:
        return 0
    return bisect_left(times, cutoff)


def _prefix_count_before(times: list[datetime], counts: list[int], cutoff: datetime | None) -> int:
    index = _count_before(times, cutoff)
    if index <= 0:
        return 0
    return counts[index - 1]


def _sample_negative_items(item_universe: list[str], user_positive_items: set[str], *, count: int, rng: random.Random) -> list[str]:
    if count <= 0 or not item_universe:
        return []
    if len(user_positive_items) >= len(item_universe):
        return []
    negatives = []
    seen = set()
    max_attempts = min(len(item_universe) * 2, max(100, count * 20))
    for _ in range(max_attempts):
        item_id = item_universe[rng.randrange(len(item_universe))]
        if item_id in user_positive_items or item_id in seen:
            continue
        negatives.append(item_id)
        seen.add(item_id)
        if len(negatives) >= count:
            return negatives
    for item_id in item_universe:
        if item_id in user_positive_items or item_id in seen:
            continue
        negatives.append(item_id)
        seen.add(item_id)
        if len(negatives) >= count:
            break
    return negatives


def _training_split_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    split_counts = Counter(_split(row) for row in rows)
    rejected = sorted(split for split in split_counts if split in FORBIDDEN_TRAINING_SPLITS or split not in ALLOWED_TRAINING_SPLITS)
    return {
        "schema_version": "cold_deepfm_ranking_training_split_gate_v1",
        "status": STOP if rejected else PASS,
        "split_counts": dict(sorted(split_counts.items())),
        "rejected_splits": rejected,
        "allowed_training_splits": sorted(ALLOWED_TRAINING_SPLITS - {""}) + ["unknown"],
        "forbidden_splits": sorted(FORBIDDEN_TRAINING_SPLITS),
        "reasons": ["valid_test_holdout_or_unknown_eval_split_in_training_input"] if rejected else [],
    }


def _schema_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    missing = []
    bad_semantics = []
    bad_labels = []
    for index, row in enumerate(rows):
        absent = [field for field in REQUIRED_ROW_FIELDS if field not in row]
        if absent:
            missing.append({"row_index": index, "missing_fields": absent})
        if row.get("label_semantics") not in {"observed_positive", "weak_negative"}:
            bad_semantics.append(index)
        if row.get("label") not in {0, 1}:
            bad_labels.append(index)
    return {
        "schema_version": "cold_deepfm_ranking_training_schema_gate_v1",
        "status": PASS if not missing and not bad_semantics and not bad_labels else STOP,
        "checked_rows": len(rows),
        "required_fields": REQUIRED_ROW_FIELDS,
        "missing": missing[:20],
        "bad_semantics_rows": bad_semantics[:20],
        "bad_label_rows": bad_labels[:20],
    }


def _feature_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    empty_feature_rows = []
    non_numeric_feature_rows = []
    feature_names = set()
    forbidden_feature_names = set()
    for index, row in enumerate(rows):
        features = row.get("features")
        if not isinstance(features, dict) or not features:
            empty_feature_rows.append(index)
            continue
        for name, value in features.items():
            feature_name = str(name)
            feature_names.add(feature_name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                non_numeric_feature_rows.append({"row_index": index, "feature_name": feature_name})
            if any(token in feature_name for token in FORBIDDEN_FEATURE_NAME_TOKENS):
                forbidden_feature_names.add(feature_name)
    missing_expected_features = sorted(set(TRAIN_HISTORY_FEATURE_NAMES) - feature_names) if rows else []
    status = PASS if not empty_feature_rows and not non_numeric_feature_rows and not forbidden_feature_names and not missing_expected_features else STOP
    return {
        "schema_version": "cold_deepfm_train_history_feature_gate_v1",
        "status": status,
        "checked_rows": len(rows),
        "feature_policy": "train_only_prefix_history_before_feature_cutoff_time",
        "feature_names": sorted(feature_names),
        "expected_feature_names": TRAIN_HISTORY_FEATURE_NAMES,
        "missing_expected_features": missing_expected_features,
        "empty_feature_rows": empty_feature_rows[:20],
        "non_numeric_feature_rows": non_numeric_feature_rows[:20],
        "forbidden_feature_names": sorted(forbidden_feature_names),
        "forbidden_feature_name_tokens": list(FORBIDDEN_FEATURE_NAME_TOKENS),
        "no_candidate_rank_or_source_features": not any(name.startswith("source_") or name == "candidate_rank_inverse" for name in feature_names),
    }


def _feature_policy_summary(feature_gate: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "cold_deepfm_train_history_feature_policy_v1",
        "status": feature_gate.get("status"),
        "feature_generation_scope": "train_only_interactions",
        "cutoff_policy": "strictly_before_feature_cutoff_time_for_history_counts",
        "feature_names": feature_gate.get("feature_names", []),
        "avoided_features": ["candidate_rank", "candidate_rank_inverse", "candidate_sources", "source_*", "valid_test_holdout_stats"],
        "cold_bucket_features": ["has_user_train_history", "has_item_train_history"],
    }


def _cold_bucket_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    bucket_counts: Counter[str] = Counter()
    positive_bucket_counts: Counter[str] = Counter()
    negative_bucket_counts: Counter[str] = Counter()
    for row in rows:
        features = row.get("features") if isinstance(row.get("features"), dict) else {}
        user_bucket = "warm_user" if float(features.get("has_user_train_history") or 0.0) > 0 else "cold_user"
        item_bucket = "warm_item" if float(features.get("has_item_train_history") or 0.0) > 0 else "cold_item"
        bucket = f"{user_bucket}__{item_bucket}"
        bucket_counts[bucket] += 1
        if row.get("label") == 1:
            positive_bucket_counts[bucket] += 1
        elif row.get("label") == 0:
            negative_bucket_counts[bucket] += 1
    return {
        "schema_version": "cold_deepfm_train_history_cold_bucket_summary_v1",
        "bucket_policy": "cold iff train-only prefix history count before feature_cutoff_time is zero",
        "bucket_counts": dict(sorted(bucket_counts.items())),
        "positive_bucket_counts": dict(sorted(positive_bucket_counts.items())),
        "negative_bucket_counts": dict(sorted(negative_bucket_counts.items())),
        "recommended_filter_challenger_order": ["warm_user_first", "warm_item_second"],
    }


def _positive_rich_gate(
    rows: list[dict[str, Any]],
    *,
    run_scope: str,
    threshold_override: bool,
    override_reason: str,
    approved_scope: str,
) -> dict[str, Any]:
    stats = _dataset_stats(rows)
    thresholds = {"positive_rows": 20, "positive_users": 10, "positive_ratio_min": 0.001, "positive_ratio_max": 0.5}
    if run_scope == "formal":
        thresholds = {"positive_rows": 1000, "positive_users": 100, "positive_ratio_min": 0.001, "positive_ratio_max": 0.3}
    reasons = []
    if stats["positive_rows"] < thresholds["positive_rows"]:
        reasons.append("positive_rows_below_threshold")
    if stats["positive_users"] < thresholds["positive_users"]:
        reasons.append("positive_users_below_threshold")
    if not (thresholds["positive_ratio_min"] <= stats["positive_ratio"] <= thresholds["positive_ratio_max"]):
        reasons.append("positive_ratio_out_of_range")
    override_valid = threshold_override and bool(override_reason.strip()) and approved_scope == run_scope
    return {
        "schema_version": "cold_deepfm_positive_rich_training_gate_v1",
        "status": PASS if not reasons or override_valid else STOP,
        "run_scope": run_scope,
        "thresholds": thresholds,
        "stats": stats,
        "threshold_override": bool(threshold_override),
        "override_reason": override_reason,
        "approved_scope": approved_scope,
        "override_valid": override_valid,
        "reasons": [] if not reasons or override_valid else reasons,
        "raw_reasons": reasons,
    }


def _weak_negative_gate(
    rows: list[dict[str, Any]],
    *,
    source_rows: list[dict[str, Any]],
    item_universe_source: str,
    item_universe_rows: int,
    negatives_per_positive: int,
    seed: int,
) -> dict[str, Any]:
    stats = _dataset_stats(rows)
    required = {
        "sampling_source": "train_only_interactions",
        "positive_negative_ratio": stats["positive_negative_ratio"],
        "negative_sampling_seed": seed,
        "item_universe": item_universe_source,
        "time_window": _time_window(source_rows),
        "exclusion_rules": ["exclude_user_observed_positive_items", "sample_without_full_item_universe_shuffle", "forbid_valid_test_holdout_training_rows"],
        "label_semantics": "weak_negative",
    }
    missing = [key for key, value in required.items() if value in (None, "", [], {})]
    semantics_ok = all(row.get("label_semantics") == "weak_negative" and row.get("label") == 0 for row in rows if row.get("label") == 0)
    return {
        "schema_version": "cold_deepfm_weak_negative_gate_v1",
        "status": PASS if not missing and semantics_ok else STOP,
        "required_metadata": required,
        "weak_negative_rows": stats["negative_rows"],
        "negatives_per_positive_requested": negatives_per_positive,
        "item_universe_rows": item_universe_rows,
        "missing_metadata_fields": missing,
        "semantics_ok": semantics_ok,
        "disclaimer": "weak_negative rows are unobserved-as-positive proxy negatives, not true exposure non-click negatives.",
    }


def _row_level_time_leakage_gate(rows: list[dict[str, Any]], *, train_split_gate: dict[str, Any]) -> dict[str, Any]:
    failures = []
    train_dev_end = max((_parse_time(row.get("label_event_time")) for row in rows if row.get("label_event_time") is not None), default=None)
    for index, row in enumerate(rows):
        event_time = _parse_time(row.get("event_time"))
        label_event_time = _parse_time(row.get("label_event_time"))
        feature_cutoff_time = _parse_time(row.get("feature_cutoff_time"))
        negative_cutoff_time = _parse_time(row.get("negative_sampling_cutoff_time"))
        reasons = []
        if train_dev_end is not None and event_time is not None and event_time > train_dev_end:
            reasons.append("event_time_after_train_dev_end")
        if train_dev_end is not None and label_event_time is not None and label_event_time > train_dev_end:
            reasons.append("label_event_time_after_train_dev_end")
        if feature_cutoff_time is None or label_event_time is None or feature_cutoff_time > label_event_time:
            reasons.append("feature_cutoff_time_after_label_event_time")
        if row.get("label_semantics") == "weak_negative":
            if negative_cutoff_time is None:
                reasons.append("weak_negative_missing_negative_sampling_cutoff_time")
            elif feature_cutoff_time is not None and feature_cutoff_time > negative_cutoff_time:
                reasons.append("weak_negative_feature_cutoff_after_negative_sampling_cutoff")
            if row.get("event_time") != row.get("negative_sampling_cutoff_time") or row.get("label_event_time") != row.get("negative_sampling_cutoff_time"):
                reasons.append("weak_negative_time_fields_not_cutoff_aligned")
        if row.get("label_semantics") == "observed_positive" and row.get("negative_sampling_cutoff_time") is not None:
            reasons.append("positive_row_has_negative_sampling_cutoff_time")
        if reasons:
            failures.append({"row_index": index, "user_id": row.get("user_id"), "item_id": row.get("item_id"), "reasons": reasons})
    return {
        "schema_version": "cold_deepfm_row_level_time_leakage_gate_v1",
        "status": PASS if not failures and train_split_gate.get("status") == PASS else STOP,
        "checked_rows": len(rows),
        "train_dev_end": _format_time(train_dev_end),
        "failures": failures[:20],
        "training_split_gate_status": train_split_gate.get("status"),
        "valid_test_holdout_used_for_training": train_split_gate.get("status") != PASS,
    }


def _dataset_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    positive_rows = [row for row in rows if row.get("label") == 1]
    negative_rows = [row for row in rows if row.get("label") == 0]
    return {
        "rows": len(rows),
        "positive_rows": len(positive_rows),
        "negative_rows": len(negative_rows),
        "positive_users": len({row["user_id"] for row in positive_rows}),
        "users": len({row["user_id"] for row in rows}),
        "positive_ratio": round(len(positive_rows) / len(rows), 8) if rows else 0.0,
        "positive_negative_ratio": f"{len(positive_rows)}:{len(negative_rows)}",
    }


def _item_universe(rows: list[dict[str, Any]], item_universe_path: Path | None) -> tuple[list[str], str, int]:
    if item_universe_path is None:
        items = sorted({_item_id(row) for row in rows if _item_id(row)})
        return items, "train_only_interaction_items", len(items)
    item_rows = list(iter_jsonl(item_universe_path))
    items = sorted({_item_id(row) for row in item_rows if _item_id(row)})
    return items, "provided_item_universe", len(item_rows)


def _read_source_rows(path: Path, *, max_rows: int | None) -> list[dict[str, Any]]:
    rows = []
    for index, row in enumerate(iter_jsonl(path), start=1):
        if max_rows is not None and index > max(0, int(max_rows)):
            break
        rows.append(row)
    return rows


def _source_manifest_hash(
    train_interactions_path: Path,
    item_universe_path: Path | None,
    *,
    max_rows: int | None,
    fast_source_fingerprint: bool,
) -> str:
    payload = {
        "train_interactions_path": str(train_interactions_path),
        "train_interactions_fingerprint": _source_fingerprint(train_interactions_path, fast=fast_source_fingerprint),
        "item_universe_path": str(item_universe_path) if item_universe_path else "",
        "item_universe_fingerprint": _source_fingerprint(item_universe_path, fast=fast_source_fingerprint) if item_universe_path else "",
        "max_rows": max_rows,
        "fingerprint_mode": "path_size_mtime" if fast_source_fingerprint else "sha256",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _source_fingerprint(path: Path | None, *, fast: bool) -> str:
    if path is None:
        return ""
    if not fast:
        return _sha256_file(path)
    stat = path.stat()
    payload = {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _time_window(rows: list[dict[str, Any]]) -> dict[str, str]:
    times = [_parse_time(_event_time(row)[0]) for row in rows]
    times = [value for value in times if value is not None]
    return {"start": _format_time(min(times)) if times else "", "end": _format_time(max(times)) if times else ""}


def _split(row: dict[str, Any]) -> str:
    return _string(row.get("split") or row.get("label_split") or "unknown").lower()


def _positive(row: dict[str, Any]) -> bool:
    for field in LABEL_FIELDS:
        if field in row:
            value = row.get(field)
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "positive"}
            return bool(value)
    event_type = str(row.get("event_type") or "").strip().lower()
    return event_type in {"train_positive", "positive", "observed_positive"}


def _item_id(row: dict[str, Any]) -> str:
    for field in ITEM_FIELDS:
        value = _string(row.get(field))
        if value:
            return value
    return ""


def _event_time(row: dict[str, Any]) -> tuple[str, str]:
    for field in TIME_FIELDS:
        value = row.get(field)
        if value not in (None, ""):
            return _format_time(_parse_time(value)) or _string(value), field
    return "1970-01-01T00:00:00+00:00", "default_epoch_missing_source_time"


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric = numeric / 1000.0
        return datetime.fromtimestamp(numeric, tz=UTC)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _parse_time(int(text))
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%m %d, %Y"):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_time(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _sha256_file(path: Path | None) -> str:
    if path is None:
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _string(value: Any) -> str:
    return str(value).strip() if value is not None else ""


if __name__ == "__main__":
    main()
