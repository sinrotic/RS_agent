from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "pool500_label_artifact_v1"
MANIFEST_SCHEMA_VERSION = "pool500_label_artifact_manifest_v1"
DEFAULT_OUTPUT_NAME = "pool500_labels.jsonl"
LABEL_FIELDS = ("label_binary", "label", "holdout_hit", "is_hit", "clicked", "purchased")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an explicit diagnostic pool500 label artifact from candidate and hit-style JSONL inputs.")
    parser.add_argument("--pool500-candidates", required=True)
    parser.add_argument("--interaction-labels", required=True, help="Explicit interaction or hit-style JSONL input; no implicit discovery is performed.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--candidate-manifest", default="", help="Optional manifest to update with label_artifact_path metadata.")
    parser.add_argument("--output-name", default=DEFAULT_OUTPUT_NAME)
    parser.add_argument("--update-candidate-manifest", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def build_pool500_label_artifact(
    *,
    pool500_candidates_path: Path,
    interaction_labels_path: Path,
    output_dir: Path,
    candidate_manifest_path: Path | None = None,
    output_name: str = DEFAULT_OUTPUT_NAME,
    update_candidate_manifest: bool = False,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    pool500_candidates_path = pool500_candidates_path.resolve()
    interaction_labels_path = interaction_labels_path.resolve()
    output_dir = output_dir.resolve()
    output_path = output_dir / output_name
    manifest_path = output_dir / "pool500_label_artifact_manifest.json"
    candidate_manifest_path = candidate_manifest_path.resolve() if candidate_manifest_path else None
    _precheck(pool500_candidates_path, interaction_labels_path, output_path, manifest_path, overwrite, candidate_manifest_path, update_candidate_manifest)

    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_rows = _load_candidate_rows(pool500_candidates_path)
    positive_pairs, positive_pair_splits, label_source_summary = _load_positive_label_pairs(interaction_labels_path)
    label_rows = [_label_row(row, positive_pairs, positive_pair_splits, label_source_summary.get("default_split")) for row in candidate_rows]
    write_jsonl(output_path, label_rows)

    positive_count = sum(1 for row in label_rows if row["label_binary"] == 1)
    user_count = len({row["user_id"] for row in label_rows})
    labeled_user_count = len({row["user_id"] for row in label_rows if row["label_binary"] == 1})
    candidate_source_counts = Counter(str(row.get("source") or "") for row in candidate_rows)
    coverage_diagnostics = _coverage_diagnostics(candidate_rows, positive_pairs)
    label_artifact = {
        "schema_version": SCHEMA_VERSION,
        "path": str(output_path),
        "sha256": _sha256_file(output_path),
        "row_count": len(label_rows),
        "positive_count": positive_count,
        "negative_count": len(label_rows) - positive_count,
        "user_count": user_count,
        "labeled_user_count": labeled_user_count,
        "candidate_coverage": 1.0 if label_rows else 0.0,
        "user_coverage": round(labeled_user_count / user_count, 6) if user_count else 0.0,
        "positive_coverage": round(positive_count / len(label_rows), 6) if label_rows else 0.0,
        "positive_overlap_count": coverage_diagnostics["positive_overlap_count"],
        "positive_overlap_user_count": coverage_diagnostics["positive_overlap_user_count"],
        "candidate_hit_rate": coverage_diagnostics["candidate_hit_rate"],
        "missing_reason_counts": coverage_diagnostics["missing_reason_counts"],
        "join_key": "user_id,parent_asin",
        "label_source_path": str(interaction_labels_path),
        "label_source_sha256": _sha256_file(interaction_labels_path),
        "label_source_summary": label_source_summary,
    }
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "PASS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pool500_candidates_path": str(pool500_candidates_path),
        "pool500_candidates_sha256": _sha256_file(pool500_candidates_path),
        "interaction_labels_path": str(interaction_labels_path),
        "interaction_labels_sha256": _sha256_file(interaction_labels_path),
        "label_artifact_path": str(output_path),
        "label_artifact": label_artifact,
        "candidate_source_counts": dict(sorted(candidate_source_counts.items())),
        "diagnostic_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "full_pool500_ready_declared": False,
    }
    write_json(manifest_path, manifest)
    if update_candidate_manifest and candidate_manifest_path is not None:
        _update_candidate_manifest(candidate_manifest_path, output_path, manifest_path, label_artifact)
    return manifest


def _precheck(
    pool500_candidates_path: Path,
    interaction_labels_path: Path,
    output_path: Path,
    manifest_path: Path,
    overwrite: bool,
    candidate_manifest_path: Path | None,
    update_candidate_manifest: bool,
) -> None:
    for path, name in ((pool500_candidates_path, "pool500_candidates"), (interaction_labels_path, "interaction_labels")):
        if not path.is_file():
            raise FileNotFoundError(f"{name} path does not exist or is not a file: {path}")
    if update_candidate_manifest and candidate_manifest_path is None:
        raise ValueError("candidate_manifest_path is required when update_candidate_manifest=True")
    if candidate_manifest_path is not None and not candidate_manifest_path.is_file():
        raise FileNotFoundError(f"candidate manifest path does not exist or is not a file: {candidate_manifest_path}")
    for path in (output_path, manifest_path):
        if path.exists() and not overwrite:
            raise FileExistsError(f"Output already exists: {path}")


def _load_candidate_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row_number, row in enumerate(iter_jsonl(path), start=1):
        user_id = str(row.get("user_id") or "")
        parent_asin = str(row.get("parent_asin") or row.get("item_id") or "")
        if not user_id or not parent_asin:
            raise ValueError(f"Candidate row {row_number} is missing user_id or item_id/parent_asin")
        pair = (user_id, parent_asin)
        if pair in seen:
            continue
        seen.add(pair)
        normalized = dict(row)
        normalized["user_id"] = user_id
        normalized["parent_asin"] = parent_asin
        rows.append(normalized)
    if not rows:
        raise ValueError(f"Candidate file has no usable rows: {path}")
    return rows


def _load_positive_label_pairs(path: Path) -> tuple[set[tuple[str, str]], dict[tuple[str, str], str], dict[str, Any]]:
    pairs: set[tuple[str, str]] = set()
    pair_splits: dict[tuple[str, str], str] = {}
    split_counts: Counter[str] = Counter()
    row_count = 0
    usable_count = 0
    skipped_missing_key_count = 0
    skipped_non_positive_count = 0
    for row in iter_jsonl(path):
        row_count += 1
        user_id = str(row.get("user_id") or "")
        parent_asin = str(row.get("parent_asin") or row.get("item_id") or "")
        split = str(row.get("split") or row.get("label_split") or "unknown")
        split_counts[split] += 1
        if not user_id or not parent_asin:
            skipped_missing_key_count += 1
            continue
        usable_count += 1
        if _label_row_positive(row):
            pair = (user_id, parent_asin)
            pairs.add(pair)
            pair_splits[pair] = split
        else:
            skipped_non_positive_count += 1
    default_split = next(iter(split_counts)) if len(split_counts) == 1 else None
    return pairs, pair_splits, {
        "schema": "hit_style_jsonl",
        "row_count": row_count,
        "usable_join_key_row_count": usable_count,
        "positive_pair_count": len(pairs),
        "split_counts": dict(sorted(split_counts.items())),
        "default_split": default_split,
        "skipped_missing_join_key_count": skipped_missing_key_count,
        "skipped_non_positive_count": skipped_non_positive_count,
        "positive_default_when_label_field_absent": True,
    }


def _coverage_diagnostics(candidate_rows: list[dict[str, Any]], positive_pairs: set[tuple[str, str]]) -> dict[str, Any]:
    candidate_pairs = {(str(row["user_id"]), str(row["parent_asin"])) for row in candidate_rows}
    candidate_users = {user_id for user_id, _ in candidate_pairs}
    hit_pairs = candidate_pairs & positive_pairs
    missing_reason_counts: Counter[str] = Counter()
    for user_id, item_id in positive_pairs:
        if user_id not in candidate_users:
            missing_reason_counts["user_missing"] += 1
        elif (user_id, item_id) not in candidate_pairs:
            missing_reason_counts["item_not_in_candidate"] += 1
        else:
            missing_reason_counts["hit"] += 1
    return {
        "positive_overlap_count": len(hit_pairs),
        "positive_overlap_user_count": len({user_id for user_id, _ in hit_pairs}),
        "candidate_hit_rate": round(len(hit_pairs) / len(positive_pairs), 6) if positive_pairs else 0.0,
        "missing_reason_counts": dict(sorted(missing_reason_counts.items())),
    }


def _label_row(candidate_row: dict[str, Any], positive_pairs: set[tuple[str, str]], positive_pair_splits: dict[tuple[str, str], str], default_split: Any) -> dict[str, Any]:
    user_id = str(candidate_row["user_id"])
    parent_asin = str(candidate_row["parent_asin"])
    pair = (user_id, parent_asin)
    label_binary = 1 if pair in positive_pairs else 0
    row = {
        "schema_version": SCHEMA_VERSION,
        "user_id": user_id,
        "parent_asin": parent_asin,
        "label_binary": label_binary,
        "split": positive_pair_splits.get(pair) or str(default_split or "unknown"),
    }
    if candidate_row.get("source") is not None:
        row["candidate_source"] = candidate_row.get("source")
    if candidate_row.get("rank") is not None:
        row["candidate_rank"] = candidate_row.get("rank")
    return row


def _label_row_positive(row: dict[str, Any]) -> bool:
    for field in LABEL_FIELDS:
        if field in row:
            return _strict_positive_value(row.get(field))
    if "rating" in row:
        return float(row.get("rating") or 0.0) > 0.0
    return True


def _strict_positive_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) > 0.0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "positive"}:
            return True
        if normalized in {"0", "false", "no", "n", "negative", ""}:
            return False
        raise ValueError(f"Unsupported label value: {value!r}")
    return bool(value)


def _update_candidate_manifest(candidate_manifest_path: Path, output_path: Path, label_manifest_path: Path, label_artifact: dict[str, Any]) -> None:
    candidate_manifest = read_json(candidate_manifest_path)
    candidate_manifest["label_artifact_path"] = str(output_path)
    candidate_manifest["label_artifact"] = {
        "schema_version": SCHEMA_VERSION,
        "path": str(output_path),
        "manifest_path": str(label_manifest_path),
        "sha256": label_artifact["sha256"],
        "row_count": label_artifact["row_count"],
        "positive_count": label_artifact["positive_count"],
        "join_key": label_artifact["join_key"],
        "candidate_coverage": label_artifact["candidate_coverage"],
        "user_coverage": label_artifact["user_coverage"],
        "positive_coverage": label_artifact["positive_coverage"],
        "positive_overlap_count": label_artifact["positive_overlap_count"],
        "positive_overlap_user_count": label_artifact["positive_overlap_user_count"],
        "candidate_hit_rate": label_artifact["candidate_hit_rate"],
        "missing_reason_counts": label_artifact["missing_reason_counts"],
    }
    candidate_manifest["candidate_generation_allowed"] = False
    candidate_manifest["ranking_input_replacement_allowed"] = False
    candidate_manifest["ranking_replacement_allowed"] = False
    candidate_manifest["promotion_allowed"] = False
    candidate_manifest["pool1000_allowed"] = False
    candidate_manifest["final_pool500_ready_claimed"] = False
    candidate_manifest["full_pool500_ready_declared"] = False
    write_json(candidate_manifest_path, candidate_manifest)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    manifest = build_pool500_label_artifact(
        pool500_candidates_path=Path(args.pool500_candidates),
        interaction_labels_path=Path(args.interaction_labels),
        output_dir=Path(args.output_dir),
        candidate_manifest_path=Path(args.candidate_manifest) if args.candidate_manifest else None,
        output_name=args.output_name,
        update_candidate_manifest=args.update_candidate_manifest,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
