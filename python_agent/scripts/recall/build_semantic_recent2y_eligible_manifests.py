from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_RECENT_DIR = ROOT / "data" / "processed" / "amazon_2023_recall_recent_2y_1m_3m"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "recall" / "pool500_method_sources_newdata"

SMOKE_QUOTAS = {
    "collaborative_rich": 40,
    "sequence_sufficient": 100,
    "fallback_only": 50,
    "cold_start": 10,
}
FORMAL_QUOTAS = {
    "collaborative_rich": 10_000,
    "sequence_sufficient": 30_000,
    "fallback_only": 10_000,
}
AUDIT_ONLY_LIMITS = {
    "medium_behavior": 90,
}
FORBIDDEN_SCOPES = [
    "valid",
    "test",
    "holdout",
    "LOPO",
    "oracle",
    "eval_label",
    "clean_10000",
    "pool1000",
]
INPUT_CONTRACT = {
    "train_only": True,
    "valid_used": False,
    "test_used": False,
    "holdout_used": False,
    "lopo_used": False,
    "oracle_used": False,
    "eval_label_used": False,
    "ranking_input_replacement_allowed": False,
    "promotion_allowed": False,
    "pool1000_allowed": False,
    "full_pool500_ready_declared": False,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build recent2y train-only eligible user manifests for semantic direct recall tiers."
    )
    parser.add_argument("--recent-dir", type=Path, default=DEFAULT_RECENT_DIR)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_manifests(recent_dir=args.recent_dir, output_root=args.output_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def build_manifests(*, recent_dir: Path, output_root: Path) -> dict[str, Any]:
    recent_dir = recent_dir.resolve()
    output_root = output_root.resolve()
    clean_manifest_path = recent_dir / "manifest.json"
    recall_views_manifest_path = recent_dir / "recall_views" / "manifest.json"
    governance_manifest_path = recent_dir / "train_only_governance" / "manifest.json"
    user_quality_path = recent_dir / "train_only_governance" / "user_quality_profile.jsonl"

    clean_manifest = _read_json(clean_manifest_path)
    governance_manifest = _read_json(governance_manifest_path)
    recall_views_manifest = _read_json(recall_views_manifest_path)
    profiles = _load_profiles(user_quality_path)

    smoke_manifest = _build_manifest(
        dataset_id="semantic_recent2y_smoke_v1",
        manifest_role="train_only_candidate_generation_target_users_with_cold_start_audit",
        quota_policy=SMOKE_QUOTAS,
        profiles=profiles,
        source_profiled_user_count=int(governance_manifest["quality_bucket_summary"]["profiled_user_count"]),
        source_eligible_bucket_counts=dict(governance_manifest["quality_bucket_summary"]["bucket_counts"]),
        clean_manifest_path=clean_manifest_path,
        recall_views_manifest_path=recall_views_manifest_path,
        governance_manifest_path=governance_manifest_path,
        user_quality_path=user_quality_path,
        clean_manifest=clean_manifest,
        recall_views_manifest=recall_views_manifest,
        selection_notes={
            "tier": "recent2y_smoke",
            "target_user_count": 200,
            "bucket_targets": SMOKE_QUOTAS,
            "cold_start_seed_rule": "include only cold_start users with positive_count>0 and unique_item_count>0; otherwise audit-only shortage",
            "ordering": "user_quality_profile_file_order",
        },
    )
    formal_manifest = _build_manifest(
        dataset_id="semantic_recent2y_formal_v1",
        manifest_role="train_only_candidate_generation_target_users",
        quota_policy=FORMAL_QUOTAS,
        profiles=profiles,
        source_profiled_user_count=int(governance_manifest["quality_bucket_summary"]["profiled_user_count"]),
        source_eligible_bucket_counts=dict(governance_manifest["quality_bucket_summary"]["bucket_counts"]),
        clean_manifest_path=clean_manifest_path,
        recall_views_manifest_path=recall_views_manifest_path,
        governance_manifest_path=governance_manifest_path,
        user_quality_path=user_quality_path,
        clean_manifest=clean_manifest,
        recall_views_manifest=recall_views_manifest,
        selection_notes={
            "tier": "recent2y_formal",
            "target_user_count": 50_000,
            "bucket_targets": FORMAL_QUOTAS,
            "audit_only_buckets": AUDIT_ONLY_LIMITS,
            "excluded_candidate_generation_buckets": ["cold_start", "medium_behavior"],
            "ordering": "user_quality_profile_file_order",
        },
    )
    _attach_audit_only(formal_manifest, profiles, AUDIT_ONLY_LIMITS)

    smoke_path = output_root / "eligible_users_semantic_recent2y_smoke_v1" / "eligible_user_manifest.json"
    formal_path = output_root / "eligible_users_semantic_recent2y_formal_v1" / "eligible_user_manifest.json"
    _write_json(smoke_path, smoke_manifest)
    _write_json(formal_path, formal_manifest)

    return {
        "smoke_eligible_user_manifest": _rel(smoke_path),
        "smoke_eligible_user_count": smoke_manifest["eligible_user_count"],
        "smoke_bucket_counts": smoke_manifest["eligible_user_bucket_counts"],
        "formal_eligible_user_manifest": _rel(formal_path),
        "formal_eligible_user_count": formal_manifest["eligible_user_count"],
        "formal_bucket_counts": formal_manifest["eligible_user_bucket_counts"],
    }


def _load_profiles(user_quality_path: Path) -> dict[str, list[dict[str, Any]]]:
    profiles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with user_quality_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            bucket = str(row.get("quality_bucket_v2") or row.get("quality_bucket") or "")
            if bucket:
                profiles[bucket].append(row)
    return profiles


def _build_manifest(
    *,
    dataset_id: str,
    manifest_role: str,
    quota_policy: dict[str, int],
    profiles: dict[str, list[dict[str, Any]]],
    source_profiled_user_count: int,
    source_eligible_bucket_counts: dict[str, int],
    clean_manifest_path: Path,
    recall_views_manifest_path: Path,
    governance_manifest_path: Path,
    user_quality_path: Path,
    clean_manifest: dict[str, Any],
    recall_views_manifest: dict[str, Any],
    selection_notes: dict[str, Any],
) -> dict[str, Any]:
    eligible_user_buckets: dict[str, list[str]] = {}
    shortage_reason: dict[str, str] = {}
    for bucket, target in quota_policy.items():
        candidates = _candidate_profiles(bucket, profiles.get(bucket, []))
        selected = [str(row["user_id"]) for row in candidates[:target]]
        eligible_user_buckets[bucket] = selected
        if len(selected) < target:
            shortage_reason[bucket] = f"requested {target}, available {len(selected)} under train-only seed policy"

    eligible_user_ids = [user_id for bucket in quota_policy for user_id in eligible_user_buckets[bucket]]
    eligible_user_bucket_counts = {bucket: len(ids) for bucket, ids in eligible_user_buckets.items()}
    generated_at = datetime.now(UTC).isoformat()
    input_contract = {
        **INPUT_CONTRACT,
        "clean_manifest": _rel(clean_manifest_path),
        "recall_views_manifest": _rel(recall_views_manifest_path),
        "train_only_governance_manifest": _rel(governance_manifest_path),
        "user_quality_profile": _rel(user_quality_path),
        "semantic_recall_inputs": _rel(_resolve_repo_path(recall_views_manifest["outputs"]["semantic_recall_inputs"])),
        "semantic_inverted_index": _rel(_resolve_repo_path(recall_views_manifest["outputs"]["semantic_inverted_index"])),
        "use_existing_recall_views_with_audit_first": True,
        "valid_used": False,
        "test_used": False,
        "holdout_used": False,
        "oracle_used": False,
        "eval_label_used": False,
    }
    return {
        "schema_version": "semantic_recent2y_eligible_user_manifest_v1",
        "dataset_id": dataset_id,
        "generated_at": generated_at,
        "manifest_role": manifest_role,
        "source": "semantic",
        "canonical_sources": ["semantic", "semantic_title_category_expansion"],
        "source_profiled_user_count": source_profiled_user_count,
        "source_eligible_bucket_counts": source_eligible_bucket_counts,
        "selection_policy": {
            **selection_notes,
            "train_only": True,
            "quota_policy": quota_policy,
            "candidate_generation_buckets": list(quota_policy),
            "shortage_reason": shortage_reason,
        },
        "eligible_user_buckets": eligible_user_buckets,
        "eligible_user_bucket_counts": eligible_user_bucket_counts,
        "eligible_user_count": len(eligible_user_ids),
        "eligible_user_hash": _hash_lines(eligible_user_ids),
        "eligible_user_ids": eligible_user_ids,
        "input_contract": input_contract,
        "forbidden_scopes": FORBIDDEN_SCOPES,
        "governance": {
            **INPUT_CONTRACT,
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "ranking_replacement_allowed": False,
        },
        "lineage": {
            "source_clean_manifest_sha256": clean_manifest.get("source_signature", {}).get("manifest_sha256"),
            "recall_views_combined_signature": recall_views_manifest.get("source_signature", {}).get("combined_signature"),
            "train_window": clean_manifest.get("window_policy", {}).get("splits", {}).get("train"),
        },
    }


def _candidate_profiles(bucket: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if bucket != "cold_start":
        return rows
    return [
        row
        for row in rows
        if int(row.get("positive_count") or 0) > 0 and int(row.get("unique_item_count") or 0) > 0
    ]


def _attach_audit_only(manifest: dict[str, Any], profiles: dict[str, list[dict[str, Any]]], limits: dict[str, int]) -> None:
    audit_user_buckets = {
        bucket: [str(row["user_id"]) for row in profiles.get(bucket, [])[:limit]]
        for bucket, limit in limits.items()
    }
    manifest["audit_only_user_buckets"] = audit_user_buckets
    manifest["audit_only_user_bucket_counts"] = {bucket: len(ids) for bucket, ids in audit_user_buckets.items()}
    manifest["selection_policy"]["audit_only_buckets"] = limits


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_repo_path(raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else ROOT / path


def _rel(path: Path | str) -> str:
    path = Path(path)
    if path.is_absolute():
        try:
            return path.relative_to(ROOT).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix().replace("\\", "/")


def _hash_lines(values: list[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


if __name__ == "__main__":
    main()
