from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "pool500_diagnostic_oracle_candidate_artifact_v1"
ORACLE_SOURCE = "diagnostic_oracle_candidate"
DEFAULT_OUTPUT_NAME = "pool500_candidates.jsonl"
DEFAULT_MANIFEST_NAME = "diagnostic_oracle_candidate_manifest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a diagnostic-only pool500 candidate artifact by injecting explicit oracle positives."
    )
    parser.add_argument("--base-candidates", required=True)
    parser.add_argument("--label", action="append", required=True, help="valid/test JSONL label input; repeat as needed.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--target-user-manifest", default="")
    parser.add_argument("--min-positive-overlap", type=int, default=30)
    parser.add_argument("--candidate-pool-size", type=int, default=500)
    parser.add_argument("--output-name", default=DEFAULT_OUTPUT_NAME)
    parser.add_argument("--manifest-name", default=DEFAULT_MANIFEST_NAME)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def build_pool500_diagnostic_oracle_candidates(
    *,
    base_candidates_path: Path,
    label_paths: Iterable[Path],
    output_dir: Path,
    target_user_manifest_path: Path | None = None,
    min_positive_overlap: int = 30,
    candidate_pool_size: int = 500,
    output_name: str = DEFAULT_OUTPUT_NAME,
    manifest_name: str = DEFAULT_MANIFEST_NAME,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    base_candidates_path = base_candidates_path.resolve()
    label_paths = [path.resolve() for path in label_paths]
    output_dir = output_dir.resolve()
    output_path = _safe_output_path(output_dir, output_name)
    manifest_path = _safe_output_path(output_dir, manifest_name)
    _precheck(base_candidates_path, label_paths, output_path, manifest_path, overwrite, candidate_pool_size, min_positive_overlap)

    target_users = _load_target_users(target_user_manifest_path)
    base_by_user, base_summary = _load_base_candidates(base_candidates_path, target_users)
    if not base_by_user:
        raise ValueError(f"base candidate file has no usable rows: {base_candidates_path}")
    candidate_users = list(base_by_user)
    label_positives = _load_label_positives(label_paths, set(candidate_users))
    if not label_positives:
        raise ValueError("no positive oracle labels matched base candidate users")

    rows, injection_summary = _build_rows(base_by_user, label_positives, candidate_pool_size)
    achieved_overlap = _count_positive_overlap(rows, label_positives)
    status = "PASS" if achieved_overlap >= min_positive_overlap else "FAIL"
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_path": str(output_path),
        "base_candidates_path": str(base_candidates_path),
        "base_candidates_sha256": _sha256_file(base_candidates_path),
        "label_paths": [str(path) for path in label_paths],
        "target_user_manifest_path": str(target_user_manifest_path.resolve()) if target_user_manifest_path else "",
        "candidate_pool_size": candidate_pool_size,
        "candidate_rows": len(rows),
        "candidate_user_count": len(candidate_users),
        "oracle_source": ORACLE_SOURCE,
        "oracle_positive_overlap_count": achieved_overlap,
        "min_positive_overlap": min_positive_overlap,
        "base_summary": base_summary,
        "injection_summary": injection_summary,
        "diagnostic_only": True,
        "label_inputs_role": "diagnostic_oracle_candidate_construction_only_not_recall_source_or_ranking_input",
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "full_pool500_ready_declared": False,
        "blockers": [] if status == "PASS" else [
            {
                "code": "MIN_POSITIVE_OVERLAP_NOT_MET",
                "evidence": {"oracle_positive_overlap_count": achieved_overlap, "required": min_positive_overlap},
            }
        ],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_path, rows)
    write_json(manifest_path, manifest)
    return manifest


def _safe_output_path(output_dir: Path, name: str) -> Path:
    candidate = Path(name)
    if candidate.is_absolute() or candidate.name != name:
        raise ValueError(f"output name must be a simple file name: {name}")
    return output_dir / candidate


def _precheck(
    base_candidates_path: Path,
    label_paths: list[Path],
    output_path: Path,
    manifest_path: Path,
    overwrite: bool,
    candidate_pool_size: int,
    min_positive_overlap: int,
) -> None:
    if not base_candidates_path.is_file():
        raise FileNotFoundError(f"base candidate path does not exist: {base_candidates_path}")
    if not label_paths:
        raise ValueError("At least one label path is required")
    for path in label_paths:
        if not path.is_file():
            raise FileNotFoundError(f"label path does not exist: {path}")
    if candidate_pool_size <= 0:
        raise ValueError("candidate_pool_size must be positive")
    if min_positive_overlap <= 0:
        raise ValueError("min_positive_overlap must be positive")
    if not overwrite and (output_path.exists() or manifest_path.exists()):
        raise FileExistsError(f"Output already exists: {output_path} or {manifest_path}")


def _load_target_users(path: Path | None) -> set[str]:
    if path is None:
        return set()
    manifest_path = path.resolve()
    manifest = read_json(manifest_path)
    if manifest.get("diagnostic_only") is not True:
        raise ValueError(f"target user manifest must be diagnostic_only=true: {manifest_path}")
    for flag in (
        "candidate_generation_allowed",
        "ranking_input_replacement_allowed",
        "ranking_replacement_allowed",
        "promotion_allowed",
        "pool1000_allowed",
        "final_pool500_ready_claimed",
        "full_pool500_ready_declared",
    ):
        if manifest.get(flag) is not False:
            raise ValueError(f"target user manifest must set {flag}=false: {manifest_path}")
    users = manifest.get("target_user_ids")
    if not isinstance(users, list) or not users:
        users = manifest.get("eligible_user_ids")
    if not isinstance(users, list) or not users:
        raise ValueError(f"target user manifest has no target_user_ids or eligible_user_ids: {manifest_path}")
    return {str(user_id) for user_id in users if user_id}


def _load_base_candidates(path: Path, target_users: set[str]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_counts: Counter[str] = Counter()
    row_count = 0
    skipped = 0
    for row in iter_jsonl(path):
        row_count += 1
        user_id = _string_value(row, "user_id", "user")
        item_id = _string_value(row, "item_id", "parent_asin", "item")
        if not user_id or not item_id:
            skipped += 1
            continue
        if target_users and user_id not in target_users:
            continue
        normalized = dict(row)
        normalized["user_id"] = user_id
        normalized["item_id"] = item_id
        normalized["rank"] = _rank_value(row, len(by_user[user_id]) + 1)
        normalized["metadata"] = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        normalized["sources"] = _sources(row)
        normalized["source"] = _primary_source(row, normalized["sources"])
        normalized["score"] = float(row.get("score", 0.0) or 0.0)
        by_user[user_id].append(normalized)
        source_counts[normalized["source"]] += 1
    for rows in by_user.values():
        rows.sort(key=lambda item: (_rank_value(item, 10**9), -float(item.get("score", 0.0)), item["item_id"]))
    return dict(by_user), {
        "row_count": row_count,
        "usable_row_count": sum(len(rows) for rows in by_user.values()),
        "candidate_user_count": len(by_user),
        "skipped_missing_key_count": skipped,
        "source_counts": dict(sorted(source_counts.items())),
    }


def _load_label_positives(label_paths: list[Path], candidate_users: set[str]) -> dict[str, list[dict[str, Any]]]:
    by_user: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for label_path in label_paths:
        label_source = _label_source(label_path)
        for row in iter_jsonl(label_path):
            user_id = _string_value(row, "user_id", "user")
            item_id = _string_value(row, "parent_asin", "item_id", "item")
            if not user_id or not item_id or user_id not in candidate_users or not _is_positive_label(row):
                continue
            current = by_user[user_id].setdefault(
                item_id,
                {"item_id": item_id, "label_sources": [], "raw_label": {k: row[k] for k in sorted(row) if k in {"rating", "label", "label_binary", "timestamp", "split"}}},
            )
            if label_source not in current["label_sources"]:
                current["label_sources"].append(label_source)
    return {user_id: sorted(items.values(), key=lambda item: (item["label_sources"], item["item_id"])) for user_id, items in by_user.items()}


def _build_rows(
    base_by_user: dict[str, list[dict[str, Any]]],
    label_positives: dict[str, list[dict[str, Any]]],
    candidate_pool_size: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    injected_by_user: dict[str, int] = {}
    promoted_existing = 0
    added_new = 0
    for user_id, base_rows in base_by_user.items():
        existing_by_item = {row["item_id"]: row for row in base_rows}
        selected: list[dict[str, Any]] = []
        selected_items: set[str] = set()
        for positive_rank, positive in enumerate(label_positives.get(user_id, []), start=1):
            item_id = positive["item_id"]
            base_row = existing_by_item.get(item_id)
            if base_row is None:
                row = _oracle_row(user_id, positive, positive_rank)
                added_new += 1
            else:
                row = _promote_existing_row(base_row, positive, positive_rank)
                promoted_existing += 1
            selected.append(row)
            selected_items.add(item_id)
        injected_by_user[user_id] = len(selected)
        for base_row in base_rows:
            if len(selected) >= candidate_pool_size:
                break
            if base_row["item_id"] in selected_items:
                continue
            selected.append(dict(base_row))
            selected_items.add(base_row["item_id"])
        selected = selected[:candidate_pool_size]
        if len(selected) != candidate_pool_size:
            raise ValueError(f"underfilled candidate pool for user {user_id}: {len(selected)} != {candidate_pool_size}")
        for rank, row in enumerate(selected, start=1):
            normalized = dict(row)
            normalized["rank"] = rank
            rows.append(normalized)
    return rows, {
        "oracle_rows_by_user": dict(sorted(injected_by_user.items())),
        "oracle_row_count": sum(injected_by_user.values()),
        "oracle_added_new_count": added_new,
        "oracle_promoted_existing_count": promoted_existing,
        "max_oracle_rows_for_user": max(injected_by_user.values()) if injected_by_user else 0,
    }


def _oracle_row(user_id: str, positive: dict[str, Any], positive_rank: int) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "item_id": positive["item_id"],
        "source": ORACLE_SOURCE,
        "sources": [ORACLE_SOURCE],
        "score": float(1_000_000 - positive_rank),
        "rank": positive_rank,
        "metadata": {
            "diagnostic_oracle_candidate": True,
            "oracle_positive_rank": positive_rank,
            "oracle_label_sources": positive["label_sources"],
            "oracle_policy_role": "diagnostic_overlap_probe_not_recall_or_ranking_input",
            "raw_label": positive.get("raw_label", {}),
        },
    }


def _promote_existing_row(base_row: dict[str, Any], positive: dict[str, Any], positive_rank: int) -> dict[str, Any]:
    row = dict(base_row)
    sources = list(row.get("sources") or [])
    if ORACLE_SOURCE not in sources:
        sources.append(ORACLE_SOURCE)
    row["source"] = ORACLE_SOURCE
    row["sources"] = sources
    row["score"] = max(float(row.get("score", 0.0) or 0.0), float(1_000_000 - positive_rank))
    metadata = dict(row.get("metadata") if isinstance(row.get("metadata"), dict) else {})
    metadata.update({
        "diagnostic_oracle_candidate": True,
        "oracle_positive_rank": positive_rank,
        "oracle_label_sources": positive["label_sources"],
        "oracle_policy_role": "diagnostic_overlap_probe_not_recall_or_ranking_input",
    })
    row["metadata"] = metadata
    return row


def _count_positive_overlap(rows: list[dict[str, Any]], label_positives: dict[str, list[dict[str, Any]]]) -> int:
    candidate_pairs = {(str(row.get("user_id") or ""), str(row.get("item_id") or row.get("parent_asin") or "")) for row in rows}
    positives = {(user_id, positive["item_id"]) for user_id, user_rows in label_positives.items() for positive in user_rows}
    return len(candidate_pairs & positives)


def _sources(row: dict[str, Any]) -> list[str]:
    values = row.get("sources")
    if isinstance(values, list):
        sources = [str(value) for value in values if value]
        if sources:
            return sources
    source = _string_value(row, "source", "canonical_source")
    return [source] if source else []


def _primary_source(row: dict[str, Any], sources: list[str]) -> str:
    return _string_value(row, "source", "canonical_source") or (sources[0] if sources else "unknown")


def _string_value(row: dict[str, Any], *fields: str) -> str:
    for field in fields:
        value = row.get(field)
        if value is not None and str(value) != "":
            return str(value)
    return ""


def _rank_value(row: dict[str, Any], fallback: int) -> int:
    try:
        rank = int(row.get("rank", fallback) or fallback)
    except (TypeError, ValueError):
        return fallback
    return rank if rank > 0 else fallback


def _is_positive_label(row: dict[str, Any]) -> bool:
    if "label_binary" in row:
        return int(row.get("label_binary") or 0) == 1
    if "label" in row:
        return int(row.get("label") or 0) == 1
    raise ValueError("label row missing explicit label_binary or label field")


def _label_source(path: Path) -> str:
    name = path.name
    if ".valid" in name or name.startswith("valid"):
        return "valid"
    if ".test" in name or name.startswith("test"):
        return "test"
    return name


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    manifest = build_pool500_diagnostic_oracle_candidates(
        base_candidates_path=Path(args.base_candidates),
        label_paths=[Path(path) for path in args.label],
        output_dir=Path(args.output_dir),
        target_user_manifest_path=Path(args.target_user_manifest) if args.target_user_manifest else None,
        min_positive_overlap=args.min_positive_overlap,
        candidate_pool_size=args.candidate_pool_size,
        output_name=args.output_name,
        manifest_name=args.manifest_name,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
