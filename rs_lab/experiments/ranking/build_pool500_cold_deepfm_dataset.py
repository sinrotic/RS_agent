from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, write_json, write_jsonl
from rs_core.common.runtime import enforce_project_venv
from rs_core.recsys.cold_deepfm import build_cold_deepfm_training_rows
from rs_core.recsys.ltr import extract_ltr_features, validate_ltr_feature_contract_gate, validate_ltr_leakage_gate
from rs_core.recsys.types import MergedCandidate
from rs_core.workflow.pool500_ranking_adapter import adapt_pool500_rows_to_candidates

SCHEMA_VERSION = "pool500_cold_deepfm_l4_dataset_v1"
ROW_SCHEMA_VERSION = "pool500_cold_deepfm_l4_row_v1"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "ranking" / "datasets" / "pool500_cold_deepfm_l4"
PASS = "PASS"
STOP = "STOP"
TRAIN_FORBIDDEN_SPLITS = {"valid", "test", "holdout"}
LABEL_FIELDS = ("label_binary", "label", "clicked", "purchased", "is_hit")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build L4 offline ranking rows for pool500 COLD/DeepFM training and evaluation.")
    parser.add_argument("--pool500-candidates", required=True)
    parser.add_argument("--train-label-artifact", required=True)
    parser.add_argument("--valid-label-artifact", default="")
    parser.add_argument("--test-label-artifact", default="")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--limit-users", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_pool500_cold_deepfm_dataset_from_files(
        pool500_candidates_path=Path(args.pool500_candidates),
        train_label_artifact_path=Path(args.train_label_artifact),
        output_dir=Path(args.output_dir),
        valid_label_artifact_path=Path(args.valid_label_artifact) if args.valid_label_artifact else None,
        test_label_artifact_path=Path(args.test_label_artifact) if args.test_label_artifact else None,
        limit_users=args.limit_users,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps(manifest["output_paths"], ensure_ascii=False, indent=2))


def build_pool500_cold_deepfm_dataset_from_files(
    *,
    pool500_candidates_path: Path,
    train_label_artifact_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    valid_label_artifact_path: Path | None = None,
    test_label_artifact_path: Path | None = None,
    limit_users: int | None = None,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    pool500_candidates_path = pool500_candidates_path.resolve()
    train_label_artifact_path = train_label_artifact_path.resolve()
    valid_label_artifact_path = valid_label_artifact_path.resolve() if valid_label_artifact_path else None
    test_label_artifact_path = test_label_artifact_path.resolve() if test_label_artifact_path else None
    output_dir = output_dir.resolve()
    output_paths = _output_paths(output_dir)
    _precheck(pool500_candidates_path, train_label_artifact_path, valid_label_artifact_path, test_label_artifact_path, output_paths, overwrite)

    candidate_rows = list(iter_jsonl(pool500_candidates_path))
    adapter_result = adapt_pool500_rows_to_candidates(candidate_rows)
    candidates_by_user = adapter_result.get("candidates_by_user", {}) if adapter_result.get("status") == PASS else {}
    if limit_users is not None:
        candidates_by_user = {user_id: candidates_by_user[user_id] for user_id in list(candidates_by_user)[: max(0, int(limit_users))]}

    train_label_rows = list(iter_jsonl(train_label_artifact_path))
    train_dataset = build_cold_deepfm_training_rows(candidates_by_user, train_label_rows)
    train_split_gate = _training_split_gate(train_label_rows)
    train_blocked = adapter_result.get("status") != PASS or train_split_gate["status"] != PASS
    train_rows = [] if train_blocked else _build_split_rows(candidates_by_user, train_label_rows, split="train")

    valid_label_rows = list(iter_jsonl(valid_label_artifact_path)) if valid_label_artifact_path else []
    test_label_rows = list(iter_jsonl(test_label_artifact_path)) if test_label_artifact_path else []
    valid_rows = _build_split_rows(candidates_by_user, valid_label_rows, split="valid") if valid_label_artifact_path and adapter_result.get("status") == PASS else []
    test_rows = _build_split_rows(candidates_by_user, test_label_rows, split="test") if test_label_artifact_path and adapter_result.get("status") == PASS else []
    all_rows = train_rows + valid_rows + test_rows

    feature_contract_gate = validate_ltr_feature_contract_gate(_gate_rows(train_rows)) if train_rows else _empty_gate("feature_contract")
    leakage_gate = validate_ltr_leakage_gate(_gate_rows(train_rows), label_source="pool500_label_artifact", training_split="train") if train_rows else _empty_gate("leakage")
    split_gate = {
        "schema_version": "pool500_cold_deepfm_split_gate_v1",
        "status": PASS if adapter_result.get("status") == PASS and train_split_gate["status"] == PASS else STOP,
        "train": train_split_gate,
        "valid": _eval_split_summary(valid_label_rows, expected_split="valid", provided=valid_label_artifact_path is not None),
        "test": _eval_split_summary(test_label_rows, expected_split="test", provided=test_label_artifact_path is not None),
    }
    label_manifest = _label_manifest(
        train_label_rows,
        valid_label_rows,
        test_label_rows,
        train_label_artifact_path=train_label_artifact_path,
        valid_label_artifact_path=valid_label_artifact_path,
        test_label_artifact_path=test_label_artifact_path,
    )
    feature_manifest = _feature_manifest(all_rows)
    blockers = []
    if adapter_result.get("status") != PASS:
        blockers.append({"code": "POOL500_ADAPTER_NOT_PASS", "severity": "blocker", "evidence": adapter_result.get("blockers", [])})
    if train_split_gate["status"] != PASS:
        blockers.append({"code": "COLD_DEEPFM_TRAIN_LABEL_SPLIT_NOT_ALLOWED", "severity": "blocker", "evidence": train_split_gate})
    if not train_rows:
        blockers.append({"code": "COLD_DEEPFM_EMPTY_TRAIN_ROWS", "severity": "blocker"})

    dataset_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": PASS if not blockers else STOP,
        "generated_at": datetime.now(UTC).isoformat(),
        "diagnostic_only": True,
        "offline_training_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "online_interaction_training": "future_boundary",
        "real_exposure_negative_sampling": "future_boundary",
        "online_business_metrics": "future_boundary",
        "serving_latency_slo": "future_boundary",
        "pool500_candidates_path": str(pool500_candidates_path),
        "limit_users": limit_users,
        "adapter_summary": _adapter_summary(adapter_result),
        "train_dataset_summary": train_dataset.get("summary", {}),
        "split_summaries": {
            "train": _row_summary(train_rows),
            "valid": _row_summary(valid_rows),
            "test": _row_summary(test_rows),
        },
        "feature_contract_gate": feature_contract_gate,
        "leakage_gate": leakage_gate,
        "split_gate": split_gate,
        "blockers": blockers,
    }

    write_jsonl(output_paths["train_rows"], train_rows)
    write_jsonl(output_paths["valid_rows"], valid_rows)
    write_jsonl(output_paths["test_rows"], test_rows)
    write_json(output_paths["feature_manifest"], feature_manifest)
    write_json(output_paths["label_manifest"], label_manifest)
    write_json(output_paths["dataset_audit"], dataset_audit)
    write_json(output_paths["split_gate"], split_gate)
    write_json(output_paths["leakage_gate"], leakage_gate)

    manifest = {
        "schema_version": "pool500_cold_deepfm_l4_manifest_v1",
        "status": dataset_audit["status"],
        "generated_at": dataset_audit["generated_at"],
        "output_dir": str(output_dir),
        "output_paths": {name: str(path) for name, path in output_paths.items()},
        "dataset_audit": dataset_audit,
        "diagnostic_only": True,
        "offline_training_only": True,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
    }
    write_json(output_paths["manifest"], manifest)
    return manifest


def _output_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "manifest": output_dir / "manifest.json",
        "train_rows": output_dir / "train_rows.jsonl",
        "valid_rows": output_dir / "valid_rows.jsonl",
        "test_rows": output_dir / "test_rows.jsonl",
        "feature_manifest": output_dir / "feature_manifest.json",
        "label_manifest": output_dir / "label_manifest.json",
        "dataset_audit": output_dir / "dataset_audit.json",
        "split_gate": output_dir / "split_gate.json",
        "leakage_gate": output_dir / "leakage_gate.json",
    }


def _precheck(
    pool500_candidates_path: Path,
    train_label_artifact_path: Path,
    valid_label_artifact_path: Path | None,
    test_label_artifact_path: Path | None,
    output_paths: dict[str, Path],
    overwrite: bool,
) -> None:
    for path, name in ((pool500_candidates_path, "pool500_candidates"), (train_label_artifact_path, "train_label_artifact")):
        if not path.is_file():
            raise FileNotFoundError(f"{name} path does not exist or is not a file: {path}")
    for path, name in ((valid_label_artifact_path, "valid_label_artifact"), (test_label_artifact_path, "test_label_artifact")):
        if path is not None and not path.is_file():
            raise FileNotFoundError(f"{name} path does not exist or is not a file: {path}")
    if not overwrite:
        existing = [str(path) for path in output_paths.values() if path.exists()]
        if existing:
            raise FileExistsError(f"Output files already exist: {existing}")


def _build_split_rows(candidates_by_user: dict[str, list[MergedCandidate]], label_rows: list[dict[str, Any]], *, split: str) -> list[dict[str, Any]]:
    label_by_pair = _label_by_pair(label_rows)
    rows: list[dict[str, Any]] = []
    for user_id, candidates in candidates_by_user.items():
        for candidate in candidates:
            features = extract_ltr_features(candidate, {"include_ranking_v2": True})
            rows.append(
                {
                    "schema_version": ROW_SCHEMA_VERSION,
                    "split": split,
                    "user_id": str(user_id),
                    "item_id": str(candidate.item_id),
                    "label": label_by_pair.get((str(user_id), str(candidate.item_id)), 0),
                    "features": features,
                    "sources": list(candidate.sources),
                    "category": str(candidate.category or ""),
                }
            )
    return rows


def _label_by_pair(label_rows: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    labels: dict[tuple[str, str], int] = {}
    for row in label_rows:
        user_id = str(row.get("user_id") or "")
        item_id = str(row.get("parent_asin") or row.get("item_id") or "")
        if not user_id or not item_id:
            continue
        labels[(user_id, item_id)] = 1 if _positive(row) else 0
    return labels


def _positive(row: dict[str, Any]) -> bool:
    for field in LABEL_FIELDS:
        if field in row:
            value = row.get(field)
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "positive"}
            return bool(value)
    return False


def _training_split_gate(label_rows: list[dict[str, Any]]) -> dict[str, Any]:
    split_counts = _split_counts(label_rows)
    rejected = sorted(split for split in split_counts if split in TRAIN_FORBIDDEN_SPLITS)
    return {
        "schema_version": "pool500_cold_deepfm_train_split_gate_v1",
        "status": STOP if rejected else PASS,
        "split_counts": split_counts,
        "rejected_splits": rejected,
        "allowed_training_splits": ["train", "unknown"],
        "reasons": ["non_train_label_split"] if rejected else [],
    }


def _eval_split_summary(label_rows: list[dict[str, Any]], *, expected_split: str, provided: bool) -> dict[str, Any]:
    split_counts = _split_counts(label_rows)
    return {
        "schema_version": "pool500_cold_deepfm_eval_split_summary_v1",
        "status": PASS,
        "provided": provided,
        "expected_split": expected_split,
        "split_counts": split_counts,
        "row_count": len(label_rows),
        "note": "not_provided" if not provided else "evaluation_only_not_used_for_training",
    }


def _split_counts(label_rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(row.get("split") or row.get("label_split") or "unknown").lower() for row in label_rows)
    return dict(sorted(counts.items()))


def _gate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"user_id": row["user_id"], "item_id": row["item_id"], "label": row["label"], "features": dict(row.get("features") or {})} for row in rows]


def _empty_gate(kind: str) -> dict[str, Any]:
    return {"status": PASS, "checked_rows": 0, "reasons": [], "kind": kind}


def _label_manifest(
    train_label_rows: list[dict[str, Any]],
    valid_label_rows: list[dict[str, Any]],
    test_label_rows: list[dict[str, Any]],
    *,
    train_label_artifact_path: Path,
    valid_label_artifact_path: Path | None,
    test_label_artifact_path: Path | None,
) -> dict[str, Any]:
    return {
        "schema_version": "pool500_cold_deepfm_label_manifest_v1",
        "train": _label_source_manifest(train_label_rows, train_label_artifact_path),
        "valid": _label_source_manifest(valid_label_rows, valid_label_artifact_path) if valid_label_artifact_path else {"provided": False},
        "test": _label_source_manifest(test_label_rows, test_label_artifact_path) if test_label_artifact_path else {"provided": False},
        "training_join_key": "user_id,item_id|parent_asin",
        "holdout_hit_used_as_positive": False,
    }


def _label_source_manifest(label_rows: list[dict[str, Any]], path: Path | None) -> dict[str, Any]:
    positive_pairs = {pair for pair, label in _label_by_pair(label_rows).items() if label == 1}
    return {
        "provided": path is not None,
        "path": str(path) if path else "",
        "sha256": _sha256_file(path) if path else "",
        "row_count": len(label_rows),
        "split_counts": _split_counts(label_rows),
        "positive_pair_count": len(positive_pairs),
        "positive_user_count": len({user_id for user_id, _ in positive_pairs}),
    }


def _feature_manifest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    feature_names = sorted({name for row in rows for name in (row.get("features") or {})})
    nonzero_counts = Counter()
    source_counts = Counter()
    missing_category_count = 0
    for row in rows:
        for name, value in (row.get("features") or {}).items():
            if float(value or 0.0) != 0.0:
                nonzero_counts[name] += 1
        for source in row.get("sources") or []:
            source_counts[str(source)] += 1
        if not row.get("category"):
            missing_category_count += 1
    return {
        "schema_version": "pool500_cold_deepfm_feature_manifest_v1",
        "feature_config": {"include_ranking_v2": True},
        "feature_names": feature_names,
        "feature_count": len(feature_names),
        "nonzero_counts": dict(sorted(nonzero_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "rows": len(rows),
        "missing_category_count": missing_category_count,
    }


def _adapter_summary(adapter_result: dict[str, Any]) -> dict[str, Any]:
    candidates_by_user = adapter_result.get("candidates_by_user", {}) if isinstance(adapter_result, dict) else {}
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


def _row_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    positive_rows = [row for row in rows if row.get("label") == 1]
    return {
        "rows": len(rows),
        "users": len({row["user_id"] for row in rows}),
        "positive_rows": len(positive_rows),
        "positive_users": len({row["user_id"] for row in positive_rows}),
        "positive_rate": round(len(positive_rows) / len(rows), 8) if rows else 0.0,
    }


def _sha256_file(path: Path | None) -> str:
    if path is None:
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
