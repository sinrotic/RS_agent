from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.recsys.candidate_merge import load_usercf_recall_sidecar
from rs_lab.experiments.recall.build_full_train_usercf_sidecar import build_full_train_usercf_sidecar
from rs_lab.experiments.recall.build_full_train_usercf_sidecar import _first_unique_items as _method_first_unique_items
from rs_lab.experiments.recall.pool500.common.source_layout import REQUIRED_SOURCE_OUTPUTS, method_output_dir
from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import _file_signature

SCHEMA_VERSION = "pool500_usercf_recall_method_source_v1"
SOURCE = "usercf_recall"
SOURCE_STATUS = "DIAGNOSTIC_ONLY"
INDEX_SCOPE = "FULL_DERIVED_INDEX"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_SOURCE_CONFIG = ROOT / "configs" / "recall" / "full_data_pool500" / SOURCE / "source_config.yaml"
DEFAULT_DATASET_POLICY = ROOT / "configs" / "recall" / "full_data_pool500" / SOURCE / "dataset_policy.yaml"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "recall" / "pool500_method_sources"
EXPECTED_PROJECT_PYTHON = (ROOT / ".venv" / "Scripts" / "python.exe").resolve()
FORBIDDEN_PATH_PARTS = (
    "amazon_2023_recall_clean_10000",
    "amazon_2023_recall_views_10000",
    "clean_10000",
    "pool1000",
)
FORBIDDEN_PATH_TOKENS = {"holdout", "valid", "test", "lopo"}
FORBIDDEN_INPUT_NAMES = (
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
)
FORBIDDEN_SWITCHES = {
    "candidate_generation_allowed": False,
    "ranking_input_replacement_allowed": False,
    "pool1000_allowed": False,
    "promotion_allowed": False,
    "final_pool500_ready_claimed": False,
}
UNDERCOVERAGE_REASONS = {
    "insufficient_positive_items",
    "no_indexed_items_after_hot_drop",
    "no_neighbor_overlap",
    "only_seen_items_after_neighbor_merge",
    "unknown_after_train_only_diagnostics",
}


def build_usercf_recall_method_source(
    *,
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    method_dataset_manifest_path: Path | None = None,
    eligible_user_quality_manifest: Path | None = None,
    output_root: Path | None = None,
    run_id: str | None = None,
    source_config_path: Path = DEFAULT_SOURCE_CONFIG,
    dataset_policy_path: Path = DEFAULT_DATASET_POLICY,
    target_user_limit: int | None = None,
    candidate_top_k_per_user: int | None = None,
    generation_usercf_per_user: int | None = None,
    similar_users_top_k: int | None = None,
    target_batch_size: int | None = None,
    shard_count: int | None = None,
    max_items_per_user: int | None = None,
    max_item_user_freq: int | None = None,
    max_rss_mb: int | None = None,
    min_free_bytes: int = 0,
    min_free_memory_bytes: int = 0,
    overwrite: bool = False,
    resume: bool = False,
    route_ready: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        _enforce_exact_project_python()
    source_config = _load_yaml(source_config_path)
    dataset_policy = _load_yaml(dataset_policy_path)
    _validate_config_contract(source_config, dataset_policy)

    clean_manifest_path = _resolve_repo_path(clean_manifest_path).resolve()
    output_root = _resolve_repo_path(output_root or source_config.get("output_root") or DEFAULT_OUTPUT_ROOT).resolve()
    run_id = run_id or source_config.get("run_id") or _default_run_id()
    output_dir = method_output_dir(output_root, SOURCE, run_id).resolve()
    target_user_limit = int(target_user_limit if target_user_limit is not None else source_config.get("target_user_limit", 500))
    candidate_top_k_per_user = int(candidate_top_k_per_user if candidate_top_k_per_user is not None else source_config.get("candidate_top_k_per_user", 500))
    generation_usercf_per_user = int(
        generation_usercf_per_user
        if generation_usercf_per_user is not None
        else source_config.get("generation_config_overrides", {}).get("usercf_per_user", candidate_top_k_per_user)
    )
    similar_users_top_k = int(similar_users_top_k if similar_users_top_k is not None else source_config.get("similar_users_top_k", 200))
    target_batch_size = int(target_batch_size if target_batch_size is not None else source_config.get("target_batch_size", 50))
    shard_count = int(shard_count if shard_count is not None else source_config.get("shard_count", 16))
    max_items_per_user = int(max_items_per_user if max_items_per_user is not None else source_config.get("max_items_per_user", 80))
    max_item_user_freq = int(max_item_user_freq if max_item_user_freq is not None else source_config.get("max_item_user_freq", 5000))
    max_rss_mb = int(max_rss_mb if max_rss_mb is not None else source_config.get("max_rss_mb", 4096))
    _validate_positive(
        target_user_limit=target_user_limit,
        candidate_top_k_per_user=candidate_top_k_per_user,
        generation_usercf_per_user=generation_usercf_per_user,
        similar_users_top_k=similar_users_top_k,
        target_batch_size=target_batch_size,
        shard_count=shard_count,
        max_items_per_user=max_items_per_user,
        max_item_user_freq=max_item_user_freq,
        max_rss_mb=max_rss_mb,
    )
    method_dataset_manifest_path = _resolve_repo_path(method_dataset_manifest_path).resolve() if method_dataset_manifest_path else None
    if method_dataset_manifest_path is None:
        _precheck_paths(clean_manifest_path, output_dir, eligible_user_quality_manifest, overwrite, resume)
    else:
        _precheck_method_dataset_paths(method_dataset_manifest_path, output_dir, overwrite, resume)
    if output_dir.exists() and not any(output_dir.iterdir()) and not resume:
        output_dir.rmdir()

    if method_dataset_manifest_path is None:
        clean_manifest = read_json(clean_manifest_path)
        train_sequences_path = _resolve_train_sequence_path(clean_manifest_path, clean_manifest)
        _precheck_train_path(train_sequences_path)
        target_diagnostics = _build_train_only_target_diagnostics(
            train_sequences_path,
            max_items_per_user,
            max_item_user_freq,
            target_user_limit=target_user_limit,
            eligible_user_quality_manifest=eligible_user_quality_manifest,
        )
        internal_manifest_path, method_dataset_manifest = _materialize_eligible_manifest(
            clean_manifest_path=clean_manifest_path,
            train_sequences_path=train_sequences_path,
            output_root=output_root,
            run_id=run_id,
            target_user_limit=target_user_limit,
            eligible_user_quality_manifest=eligible_user_quality_manifest,
            target_diagnostics=target_diagnostics,
            source_config_path=source_config_path,
            dataset_policy_path=dataset_policy_path,
        )
    else:
        input_method_dataset_manifest, train_sequences_path = _resolve_method_dataset_rows(method_dataset_manifest_path)
        target_diagnostics = _build_method_dataset_target_diagnostics(
            train_sequences_path,
            max_items_per_user,
            target_user_limit=target_user_limit,
        )
        internal_manifest_path, method_dataset_manifest = _materialize_method_dataset_input_manifest(
            method_dataset_manifest_path=method_dataset_manifest_path,
            method_dataset_rows_path=train_sequences_path,
            input_method_dataset_manifest=input_method_dataset_manifest,
            output_root=output_root,
            run_id=run_id,
            target_user_limit=target_user_limit,
            target_diagnostics=target_diagnostics,
            source_config_path=source_config_path,
            dataset_policy_path=dataset_policy_path,
        )
    if route_ready:
        _validate_route_ready_scope(method_dataset_manifest_path, method_dataset_manifest)

    core_manifest = build_full_train_usercf_sidecar(
        clean_manifest=clean_manifest_path,
        output_dir=output_dir,
        eligible_user_quality_manifest=internal_manifest_path if method_dataset_manifest_path is None else None,
        method_dataset_manifest=method_dataset_manifest_path,
        include_medium_behavior=False,
        max_items_per_user=max_items_per_user,
        max_item_user_freq=max_item_user_freq,
        similar_users_top_k=similar_users_top_k,
        candidate_top_k_per_user=candidate_top_k_per_user,
        shard_count=shard_count,
        target_user_limit=target_user_limit,
        target_batch_size=target_batch_size,
        min_free_bytes=min_free_bytes,
        min_free_memory_bytes=min_free_memory_bytes,
        max_rss_mb=max_rss_mb,
        resume=resume,
        overwrite=overwrite,
        enforce_venv=False,
    )
    candidate_stats = _export_flat_candidates(output_dir, core_manifest)
    resource_audit = read_json(output_dir / "resource_audit.json")
    coverage_audit = _coverage_audit(
        candidate_stats=candidate_stats,
        target_user_ids=method_dataset_manifest["target_user_ids"],
        method_dataset_manifest=method_dataset_manifest,
        resource_audit=resource_audit,
    )
    undercoverage_audit = _undercoverage_audit(
        candidate_stats=candidate_stats,
        target_user_ids=method_dataset_manifest["target_user_ids"],
        target_diagnostics=target_diagnostics,
        max_item_user_freq=max_item_user_freq,
        candidate_cap=candidate_top_k_per_user,
    )
    final_manifest = _final_source_index_manifest(
        output_dir=output_dir,
        run_id=run_id,
        clean_manifest_path=clean_manifest_path,
        train_sequences_path=train_sequences_path,
        eligible_manifest_path=internal_manifest_path,
        core_manifest=core_manifest,
        method_dataset_manifest=method_dataset_manifest,
        candidate_stats=candidate_stats,
        coverage_audit=coverage_audit,
        candidate_top_k_per_user=candidate_top_k_per_user,
        generation_usercf_per_user=generation_usercf_per_user,
        similar_users_top_k=similar_users_top_k,
        target_batch_size=target_batch_size,
        shard_count=shard_count,
        max_items_per_user=max_items_per_user,
        max_item_user_freq=max_item_user_freq,
        max_rss_mb=max_rss_mb,
        runtime_seconds=round(perf_counter() - started, 6),
        route_ready=route_ready,
    )
    if route_ready:
        _validate_route_ready_outputs(output_dir, final_manifest)
    _copy_internal_eligible_manifest(internal_manifest_path, output_dir)
    write_json(output_dir / "coverage_audit.json", coverage_audit)
    write_json(output_dir / "undercoverage_audit.json", undercoverage_audit)
    write_json(output_dir / "source_index_manifest.json", final_manifest)
    method_dataset_manifest["source_index_manifest_sha256"] = _file_signature(output_dir / "source_index_manifest.json")["sha256"]
    write_json(output_dir / "method_dataset_manifest.json", method_dataset_manifest)
    _write_readiness_contract(output_dir, final_manifest, route_ready=route_ready)
    load_usercf_recall_sidecar(output_dir / "source_index_manifest.json")
    return {
        **final_manifest,
        "required_outputs_present": {name: (output_dir / name).is_file() for name in REQUIRED_SOURCE_OUTPUTS},
        "coverage_audit": coverage_audit,
        "undercoverage_audit": undercoverage_audit,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build pool500 train-only diagnostic UserCF method-source artifacts.")
    parser.add_argument("--clean-manifest", type=Path, default=DEFAULT_CLEAN_MANIFEST)
    parser.add_argument("--method-dataset-manifest", type=Path, default=None)
    parser.add_argument("--eligible-user-quality-manifest", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--source-config", type=Path, default=DEFAULT_SOURCE_CONFIG)
    parser.add_argument("--dataset-policy", type=Path, default=DEFAULT_DATASET_POLICY)
    parser.add_argument("--target-user-limit", type=int, default=None)
    parser.add_argument("--candidate-top-k-per-user", type=int, default=None)
    parser.add_argument("--generation-usercf-per-user", type=int, default=None)
    parser.add_argument("--similar-users-top-k", type=int, default=None)
    parser.add_argument("--target-batch-size", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--route-ready", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_usercf_recall_method_source(
        clean_manifest_path=args.clean_manifest,
        method_dataset_manifest_path=args.method_dataset_manifest,
        eligible_user_quality_manifest=args.eligible_user_quality_manifest,
        output_root=args.output_root,
        run_id=args.run_id,
        source_config_path=args.source_config,
        dataset_policy_path=args.dataset_policy,
        target_user_limit=args.target_user_limit,
        candidate_top_k_per_user=args.candidate_top_k_per_user,
        generation_usercf_per_user=args.generation_usercf_per_user,
        similar_users_top_k=args.similar_users_top_k,
        target_batch_size=args.target_batch_size,
        overwrite=args.overwrite,
        resume=args.resume,
        route_ready=args.route_ready,
        enforce_venv=True,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def _enforce_exact_project_python() -> None:
    executable = Path(sys.executable).resolve()
    if executable != EXPECTED_PROJECT_PYTHON:
        raise RuntimeError(f"Project Python required: {EXPECTED_PROJECT_PYTHON}; got {executable}")


def _load_yaml(path: Path) -> dict[str, Any]:
    resolved = _resolve_repo_path(path)
    if not resolved.is_file():
        return {}
    import yaml

    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _validate_config_contract(source_config: dict[str, Any], dataset_policy: dict[str, Any]) -> None:
    for payload_name, payload in (("source_config", source_config), ("dataset_policy", dataset_policy)):
        if payload and payload.get("source") != SOURCE:
            raise ValueError(f"{payload_name}.source must be {SOURCE}")
    governance = dataset_policy.get("governance", {}) if isinstance(dataset_policy.get("governance"), dict) else {}
    source_governance = source_config.get("governance", {}) if isinstance(source_config.get("governance"), dict) else {}
    for key, expected in FORBIDDEN_SWITCHES.items():
        if key in governance and governance[key] is not expected:
            raise ValueError(f"dataset_policy.governance.{key} must be false")
        if key in source_governance and source_governance[key] is not expected:
            raise ValueError(f"source_config.governance.{key} must be false")


def _validate_positive(**values: int) -> None:
    for name, value in values.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive")


def _precheck_paths(clean_manifest_path: Path, output_dir: Path, eligible_manifest: Path | None, overwrite: bool, resume: bool) -> None:
    if overwrite and resume:
        raise ValueError("--overwrite and --resume cannot be used together")
    for path in (clean_manifest_path, output_dir, eligible_manifest):
        if path is None:
            continue
        _precheck_input_path(path)
    if not clean_manifest_path.is_file():
        raise FileNotFoundError(clean_manifest_path)
    if eligible_manifest is not None and not _resolve_repo_path(eligible_manifest).is_file():
        raise FileNotFoundError(eligible_manifest)


def _precheck_method_dataset_paths(method_dataset_manifest_path: Path, output_dir: Path, overwrite: bool, resume: bool) -> None:
    if overwrite and resume:
        raise ValueError("--overwrite and --resume cannot be used together")
    _precheck_input_path(method_dataset_manifest_path)
    _precheck_input_path(output_dir)
    if not method_dataset_manifest_path.is_file():
        raise FileNotFoundError(method_dataset_manifest_path)


def _precheck_input_path(path: Path) -> None:
    lowered = str(path).replace("\\", "/").lower()
    if any(part in lowered for part in FORBIDDEN_PATH_PARTS):
        raise ValueError(f"Forbidden holdout/10k/pool1000 path is not allowed: {path}")
    tokens = {token for token in lowered.replace("-", "_").replace(".", "_").split("/") if token}
    if tokens & FORBIDDEN_PATH_TOKENS:
        raise ValueError(f"Forbidden holdout/valid/test/LOPO/oracle/eval path is not allowed: {path}")


def _precheck_train_path(train_sequences_path: Path) -> None:
    lowered = str(train_sequences_path).replace("\\", "/").lower()
    _precheck_input_path(train_sequences_path)
    if any(name in lowered for name in FORBIDDEN_INPUT_NAMES):
        raise ValueError(f"Forbidden non-train input is not allowed: {train_sequences_path}")
    if train_sequences_path.name != "user_sequences.train.jsonl":
        raise ValueError(f"UserCF method source must read user_sequences.train.jsonl, got {train_sequences_path.name}")
    if not train_sequences_path.is_file():
        raise FileNotFoundError(train_sequences_path)


def _resolve_train_sequence_path(clean_manifest_path: Path, manifest_payload: dict[str, Any]) -> Path:
    candidates = [
        manifest_payload.get("train_user_sequences_path"),
        manifest_payload.get("user_sequences_train_path"),
        manifest_payload.get("user_sequences", {}).get("train") if isinstance(manifest_payload.get("user_sequences"), dict) else None,
    ]
    for candidate in candidates:
        if candidate:
            path = Path(str(candidate))
            if path.is_absolute():
                return path.resolve()
            root_candidate = (ROOT / path).resolve()
            if root_candidate.exists():
                return root_candidate
            return (clean_manifest_path.parent / path).resolve()
    return (clean_manifest_path.parent / "user_sequences.train.jsonl").resolve()


def _resolve_method_dataset_rows(manifest_path: Path) -> tuple[dict[str, Any], Path]:
    payload = read_json(manifest_path)
    if payload.get("status") != "PASS":
        raise ValueError("method_dataset_manifest.status must be PASS")
    if payload.get("schema_version") != "pool500_method_dataset_v1":
        raise ValueError("method_dataset_manifest.schema_version must be pool500_method_dataset_v1")
    if payload.get("train_only") is not True:
        raise ValueError("method_dataset_manifest.train_only must be true")
    for key, expected in FORBIDDEN_SWITCHES.items():
        if key in payload and payload.get(key) is not expected:
            raise ValueError(f"method_dataset_manifest.{key} must be false")
    if payload.get("source_method") != "usercf_method_dataset":
        raise ValueError("method_dataset_manifest.source_method must be usercf_method_dataset")
    outputs = payload.get("outputs") if isinstance(payload.get("outputs"), dict) else {}
    if outputs.get("dataset_schema") != "eligible_user_sequence_v1":
        raise ValueError("method_dataset_manifest.outputs.dataset_schema must be eligible_user_sequence_v1")
    rows_path_raw = outputs.get("dataset_rows_path")
    if not rows_path_raw:
        raise ValueError("method_dataset_manifest.outputs.dataset_rows_path is required")
    rows_path = Path(str(rows_path_raw))
    rows_path = rows_path.resolve() if rows_path.is_absolute() else (manifest_path.parent / rows_path).resolve()
    _precheck_input_path(rows_path)
    if rows_path.name != "method_dataset_rows.jsonl":
        raise ValueError(f"method_dataset rows file must be method_dataset_rows.jsonl, got {rows_path.name}")
    if not rows_path.is_file():
        raise FileNotFoundError(rows_path)
    return payload, rows_path


def _build_train_only_target_diagnostics(
    train_sequences_path: Path,
    max_items_per_user: int,
    max_item_user_freq: int,
    *,
    target_user_limit: int,
    eligible_user_quality_manifest: Path | None,
) -> dict[str, Any]:
    external_target_ids = _external_target_user_ids(eligible_user_quality_manifest, target_user_limit)
    external_target_set = set(external_target_ids or [])
    candidates: list[tuple[int, int, str, int, dict[str, Any]]] | list[dict[str, Any]] = []
    raw_user_count = 0
    raw_item_count = 0
    matched_external_targets = 0
    preselection_limit = max(target_user_limit, target_user_limit * 10)

    for row in iter_jsonl(train_sequences_path):
        user_id = str(row.get("user_id") or "")
        raw_items = row.get("recent_positive_item_sequence", []) or []
        if not user_id or not isinstance(raw_items, list):
            continue
        raw_user_count += 1
        if external_target_ids is not None and user_id not in external_target_set:
            continue
        items = _recent_unique_items(raw_items, max_items_per_user)
        raw_item_count += len(items)
        profile = {
            "user_id": user_id,
            "positive_count": len(raw_items),
            "unique_item_count": len(set(str(item) for item in raw_items if str(item))),
            "indexed_items": items,
        }
        if external_target_ids is not None:
            candidates.append(profile)
            matched_external_targets += 1
            if matched_external_targets >= len(external_target_set):
                break
        else:
            _push_candidate_profile(candidates, profile, preselection_limit, raw_user_count)

    if external_target_ids is not None:
        candidates_by_id = {str(profile["user_id"]): profile for profile in candidates}
        selected_candidates = [candidates_by_id[user_id] for user_id in external_target_ids if user_id in candidates_by_id]
    else:
        selected_candidates = [entry[4] for entry in heapq.nlargest(target_user_limit, candidates)]
    users: dict[str, dict[str, Any]] = {}
    indexed_after_hot: dict[str, list[str]] = {}
    overlap_potential: dict[str, int] = {}
    selected_candidates.sort(key=lambda profile: (-int(profile["positive_count"]), -int(profile["unique_item_count"]), str(profile["user_id"])))
    for profile in selected_candidates[:target_user_limit]:
        user_id = str(profile.pop("user_id"))
        kept_items = list(profile["indexed_items"])
        users[user_id] = profile
        indexed_after_hot[user_id] = kept_items
        overlap_potential[user_id] = len(kept_items)
    return {
        "users": users,
        "hot_items": [],
        "indexed_items_after_hot_drop": indexed_after_hot,
        "overlap_potential": overlap_potential,
        "raw_user_count": raw_user_count,
        "raw_item_count": raw_item_count,
    }


def _build_method_dataset_target_diagnostics(
    method_dataset_rows_path: Path,
    max_items_per_user: int,
    *,
    target_user_limit: int,
) -> dict[str, Any]:
    users: dict[str, dict[str, Any]] = {}
    indexed_after_hot: dict[str, list[str]] = {}
    overlap_potential: dict[str, int] = {}
    dropped_reason_counts: Counter[str] = Counter()
    raw_user_count = 0
    raw_item_count = 0
    empty_history_count = 0
    for row in iter_jsonl(method_dataset_rows_path):
        user_id = str(row.get("user_id") or "").strip()
        raw_items = row.get("eligible_item_sequence")
        if not user_id:
            dropped_reason_counts["missing_user_id"] += 1
            continue
        if not isinstance(raw_items, list):
            dropped_reason_counts["missing_or_invalid_eligible_item_sequence"] += 1
            continue
        raw_user_count += 1
        items, dropped = _method_first_unique_items(raw_items, max_items_per_user)
        dropped_reason_counts.update(dropped)
        raw_item_count += len(items)
        if not items:
            empty_history_count += 1
            dropped_reason_counts["empty_eligible_item_sequence"] += 1
        users[user_id] = {
            "positive_count": int(row.get("positive_item_count", len(raw_items)) or len(raw_items)),
            "unique_item_count": len(items),
            "indexed_items": items,
        }
        indexed_after_hot[user_id] = items
        overlap_potential[user_id] = len(items)
        if target_user_limit and raw_user_count >= target_user_limit:
            break
    return {
        "users": users,
        "hot_items": [],
        "indexed_items_after_hot_drop": indexed_after_hot,
        "overlap_potential": overlap_potential,
        "raw_user_count": raw_user_count,
        "raw_item_count": raw_item_count,
        "empty_history_count": empty_history_count,
        "dropped_reason_counts": dict(sorted(dropped_reason_counts.items())),
    }


def _external_target_user_ids(eligible_user_quality_manifest: Path | None, target_user_limit: int) -> list[str] | None:
    if eligible_user_quality_manifest is None:
        return None
    payload = read_json(_resolve_repo_path(eligible_user_quality_manifest).resolve())
    return [str(profile["user_id"]) for profile in _validate_external_eligible_manifest(payload, target_user_limit)]


def _push_candidate_profile(candidates: list[tuple[int, int, str, int, dict[str, Any]]], profile: dict[str, Any], target_user_limit: int, sequence: int) -> None:
    key = (int(profile["positive_count"]), int(profile["unique_item_count"]), _reverse_lex_key(str(profile["user_id"])), -sequence, profile)
    if len(candidates) < target_user_limit:
        heapq.heappush(candidates, key)
    elif key > candidates[0]:
        heapq.heapreplace(candidates, key)


def _reverse_lex_key(value: str) -> str:
    return "".join(chr(0x10FFFF - ord(char)) for char in value)


def _materialize_eligible_manifest(
    *,
    clean_manifest_path: Path,
    train_sequences_path: Path,
    output_root: Path,
    run_id: str,
    target_user_limit: int,
    eligible_user_quality_manifest: Path | None,
    target_diagnostics: dict[str, Any],
    source_config_path: Path,
    dataset_policy_path: Path,
) -> tuple[Path, dict[str, Any]]:
    if eligible_user_quality_manifest is None:
        selected_profiles = _generated_target_profiles(target_diagnostics, target_user_limit)
        source_manifest_path = None
        eligible_profile_count_raw = target_diagnostics["raw_user_count"]
    else:
        source_path = _resolve_repo_path(eligible_user_quality_manifest).resolve()
        payload = read_json(source_path)
        selected_profiles = _validate_external_eligible_manifest(payload, target_user_limit)
        source_manifest_path = source_path
        eligible_profile_count_raw = len(payload.get("profiles", []) or [])
    selected_user_ids = [str(profile["user_id"]) for profile in selected_profiles]
    internal_dir = output_root / "_internal_usercf_eligible_manifests"
    internal_dir.mkdir(parents=True, exist_ok=True)
    internal_manifest_path = internal_dir / f"{run_id}.eligible_user_quality_manifest.json"
    eligible_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.eligible_user_quality_manifest",
        "scope": "target500_train_only_high_cost_slice_users",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "train_only": True,
        **FORBIDDEN_SWITCHES,
        "target_user_limit": target_user_limit,
        "profile_count": len(selected_profiles),
        "profiles": selected_profiles,
    }
    write_json(internal_manifest_path, eligible_manifest)
    method_dataset_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.method_dataset_manifest",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "diagnostic_only": True,
        "index_scope": INDEX_SCOPE,
        "train_only": True,
        **FORBIDDEN_SWITCHES,
        "run_id": run_id,
        "clean_manifest_path": str(clean_manifest_path),
        "train_user_sequences_path": str(train_sequences_path),
        "source_config_path": str(_resolve_repo_path(source_config_path)),
        "dataset_policy_path": str(_resolve_repo_path(dataset_policy_path)),
        "eligible_user_quality_manifest_input": str(source_manifest_path) if source_manifest_path else None,
        "eligible_user_quality_manifest_effective": str(internal_manifest_path),
        "clean_manifest_signature": _file_signature(clean_manifest_path),
        "train_sequence_signature": _file_signature(train_sequences_path),
        "eligible_input_signature": _file_signature(source_manifest_path) if source_manifest_path else None,
        "eligible_profile_count_raw": eligible_profile_count_raw,
        "target_user_limit": target_user_limit,
        "selected_target_user_count": len(selected_user_ids),
        "target_user_count": len(selected_user_ids),
        "target_user_ids": selected_user_ids,
        "selected_user_ids_sha256": _sha256_strings(selected_user_ids),
        "behavior_count_distribution": _behavior_distribution(selected_user_ids, target_diagnostics),
        "no_holdout_evidence": {
            "read_files": [str(train_sequences_path), str(source_manifest_path) if source_manifest_path else None],
            "uses_valid": False,
            "uses_test": False,
            "uses_holdout": False,
            "uses_lopo": False,
            "uses_clean_10000": False,
            "uses_pool1000": False,
        },
        "selection_policy": "external_manifest_capped" if source_manifest_path else "train_only_overlap_potential",
    }
    return internal_manifest_path, method_dataset_manifest


def _materialize_method_dataset_input_manifest(
    *,
    method_dataset_manifest_path: Path,
    method_dataset_rows_path: Path,
    input_method_dataset_manifest: dict[str, Any],
    output_root: Path,
    run_id: str,
    target_user_limit: int,
    target_diagnostics: dict[str, Any],
    source_config_path: Path,
    dataset_policy_path: Path,
) -> tuple[Path, dict[str, Any]]:
    selected_user_ids = list(target_diagnostics["users"])
    selected_profiles = [_eligible_profile(user_id, target_diagnostics["users"][user_id], target_diagnostics["overlap_potential"].get(user_id, 0)) for user_id in selected_user_ids]
    internal_dir = output_root / "_internal_usercf_eligible_manifests"
    internal_dir.mkdir(parents=True, exist_ok=True)
    internal_manifest_path = internal_dir / f"{run_id}.eligible_user_quality_manifest.json"
    eligible_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.eligible_user_quality_manifest",
        "scope": "method_dataset_target_users",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "train_only": True,
        **FORBIDDEN_SWITCHES,
        "target_user_limit": target_user_limit,
        "profile_count": len(selected_profiles),
        "profiles": selected_profiles,
    }
    write_json(internal_manifest_path, eligible_manifest)
    method_dataset_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.method_dataset_manifest",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "diagnostic_only": True,
        "index_scope": INDEX_SCOPE,
        "train_only": True,
        **FORBIDDEN_SWITCHES,
        "run_id": run_id,
        "input_mode": "method_dataset",
        "method_dataset_manifest_input": str(method_dataset_manifest_path),
        "method_dataset_rows_path": str(method_dataset_rows_path),
        "source_config_path": str(_resolve_repo_path(source_config_path)),
        "dataset_policy_path": str(_resolve_repo_path(dataset_policy_path)),
        "eligible_user_quality_manifest_input": None,
        "eligible_user_quality_manifest_effective": str(internal_manifest_path),
        "method_dataset_input_signature": _file_signature(method_dataset_manifest_path),
        "method_dataset_rows_signature": _file_signature(method_dataset_rows_path),
        "eligible_input_signature": None,
        "eligible_profile_count_raw": int(input_method_dataset_manifest.get("user_count", input_method_dataset_manifest.get("row_count", target_diagnostics["raw_user_count"])) or 0),
        "target_user_limit": target_user_limit,
        "selected_target_user_count": len(selected_user_ids),
        "target_user_count": len(selected_user_ids),
        "target_user_ids": selected_user_ids,
        "selected_user_ids_sha256": _sha256_strings(selected_user_ids),
        "behavior_count_distribution": _behavior_distribution(selected_user_ids, target_diagnostics),
        "empty_history_count": target_diagnostics.get("empty_history_count", 0),
        "dropped_reason_counts": target_diagnostics.get("dropped_reason_counts", {}),
        "no_holdout_evidence": {
            "read_files": [str(method_dataset_manifest_path), str(method_dataset_rows_path)],
            "uses_valid": False,
            "uses_test": False,
            "uses_holdout": False,
            "uses_lopo": False,
            "uses_clean_10000": False,
            "uses_pool1000": False,
        },
        "selection_policy": "method_dataset_target_users",
    }
    return internal_manifest_path, method_dataset_manifest


def _generated_target_profiles(target_diagnostics: dict[str, Any], target_user_limit: int) -> list[dict[str, Any]]:
    users = target_diagnostics["users"]
    overlap_potential = target_diagnostics["overlap_potential"]
    ranked = sorted(
        users,
        key=lambda user_id: (
            -int(users[user_id]["positive_count"]),
            -int(users[user_id]["unique_item_count"]),
            -int(overlap_potential.get(user_id, 0)),
            user_id,
        ),
    )[:target_user_limit]
    return [_eligible_profile(user_id, users[user_id], overlap_potential.get(user_id, 0)) for user_id in ranked]


def _validate_external_eligible_manifest(payload: dict[str, Any], target_user_limit: int) -> list[dict[str, Any]]:
    scope = payload.get("scope")
    allowed_scopes = {"target500_train_only_high_cost_slice_users", "diagnostic_limited_train_users"}
    if scope not in allowed_scopes:
        raise ValueError(f"eligible_user_quality_manifest.scope must be one of {sorted(allowed_scopes)}")
    for key in ("train_only",):
        if payload.get(key) is not True:
            raise ValueError(f"eligible_user_quality_manifest.{key} must be true")
    for key, expected in FORBIDDEN_SWITCHES.items():
        if key in payload and payload.get(key) is not expected:
            raise ValueError(f"eligible_user_quality_manifest.{key} must be false")
    profiles = payload.get("profiles")
    if not isinstance(profiles, list):
        raise ValueError("eligible_user_quality_manifest.profiles must be a list")
    selected = []
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        if not _external_profile_usercf_eligible(profile, scope):
            continue
        user_id = str(profile.get("user_id") or "")
        if not user_id:
            continue
        selected.append({**profile, "user_id": user_id, "quality_bucket": "target500_high_cost_slice", "eligible_for_usercf_slice": True})
        if len(selected) >= target_user_limit:
            break
    return selected


def _external_profile_usercf_eligible(profile: dict[str, Any], scope: Any) -> bool:
    if scope == "target500_train_only_high_cost_slice_users":
        return profile.get("quality_bucket") == "target500_high_cost_slice" and profile.get("eligible_for_usercf_slice") is True
    if scope == "diagnostic_limited_train_users":
        if profile.get("eligible_for_usercf") is True:
            return True
        return profile.get("quality_bucket") == "medium_behavior" and int(profile.get("shared_item_neighbor_count", 0) or 0) > 0
    return False


def _eligible_profile(user_id: str, user_stats: dict[str, Any], overlap_potential: int) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "quality_bucket": "target500_high_cost_slice",
        "eligible_for_usercf_slice": True,
        "positive_count": user_stats["positive_count"],
        "unique_item_count": user_stats["unique_item_count"],
        "train_only_overlap_potential": overlap_potential,
    }


def _export_flat_candidates(output_dir: Path, core_manifest: dict[str, Any]) -> dict[str, Any]:
    candidate_shards = core_manifest.get("outputs", {}).get("candidate_shards") or []
    candidates_path = output_dir / "candidates.jsonl"
    candidate_counts: dict[str, int] = Counter()
    candidate_row_count = 0
    with candidates_path.open("w", encoding="utf-8") as out:
        for shard_path in candidate_shards:
            for row in iter_jsonl(_resolve_manifest_path(output_dir / "source_index_manifest.json", shard_path)):
                user_id = str(row.get("user_id") or "")
                for candidate in row.get("candidates", []) or []:
                    flat = {
                        "user_id": user_id,
                        "item_id": str(candidate.get("item_id") or ""),
                        "score": float(candidate.get("score", 0.0) or 0.0),
                        "rank": int(candidate.get("rank", candidate_counts[user_id] + 1) or candidate_counts[user_id] + 1),
                        "source": SOURCE,
                        "canonical_source": SOURCE,
                    }
                    out.write(json.dumps(flat, ensure_ascii=False, sort_keys=True) + "\n")
                    candidate_counts[user_id] += 1
                    candidate_row_count += 1
    counts = list(candidate_counts.values())
    return {
        "candidates_path": str(candidates_path),
        "candidate_row_count": candidate_row_count,
        "user_coverage_count": len(candidate_counts),
        "candidate_counts_by_user": dict(candidate_counts),
        "candidate_count_stats": _count_stats(counts),
        "candidate_signature": _file_signature(candidates_path),
    }


def _coverage_audit(candidate_stats: dict[str, Any], target_user_ids: list[str], method_dataset_manifest: dict[str, Any], resource_audit: dict[str, Any]) -> dict[str, Any]:
    old_candidate_row_count = 8364
    old_user_coverage_count = 290
    target_user_count = len(target_user_ids)
    return {
        "schema_version": f"{SCHEMA_VERSION}.coverage_audit",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "diagnostic_only": True,
        "index_scope": INDEX_SCOPE,
        "train_only": True,
        **FORBIDDEN_SWITCHES,
        "target_user_count": target_user_count,
        "candidate_row_count": candidate_stats["candidate_row_count"],
        "user_coverage_count": candidate_stats["user_coverage_count"],
        "candidate_count_stats": candidate_stats["candidate_count_stats"],
        "behavior_count_distribution": method_dataset_manifest["behavior_count_distribution"],
        "neighbor_edge_checks": resource_audit.get("neighbor_edge_checks", 0),
        "similar_user_links_used": resource_audit.get("similar_user_links_used", 0),
        "neighbor_count_distribution": _batch_distribution(resource_audit, "similar_user_links_used"),
        "overlap_count_distribution": _batch_distribution(resource_audit, "neighbor_edge_checks"),
        "dropped_hot_item_count": resource_audit.get("dropped_hot_item_count", 0),
        "old_promoted_baseline": {
            "candidate_row_count": old_candidate_row_count,
            "user_coverage_count": old_user_coverage_count,
            "coverage": "290/500",
        },
        "new_vs_old_delta": {
            "candidate_row_count_delta": candidate_stats["candidate_row_count"] - old_candidate_row_count,
            "user_coverage_count_delta": candidate_stats["user_coverage_count"] - old_user_coverage_count,
        },
    }


def _undercoverage_audit(candidate_stats: dict[str, Any], target_user_ids: list[str], target_diagnostics: dict[str, Any], max_item_user_freq: int, candidate_cap: int) -> dict[str, Any]:
    counts_by_user = candidate_stats["candidate_counts_by_user"]
    users = target_diagnostics["users"]
    indexed_after_hot = target_diagnostics["indexed_items_after_hot_drop"]
    overlap_potential = target_diagnostics["overlap_potential"]
    rows = []
    reason_counts: Counter[str] = Counter()
    for user_id in target_user_ids:
        candidate_count = int(counts_by_user.get(user_id, 0))
        if candidate_count >= candidate_cap:
            continue
        user_stats = users.get(user_id, {})
        reason = _undercoverage_reason(user_id, user_stats, indexed_after_hot, overlap_potential, candidate_count)
        reason_counts[reason] += 1
        rows.append(
            {
                "user_id": user_id,
                "candidate_count": candidate_count,
                "target_candidate_cap": candidate_cap,
                "reason": reason,
                "candidate_cap_exhausted": candidate_count >= candidate_cap,
                "positive_count": user_stats.get("positive_count", 0),
                "unique_item_count": user_stats.get("unique_item_count", 0),
                "indexed_item_count_after_hot_drop": len(indexed_after_hot.get(user_id, []) or []),
                "train_only_overlap_potential": overlap_potential.get(user_id, 0),
            }
        )
    invalid = set(reason_counts) - UNDERCOVERAGE_REASONS
    if invalid:
        raise ValueError(f"Unsupported undercoverage reasons: {sorted(invalid)}")
    return {
        "schema_version": f"{SCHEMA_VERSION}.undercoverage_audit",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "diagnostic_only": True,
        "index_scope": INDEX_SCOPE,
        "train_only": True,
        **FORBIDDEN_SWITCHES,
        "target_user_count": len(target_user_ids),
        "undercovered_user_count": len(rows),
        "candidate_cap": candidate_cap,
        "max_item_user_freq": max_item_user_freq,
        "reason_counts": dict(sorted(reason_counts.items())),
        "users": rows,
    }


def _undercoverage_reason(user_id: str, user_stats: dict[str, Any], indexed_after_hot: dict[str, list[str]], overlap_potential: dict[str, int], candidate_count: int) -> str:
    if not user_stats or int(user_stats.get("positive_count", 0)) <= 1:
        return "insufficient_positive_items"
    if not indexed_after_hot.get(user_id):
        return "no_indexed_items_after_hot_drop"
    if int(overlap_potential.get(user_id, 0)) <= 0:
        return "no_neighbor_overlap"
    if candidate_count == 0:
        return "only_seen_items_after_neighbor_merge"
    return "unknown_after_train_only_diagnostics"


def _final_source_index_manifest(
    *,
    output_dir: Path,
    run_id: str,
    clean_manifest_path: Path,
    train_sequences_path: Path,
    eligible_manifest_path: Path,
    core_manifest: dict[str, Any],
    method_dataset_manifest: dict[str, Any],
    candidate_stats: dict[str, Any],
    coverage_audit: dict[str, Any],
    candidate_top_k_per_user: int,
    generation_usercf_per_user: int,
    similar_users_top_k: int,
    target_batch_size: int,
    shard_count: int,
    max_items_per_user: int,
    max_item_user_freq: int,
    max_rss_mb: int,
    runtime_seconds: float,
    route_ready: bool = False,
) -> dict[str, Any]:
    outputs = core_manifest.get("outputs", {}) if isinstance(core_manifest.get("outputs"), dict) else {}
    source_status = "READY" if route_ready else SOURCE_STATUS
    final_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.source_index_manifest",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": source_status,
        "diagnostic_only": not route_ready,
        "index_scope": INDEX_SCOPE,
        "train_only": True,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(output_dir),
        "clean_manifest_path": str(clean_manifest_path),
        "train_user_sequences_path": str(train_sequences_path),
        "eligible_user_quality_manifest": str(eligible_manifest_path),
        "target_user_limit": method_dataset_manifest["target_user_limit"],
        "target_user_count": method_dataset_manifest["selected_target_user_count"],
        "candidate_user_count": candidate_stats["user_coverage_count"],
        "candidate_total_count": candidate_stats["candidate_row_count"],
        "candidate_row_count": candidate_stats["candidate_row_count"],
        "row_count": candidate_stats["candidate_row_count"],
        "user_coverage_count": candidate_stats["user_coverage_count"],
        "candidate_count_stats": candidate_stats["candidate_count_stats"],
        "coverage_audit_summary": {
            "old_candidate_row_count": coverage_audit["old_promoted_baseline"]["candidate_row_count"],
            "old_user_coverage_count": coverage_audit["old_promoted_baseline"]["user_coverage_count"],
            "candidate_row_count_delta": coverage_audit["new_vs_old_delta"]["candidate_row_count_delta"],
            "user_coverage_count_delta": coverage_audit["new_vs_old_delta"]["user_coverage_count_delta"],
        },
        "generation_config_overrides": {"usercf_per_user": generation_usercf_per_user},
        "config_caps": {
            "candidate_top_k_per_user": candidate_top_k_per_user,
            "similar_users_top_k": similar_users_top_k,
            "target_batch_size": target_batch_size,
            "shard_count": shard_count,
            "max_items_per_user": max_items_per_user,
            "max_item_user_freq": max_item_user_freq,
            "max_rss_mb": max_rss_mb,
        },
        **FORBIDDEN_SWITCHES,
        "outputs": {
            "candidate_shards": outputs.get("candidate_shards", []),
            "method_dataset_manifest": str(output_dir / "method_dataset_manifest.json"),
            "source_index_manifest": str(output_dir / "source_index_manifest.json"),
            "candidates": str(output_dir / "candidates.jsonl"),
            "coverage_audit": str(output_dir / "coverage_audit.json"),
            "undercoverage_audit": str(output_dir / "undercoverage_audit.json"),
            "resource_audit": str(output_dir / "resource_audit.json"),
            "no_holdout_audit": str(output_dir / "no_holdout_audit.json"),
        },
        "runtime_seconds": runtime_seconds,
    }
    return final_manifest


def _write_readiness_contract(output_dir: Path, final_manifest: dict[str, Any], *, route_ready: bool = False) -> None:
    manifest_path = output_dir / "source_index_manifest.json"
    signature = _file_signature(manifest_path)
    source_status = "READY" if route_ready else SOURCE_STATUS
    payload = {
        "schema_version": f"{SCHEMA_VERSION}.readiness_contract",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "status": source_status,
        "source_status": source_status,
        "diagnostic_only": not route_ready,
        "index_status": "INDEX_READY",
        "diagnostic_output_status": "DIAGNOSTIC_OUTPUT_READY" if not route_ready else None,
        "full_output_status": "FULL_OUTPUT_READY" if route_ready else None,
        "index_scope": INDEX_SCOPE,
        "train_only": True,
        **FORBIDDEN_SWITCHES,
        "manifest_path": str(output_dir / "readiness_contract.json"),
        "index_manifest_path": str(manifest_path),
        "index_manifest_signature": signature,
        "index_manifest_sha256": signature["sha256"],
        "target_user_count": final_manifest["target_user_count"],
        "candidate_user_count": final_manifest["candidate_user_count"],
        "candidate_total_count": final_manifest["candidate_total_count"],
        "candidate_row_count": final_manifest["candidate_row_count"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    payload["manifest_sha256"] = _canonical_sha256(payload)
    write_json(output_dir / "readiness_contract.json", payload)


def _validate_route_ready_scope(method_dataset_manifest_path: Path | None, method_dataset_manifest: dict[str, Any]) -> None:
    if method_dataset_manifest_path is None:
        raise ValueError("route-ready UserCF requires method_dataset input")
    if method_dataset_manifest.get("input_mode") != "method_dataset":
        raise ValueError("route-ready UserCF requires method_dataset input_mode")
    if method_dataset_manifest.get("train_only") is not True:
        raise ValueError("route-ready UserCF requires train_only method dataset")
    target_count = int(method_dataset_manifest.get("target_user_count") or 0)
    selected_count = int(method_dataset_manifest.get("selected_target_user_count") or 0)
    if target_count <= 0 or selected_count != target_count:
        raise ValueError("route-ready UserCF requires full formal target scope")


def _validate_route_ready_outputs(output_dir: Path, final_manifest: dict[str, Any]) -> None:
    no_holdout_path = output_dir / "no_holdout_audit.json"
    if not no_holdout_path.is_file():
        raise FileNotFoundError(no_holdout_path)
    no_holdout = read_json(no_holdout_path)
    if no_holdout.get("status") != "PASS":
        raise ValueError("route-ready UserCF requires PASS no_holdout_audit")
    shard_paths = final_manifest.get("outputs", {}).get("candidate_shards", [])
    if not shard_paths or any(not Path(path).is_file() for path in shard_paths):
        raise ValueError("route-ready UserCF requires loadable candidate shards")
    if int(final_manifest.get("candidate_row_count") or 0) <= 0:
        raise ValueError("route-ready UserCF requires non-empty candidates")


def _copy_internal_eligible_manifest(internal_manifest_path: Path, output_dir: Path) -> None:
    destination = output_dir / "eligible_user_quality_manifest.json"
    if internal_manifest_path.resolve() != destination.resolve():
        shutil.copyfile(internal_manifest_path, destination)


def _batch_distribution(resource_audit: dict[str, Any], key: str) -> dict[str, Any]:
    values = [int(batch.get(key, 0)) for batch in resource_audit.get("batches", []) if isinstance(batch, dict)]
    return _count_stats(values)


def _behavior_distribution(user_ids: list[str], target_diagnostics: dict[str, Any]) -> dict[str, Any]:
    users = target_diagnostics["users"]
    positive_counts = [int(users.get(user_id, {}).get("positive_count", 0)) for user_id in user_ids]
    unique_counts = [int(users.get(user_id, {}).get("unique_item_count", 0)) for user_id in user_ids]
    overlap_counts = [int(target_diagnostics["overlap_potential"].get(user_id, 0)) for user_id in user_ids]
    return {
        "positive_count": _count_stats(positive_counts),
        "unique_item_count": _count_stats(unique_counts),
        "train_only_overlap_potential": _count_stats(overlap_counts),
    }


def _count_stats(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"min": 0, "p50": 0, "p90": 0, "max": 0}
    ordered = sorted(int(value) for value in values)
    return {
        "min": ordered[0],
        "p50": int(median(ordered)),
        "p90": ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))],
        "max": ordered[-1],
    }


def _recent_unique_items(raw_items: list[Any], max_items_per_user: int) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for item in reversed(raw_items[-max_items_per_user:]):
        item_id = str(item)
        if item_id and item_id not in seen:
            seen.add(item_id)
            items.append(item_id)
    items.reverse()
    return items


def _resolve_manifest_path(manifest_path: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (manifest_path.parent / path).resolve()


def _resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256_strings(values: list[str]) -> str:
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _canonical_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    main()
