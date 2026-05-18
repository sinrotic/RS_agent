from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import read_json, write_json
from rs_lab.experiments.recall.run_full_lightweight_recall_e2e import MIN_FREE_BYTES
from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import (
    _enforce_project_venv,
    _existing_ancestor,
    _file_signature,
)

SCHEMA_VERSION = "pool500_all_methods_final_gate_v1"
BASE_DIR = ROOT / "outputs" / "recall" / "pool500_all_methods_representative"
DEFAULT_CUSTOM_INDEX_DIR = BASE_DIR / "custom_index"
DEFAULT_LIGHTWEIGHT_CF_DIR = BASE_DIR / "lightweight_cf_methods"
DEFAULT_SEQUENCE_SESSION_DIR = BASE_DIR / "sequence_session_methods"
DEFAULT_HEAVY_PROBES_DIR = BASE_DIR / "heavy_indexed_probes"
DEFAULT_OUTPUT_DIR = BASE_DIR / "final_gate"
FORBIDDEN_PATH_MARKERS = (
    "amazon_2023_recall_clean_10000",
    "amazon_2023_recall_views_10000",
    "pool1000",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate final all-method representative pool500 gate.")
    parser.add_argument("--custom-index-dir", default=str(DEFAULT_CUSTOM_INDEX_DIR))
    parser.add_argument("--lightweight-cf-dir", default=str(DEFAULT_LIGHTWEIGHT_CF_DIR))
    parser.add_argument("--sequence-session-dir", default=str(DEFAULT_SEQUENCE_SESSION_DIR))
    parser.add_argument("--heavy-probes-dir", default=str(DEFAULT_HEAVY_PROBES_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--min-free-bytes", type=int, default=MIN_FREE_BYTES)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_pool500_all_methods_gate(
    *,
    custom_index_dir: Path = DEFAULT_CUSTOM_INDEX_DIR,
    lightweight_cf_dir: Path = DEFAULT_LIGHTWEIGHT_CF_DIR,
    sequence_session_dir: Path = DEFAULT_SEQUENCE_SESSION_DIR,
    heavy_probes_dir: Path = DEFAULT_HEAVY_PROBES_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    min_free_bytes: int = MIN_FREE_BYTES,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        _enforce_project_venv()

    custom_index_dir = custom_index_dir.resolve()
    lightweight_cf_dir = lightweight_cf_dir.resolve()
    sequence_session_dir = sequence_session_dir.resolve()
    heavy_probes_dir = heavy_probes_dir.resolve()
    output_dir = output_dir.resolve()
    paths = _input_paths(custom_index_dir, lightweight_cf_dir, sequence_session_dir, heavy_probes_dir)
    _precheck(paths, output_dir, min_free_bytes)

    artifacts = {name: read_json(path) for name, path in paths.items()}
    final_method_matrix = _final_method_matrix(artifacts)
    source_audit = _source_audit(paths, artifacts)
    resource_audit = _resource_audit(artifacts)
    promote_stop_gate = _promote_stop_gate(artifacts, final_method_matrix, source_audit, resource_audit)

    output_dir.mkdir(parents=True, exist_ok=False)
    write_json(output_dir / "final_method_matrix.json", final_method_matrix)
    write_json(output_dir / "promote_stop_gate.json", promote_stop_gate)
    write_json(output_dir / "source_audit.json", source_audit)
    write_json(output_dir / "resource_audit.json", resource_audit)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": promote_stop_gate["status"],
        "decision": promote_stop_gate["decision"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "pool500_all_methods_representative_final_gate_recall_only",
        "output_dir": str(output_dir),
        "runtime_seconds": round(perf_counter() - started, 6),
        "project_venv_required": enforce_venv,
        "no_candidate_generation_executed": True,
        "no_full_pool500_executed": True,
        "no_pool1000_generated": True,
        "no_model_training_executed": True,
        "no_ranking_input_modified": True,
        "required_artifacts": {
            "manifest": str(output_dir / "manifest.json"),
            "final_method_matrix": str(output_dir / "final_method_matrix.json"),
            "promote_stop_gate": str(output_dir / "promote_stop_gate.json"),
            "source_audit": str(output_dir / "source_audit.json"),
            "resource_audit": str(output_dir / "resource_audit.json"),
        },
        "input_signatures": {name: _file_signature(path) for name, path in paths.items()},
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _input_paths(
    custom_index_dir: Path,
    lightweight_cf_dir: Path,
    sequence_session_dir: Path,
    heavy_probes_dir: Path,
) -> dict[str, Path]:
    return {
        "custom_manifest": custom_index_dir / "manifest.json",
        "custom_source_audit": custom_index_dir / "source_audit.json",
        "custom_resource_audit": custom_index_dir / "resource_audit.json",
        "lightweight_cf_manifest": lightweight_cf_dir / "manifest.json",
        "lightweight_cf_metrics": lightweight_cf_dir / "method_metrics.json",
        "lightweight_cf_contribution": lightweight_cf_dir / "method_contribution.json",
        "lightweight_cf_source_audit": lightweight_cf_dir / "source_audit.json",
        "lightweight_cf_resource_audit": lightweight_cf_dir / "resource_audit.json",
        "sequence_session_manifest": sequence_session_dir / "manifest.json",
        "sequence_session_metrics": sequence_session_dir / "metrics.json",
        "sequence_session_source_audit": sequence_session_dir / "source_audit.json",
        "sequence_session_resource_audit": sequence_session_dir / "resource_audit.json",
        "heavy_manifest": heavy_probes_dir / "manifest.json",
        "heavy_graph_metrics": heavy_probes_dir / "graph_probe_metrics.json",
        "heavy_mf_metrics": heavy_probes_dir / "mf_probe_metrics.json",
        "heavy_two_tower_metrics": heavy_probes_dir / "two_tower_probe_metrics.json",
        "heavy_source_audit": heavy_probes_dir / "source_audit.json",
        "heavy_resource_audit": heavy_probes_dir / "resource_audit.json",
    }


def _precheck(paths: dict[str, Path], output_dir: Path, min_free_bytes: int) -> None:
    for path in [*paths.values(), output_dir]:
        lowered = str(path).replace("\\", "/").lower()
        if any(marker in lowered for marker in FORBIDDEN_PATH_MARKERS):
            raise ValueError(f"Forbidden all-method gate path marker in {path}")
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing all-method gate inputs: {missing}")
    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    free_bytes = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if free_bytes < min_free_bytes:
        raise RuntimeError(f"D drive free bytes below threshold: {free_bytes} < {min_free_bytes}")


def _final_method_matrix(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    lightweight = artifacts["lightweight_cf_metrics"]
    sequence = artifacts["sequence_session_metrics"]
    graph = artifacts["heavy_graph_metrics"]
    mf = artifacts["heavy_mf_metrics"]
    two_tower = artifacts["heavy_two_tower_metrics"]

    methods = {
        "popular": _candidate_method("lightweight_baseline", lightweight["lightweight_by_source"]["popular"]),
        "category": _candidate_method("lightweight_baseline", lightweight["lightweight_by_source"]["category"]),
        "semantic": _candidate_method("lightweight_baseline", lightweight["lightweight_by_source"]["semantic"]),
        "bounded_itemcf_covisit": _candidate_method("bounded_cf", lightweight["bounded_itemcf_covisit"]),
        "bounded_usercf": _candidate_method("bounded_cf", lightweight["bounded_usercf"]),
        "swing_recall": _candidate_method("sequence_session", sequence["swing_recall"]),
        "session_transition_recall": _candidate_method("sequence_session", sequence["session_transition_recall"]),
        "graph_probe": _probe_method("heavy_probe", graph),
        "mf_probe": _probe_method("heavy_probe", mf),
        "two_tower_probe": _probe_method("heavy_probe", two_tower),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "representative_user_count": artifacts["custom_manifest"].get("representative_user_count"),
        "custom_item_count": artifacts["custom_manifest"].get("custom_item_count"),
        "method_families": {
            "lightweight_baseline": ["popular", "category", "semantic"],
            "bounded_cf": ["bounded_itemcf_covisit", "bounded_usercf"],
            "sequence_session": ["swing_recall", "session_transition_recall"],
            "heavy_probe": ["graph_probe", "mf_probe", "two_tower_probe"],
        },
        "methods": methods,
        "merged_observations": {
            "lightweight_pool500": lightweight["lightweight_pool500"],
            "merged_lightweight_cf": lightweight["merged_lightweight_cf"],
            "merged_sequence_session": sequence["merged_pool500"],
            "lightweight_cf_delta_vs_lightweight": artifacts["lightweight_cf_contribution"],
            "sequence_session_contribution": sequence["contribution"],
        },
    }


def _candidate_method(family: str, metrics: dict[str, Any]) -> dict[str, Any]:
    candidate_rows = metrics.get("candidate_row_count")
    return {
        "family": family,
        "status": "PASS_OBSERVED" if candidate_rows else "PASS_OBSERVED_ZERO_HIT_OR_SPARSE",
        "candidate_generation_executed_upstream": True,
        "candidate_generation_executed_in_final_gate": False,
        "model_training_executed": False,
        "candidate_row_count": candidate_rows,
        "empty_candidate_users": metrics.get("empty_candidate_users"),
        "empty_candidate_rate": metrics.get("empty_candidate_rate"),
        "candidate_hit_users": metrics.get("candidate_hit_users"),
        "recall_at_pool": metrics.get("recall_at_pool"),
        "source_user_coverage": metrics.get("source_user_coverage", {}),
        "source_item_coverage": metrics.get("source_item_coverage", {}),
    }


def _probe_method(family: str, metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "family": family,
        "status": "PASS_FEASIBILITY_PROBE_ONLY",
        "candidate_generation_executed_upstream": False,
        "candidate_generation_executed_in_final_gate": False,
        "model_training_executed": bool(metrics.get("training_executed")),
        "candidate_row_count": None,
        "decision": metrics.get("decision"),
        "probe_type": metrics.get("probe_type"),
    }


def _source_audit(paths: dict[str, Path], artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    forbidden_generation_inputs = artifacts["lightweight_cf_source_audit"].get("forbidden_candidate_generation_inputs", [])
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if _source_rules_pass(artifacts) else "FAIL",
        "final_gate_read_only_inputs": {name: str(path) for name, path in paths.items()},
        "candidate_generation_executed_in_final_gate": False,
        "full_pool500_executed_in_final_gate": False,
        "ranking_executed_in_final_gate": False,
        "model_training_executed_in_final_gate": False,
        "candidate_generation_uses_holdout": False,
        "forbidden_candidate_generation_inputs": forbidden_generation_inputs,
        "evaluation_only_holdout_reads_upstream": {
            "lightweight_cf": artifacts["lightweight_cf_metrics"].get("evaluation_only", {}),
            "sequence_session": artifacts["sequence_session_metrics"].get("evaluation_only", {}),
        },
        "no_10k_source": all(
            audit.get("no_10k_source", True) or audit.get("no_10k", True)
            for audit in _source_audits(artifacts)
        ),
        "no_full_clean_copy": all(audit.get("no_full_clean_copy", True) for audit in _source_audits(artifacts)),
        "custom_index_scope_only": artifacts["lightweight_cf_source_audit"].get("custom_index_scope_only") is True,
        "disabled_outputs": {
            "pool1000": True,
            "ranking": True,
            "ranking_default_input_modified": False,
            "graph_training": True,
            "mf_training": True,
            "two_tower_training": True,
        },
        "source_signatures": {name: _file_signature(path) for name, path in paths.items()},
    }


def _resource_audit(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    lightweight_source = artifacts["lightweight_cf_source_audit"]
    heavy_manifest = artifacts["heavy_manifest"]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if _resource_rules_pass(artifacts) else "FAIL",
        "final_gate_only_reads_compact_json": True,
        "no_dense_user_user_matrix": lightweight_source.get("bounded_usercf", {}).get("no_dense_user_user_matrix") is True,
        "no_full_global_cooccurrence_counter": lightweight_source.get("bounded_itemcf_covisit", {}).get("full_global_cooccurrence_counter") is False,
        "bounded_user_count": artifacts["custom_manifest"].get("representative_user_count"),
        "bounded_item_count": artifacts["custom_manifest"].get("custom_item_count"),
        "candidate_row_counts": {
            "lightweight_cf": artifacts["lightweight_cf_manifest"].get("candidate_row_count"),
            "sequence_session": artifacts["sequence_session_manifest"].get("candidate_row_count"),
            "heavy_probes": None,
        },
        "heavy_probe_boundaries": {
            "candidate_generation_executed": heavy_manifest.get("candidate_generation_executed"),
            "no_model_training_executed": heavy_manifest.get("no_model_training_executed"),
            "no_full_graph_mf_two_tower_training": heavy_manifest.get("no_full_graph_mf_two_tower_training"),
            "pool1000_generated": heavy_manifest.get("pool1000_generated"),
        },
    }


def _promote_stop_gate(
    artifacts: dict[str, dict[str, Any]],
    final_method_matrix: dict[str, Any],
    source_audit: dict[str, Any],
    resource_audit: dict[str, Any],
) -> dict[str, Any]:
    rule_results = _rule_results(artifacts, final_method_matrix, source_audit, resource_audit)
    passed = all(rule["pass"] for rule in rule_results.values())
    decision = "CONTINUATION_ONLY" if passed else "STOP"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "decision": decision,
        "full_pool500_continuation_allowed": passed,
        "allowed_scope": (
            "recall-only full pool500 continuation using approved lightweight, bounded CF, sequence/session, and probe-gated method scopes; "
            "does not replace frozen pool200 ranking input"
        )
        if passed
        else None,
        "ranking_input_replacement_allowed": False,
        "heavy_model_training_allowed_by_this_gate": False,
        "pool1000_allowed": False,
        "reason": "all representative all-method artifacts pass source/resource/isolation gates" if passed else "one or more gate rules failed",
        "rule_results": rule_results,
        "method_family_coverage": final_method_matrix["method_families"],
    }


def _rule_results(
    artifacts: dict[str, dict[str, Any]],
    final_method_matrix: dict[str, Any],
    source_audit: dict[str, Any],
    resource_audit: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    methods = final_method_matrix["methods"]
    return {
        "custom_index_pass": _rule(artifacts["custom_manifest"].get("status") == "PASS", "custom index manifest is PASS"),
        "lightweight_cf_pass": _rule(artifacts["lightweight_cf_manifest"].get("status") == "PASS", "lightweight+CF manifest is PASS"),
        "sequence_session_executed_pass": _rule(
            artifacts["sequence_session_manifest"].get("status") == "EXECUTED_PASS_OBSERVATION_ONLY",
            "sequence/session manifest is EXECUTED_PASS_OBSERVATION_ONLY",
        ),
        "heavy_probes_pass": _rule(artifacts["heavy_manifest"].get("status") == "PASS", "heavy indexed probes manifest is PASS"),
        "all_method_families_present": _rule(
            set(methods) == {
                "popular",
                "category",
                "semantic",
                "bounded_itemcf_covisit",
                "bounded_usercf",
                "swing_recall",
                "session_transition_recall",
                "graph_probe",
                "mf_probe",
                "two_tower_probe",
            },
            "final method matrix covers lightweight, bounded CF, sequence/session, graph, MF, and two_tower families",
        ),
        "source_audit_pass": _rule(source_audit["status"] == "PASS", "source audit passes forbidden-source and read-only checks"),
        "resource_audit_pass": _rule(resource_audit["status"] == "PASS", "resource audit passes bounded-resource checks"),
        "no_candidate_generation_in_gate": _rule(
            not source_audit["candidate_generation_executed_in_final_gate"],
            "final gate only aggregates existing artifacts",
        ),
        "no_heavy_training": _rule(
            all(not artifacts[name].get("training_executed") for name in ("heavy_graph_metrics", "heavy_mf_metrics", "heavy_two_tower_metrics"))
            and artifacts["heavy_manifest"].get("no_model_training_executed") is True,
            "graph/MF/two_tower remain probe-only with no training",
        ),
        "ranking_isolation": _rule(
            artifacts["heavy_manifest"].get("ranking_input_modified") is False
            and artifacts["custom_manifest"].get("disabled_outputs", {}).get("ranking") is True
            and artifacts["lightweight_cf_source_audit"].get("disabled_outputs", {}).get("ranking_default_input_modified") is False,
            "pool500 all-method evidence does not replace or modify ranking input",
        ),
        "no_pool1000": _rule(
            artifacts["heavy_manifest"].get("pool1000_generated") is False
            and artifacts["custom_manifest"].get("disabled_outputs", {}).get("pool1000") is True,
            "pool1000 remains disabled and ungenerated",
        ),
    }


def _source_rules_pass(artifacts: dict[str, dict[str, Any]]) -> bool:
    source_audits = _source_audits(artifacts)
    return all(audit.get("status") in {"PASS", None} for audit in source_audits) and all(
        audit.get("candidate_generation_uses_holdout") is False
        for audit in (artifacts["lightweight_cf_source_audit"], artifacts["custom_manifest"])
    )


def _resource_rules_pass(artifacts: dict[str, dict[str, Any]]) -> bool:
    source = artifacts["lightweight_cf_source_audit"]
    return (
        source.get("bounded_usercf", {}).get("no_dense_user_user_matrix") is True
        and source.get("bounded_itemcf_covisit", {}).get("full_global_cooccurrence_counter") is False
        and artifacts["heavy_manifest"].get("no_full_graph_mf_two_tower_training") is True
    )


def _source_audits(artifacts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        artifacts["custom_source_audit"],
        artifacts["lightweight_cf_source_audit"],
        artifacts["sequence_session_source_audit"],
        artifacts["heavy_source_audit"],
    ]


def _rule(passed: bool, reason: str) -> dict[str, Any]:
    return {"pass": bool(passed), "reason": reason}


def main() -> None:
    args = parse_args()
    manifest = run_pool500_all_methods_gate(
        custom_index_dir=Path(args.custom_index_dir),
        lightweight_cf_dir=Path(args.lightweight_cf_dir),
        sequence_session_dir=Path(args.sequence_session_dir),
        heavy_probes_dir=Path(args.heavy_probes_dir),
        output_dir=Path(args.output_dir),
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
    )
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "decision": manifest["decision"],
                "manifest_path": manifest["required_artifacts"]["manifest"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
