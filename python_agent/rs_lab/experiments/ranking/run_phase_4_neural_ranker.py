from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import read_jsonl, write_json
from rs_core.offline.evaluation.ranking import build_ranking_experiment_registry_entry, build_ranking_feature_contract, build_ranking_gpu_resource_summary, build_ranking_method_registry_entry, compare_frozen_candidate_signatures, inspect_ranking_run_artifacts
from rs_core.workflow.hybrid_demo import run_hybrid_demo
from rs_lab.experiments.ranking.run_phase_1_23_pool200_ranking_isolation import FREEZE_FIELDS, _status_and_drift
from rs_lab.experiments.ranking.run_phase_1_28_lightweight_learned_ranker import LTR_FEATURE_CONFIG, _public_training_result, train_ltr_ranker

_PHASE = "phase_4_neural_ranker"
_BASELINE_VARIANT = "same_run_baseline"
BASELINE_CONFIG = ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_4_neural_ranker"
MINIMUM_RUNS = 1
REQUIRED_CONSISTENT_RUNS = 1
NEURAL_EPOCHS = 2
NEURAL_BATCH_SIZE = 256
NEURAL_SEED = 17
METRIC_FIELDS = [
    "hit_rate_at_k",
    "ndcg_at_k",
    "mrr_at_k",
    "map_at_k",
    "candidate_hit_missed_topk_users",
    *FREEZE_FIELDS,
]
NEURAL_METHODS = [
    {"name": "mlp_pointwise_cuda_diagnostic", "method_family": "mlp_ranker", "lane": "diagnostic", "gpu_required": True, "train_kind": "pointwise"},
    {"name": "ranknet_pairwise_cuda_diagnostic", "method_family": "ranknet", "lane": "diagnostic", "gpu_required": True, "train_kind": "pairwise"},
]
BLOCKED_NEURAL_METHODS = [
    {"name": "lambdarank_cuda_diagnostic", "method_family": "lambdarank", "lane": "diagnostic", "reasons": ["listwise_group_objective_not_implemented", "diagnostic_adapter_missing"]},
    {"name": "listnet_listmle_cuda_diagnostic", "method_family": "listwise_neural", "lane": "diagnostic", "reasons": ["listwise_group_objective_not_implemented", "diagnostic_adapter_missing"]},
    {"name": "wide_deep_deepfm_dcn_xdeepfm_cuda_diagnostic", "method_family": "wide_deep_feature_cross", "lane": "diagnostic", "reasons": ["feature_cross_schema_missing", "diagnostic_adapter_missing"]},
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 4 neural ranker diagnostic gates on frozen pool200 candidates.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase 4 artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = run_phase_4_neural_ranker(output_dir=output_dir, limit_users=args.limit_users)
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


def run_phase_4_neural_ranker(output_dir: Path, limit_users: int | None = None) -> dict[str, Any]:
    feature_contract = build_ranking_feature_contract()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    command_text = _command_text(output_dir, limit_users)
    dependency_status = _dependency_status()
    baseline_row = _run_baseline(output_dir, limit_users, feature_contract, run_id, command_text)
    candidate_row_export = _export_neural_candidate_rows(output_dir, limit_users)
    neural_training = _run_neural_diagnostics(output_dir, candidate_row_export, dependency_status)
    return {
        "phase": _PHASE,
        "run_id": run_id,
        "limit_users": limit_users,
        "minimum_runs": MINIMUM_RUNS,
        "required_consistent_runs": REQUIRED_CONSISTENT_RUNS,
        "actual_runs": 1,
        "candidate_pool_size": 200,
        "top_k": 5,
        "baseline_config_path": str(BASELINE_CONFIG),
        "output_dir": str(output_dir),
        "command_text": command_text,
        "dependency_status": dependency_status,
        "candidate_row_export": candidate_row_export,
        "neural_training": neural_training,
        "lanes": {
            "promotion": {"candidate_types": ["baseline"], "promotion_eligible": True},
            "diagnostic": {"candidate_types": ["mlp_ranker", "ranknet", "lambdarank", "listwise_neural", "wide_deep_feature_cross"], "promotion_eligible": False},
        },
        "promotion_policy": {"neural_rankers_are_diagnostic_by_default": True, "promotion_requires_adr_and_serving_adapter": True, "gpu_training_required": True, "valid_test_training_required_for_promotion": True},
        "artifact_inspection": inspect_ranking_run_artifacts([baseline_row]) | {"phase_4_scope": "neural_ranker_diagnostic_training_on_frozen_pool200_candidate_rows"},
        "final_decision": {"selected_route": _BASELINE_VARIANT, "status": "BASELINE_FINAL_ROUTE", "reason": "phase_4_neural_rankers_are_diagnostic_only"},
        "method_registry": [_method_registry_row(baseline_row), *_neural_method_registry_rows(dependency_status, neural_training), *_blocked_method_registry_rows(dependency_status)],
        "gpu_resource_strategy": _gpu_resource_strategy(dependency_status),
        "ranking_experiment_registry": [baseline_row["ranking_experiment_registry"]],
        "runs": [_public_run_row(baseline_row)],
    }


def _run_baseline(output_dir: Path, limit_users: int | None, feature_contract: dict[str, Any], run_id: str, command_text: str) -> dict[str, Any]:
    variant_output_dir = output_dir / _BASELINE_VARIANT
    result = run_hybrid_demo(BASELINE_CONFIG, limit_users=limit_users, config_overrides={"output_dir": str(variant_output_dir), "report_path": str(variant_output_dir / "report.md"), "export_frozen_candidates": True, "strategy_name": f"{_PHASE}_{_BASELINE_VARIANT}"})
    metrics = result["metrics"]
    frozen_rows = _read_frozen_rows(_BASELINE_VARIANT, result, metrics)
    strict_status = _baseline_status()
    registry_entry = build_ranking_experiment_registry_entry(
        experiment_id=f"{_PHASE}:{run_id}:{_BASELINE_VARIANT}",
        config=_registry_config(metrics, _BASELINE_VARIANT),
        frozen_rows=frozen_rows,
        metrics=metrics,
        status=strict_status,
        feature_contract=feature_contract,
        feature_contract_gate_summary=_not_applicable_feature_contract_gate(),
        leakage_gate_summary=_not_applicable_leakage_gate(),
    )
    return _variant_row(_BASELINE_VARIANT, "baseline", "promotion", True, False, run_id, command_text, result, metrics, frozen_rows, frozen_rows, _freeze_values(metrics), strict_status, registry_entry)


def _export_neural_candidate_rows(output_dir: Path, limit_users: int | None) -> dict[str, Any]:
    export = train_ltr_ranker(
        BASELINE_CONFIG,
        output_dir=output_dir / "neural_candidate_rows",
        limit_users=limit_users,
        config_overrides={
            "evaluation_mode": "leave_one_positive_out",
            "ltr_training": {
                "model_type": "pointwise_logistic",
                "features": LTR_FEATURE_CONFIG,
                "write_candidate_rows": True,
                "max_candidate_rows": 20000,
                "train": {"epochs": 1, "learning_rate": 0.05, "positive_weight": 1.0, "negative_weight": 1.0},
            },
        },
    )
    public = _public_training_result(export)
    public["purpose"] = "candidate_rows_for_phase_4_neural_diagnostics"
    public["promotion_eligible"] = False
    public["diagnostic_only"] = True
    public["reasons"] = ["candidate_row_export_only", "lopo_training_diagnostic_only", "not_serving_ranker_model"]
    return public


def _run_neural_diagnostics(output_dir: Path, candidate_row_export: dict[str, Any], dependency_status: dict[str, Any]) -> dict[str, Any]:
    if not dependency_status["torch_available"]:
        return {method["name"]: _blocked_training_result(method, ["torch_dependency_missing"]) for method in NEURAL_METHODS}
    if not dependency_status["cuda_available"]:
        return {method["name"]: _blocked_training_result(method, ["blocked-gpu-unavailable"]) for method in NEURAL_METHODS}
    rows_path = candidate_row_export.get("candidate_rows_path")
    if not rows_path or not Path(rows_path).exists():
        return {method["name"]: _blocked_training_result(method, ["candidate_rows_missing"]) for method in NEURAL_METHODS}
    rows = read_jsonl(rows_path)
    return {method["name"]: _train_neural_method(output_dir / "neural_training" / method["name"], rows, method) for method in NEURAL_METHODS}


def _train_neural_method(output_dir: Path, rows: list[dict[str, Any]], method: dict[str, Any]) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if not rows:
        result = _blocked_training_result(method, ["candidate_rows_empty"])
        write_json(output_dir / "train_metrics.json", result)
        return result | {"metrics_path": str(output_dir / "train_metrics.json")}
    import torch
    from torch import nn

    random.seed(NEURAL_SEED)
    torch.manual_seed(NEURAL_SEED)
    device = torch.device("cuda")
    torch.cuda.manual_seed_all(NEURAL_SEED)
    torch.cuda.reset_peak_memory_stats(device)
    feature_names = sorted({name for row in rows for name in (row.get("features") or {})})
    x = torch.tensor([[float((row.get("features") or {}).get(name, 0.0)) for name in feature_names] for row in rows], dtype=torch.float32, device=device)
    y = torch.tensor([float(row.get("label", 0)) for row in rows], dtype=torch.float32, device=device)
    if x.numel() == 0 or not feature_names:
        result = _blocked_training_result(method, ["feature_rows_empty"])
        write_json(output_dir / "train_metrics.json", result)
        return result | {"metrics_path": str(output_dir / "train_metrics.json")}
    model = nn.Sequential(nn.Linear(len(feature_names), min(32, max(4, len(feature_names)))), nn.ReLU(), nn.Linear(min(32, max(4, len(feature_names))), 1)).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    if method["train_kind"] == "pairwise":
        loss_history, trainable = _train_pairwise_ranknet(model, optimizer, x, y, rows)
    else:
        loss_history, trainable = _train_pointwise_mlp(model, optimizer, x, y)
    status = "PASS" if trainable else "BLOCKED"
    reasons = ["diagnostic_only", "lopo_candidate_rows", "serving_adapter_missing", "promotion_adr_required"]
    if not trainable:
        reasons.append("positive_negative_pairs_missing")
    model_path = output_dir / "model.pt"
    metrics_path = output_dir / "train_metrics.json"
    torch.save({"state_dict": model.state_dict(), "feature_names": feature_names, "method": method["name"]}, model_path)
    metrics = {
        "schema_version": "phase_4_neural_ranker_training_v1",
        "method_id": method["name"],
        "method_family": method["method_family"],
        "status": status,
        "promotion_eligible": False,
        "diagnostic_only": True,
        "reasons": reasons,
        "backend": "pytorch",
        "torch_version": str(torch.__version__),
        "device": str(device),
        "cuda_device_name": torch.cuda.get_device_name(0),
        "epochs": NEURAL_EPOCHS,
        "batch_size": NEURAL_BATCH_SIZE,
        "rows": len(rows),
        "positive_rows": int(y.sum().detach().cpu().item()),
        "negative_rows": int((y.numel() - y.sum()).detach().cpu().item()),
        "feature_count": len(feature_names),
        "loss_history": loss_history,
        "peak_cuda_memory_mb": round(torch.cuda.max_memory_allocated(device) / (1024 * 1024), 3),
        "model_path": str(model_path),
    }
    write_json(metrics_path, metrics)
    return {"model_path": str(model_path), "metrics_path": str(metrics_path), "metrics": metrics}


def _train_pointwise_mlp(model: Any, optimizer: Any, x: Any, y: Any) -> tuple[list[float], bool]:
    import torch

    if y.sum().item() == 0 or y.sum().item() == y.numel():
        return [], False
    loss_history = []
    criterion = torch.nn.BCEWithLogitsLoss()
    for _ in range(NEURAL_EPOCHS):
        order = torch.randperm(x.shape[0], device=x.device)
        losses = []
        for start in range(0, x.shape[0], NEURAL_BATCH_SIZE):
            batch = order[start : start + NEURAL_BATCH_SIZE]
            optimizer.zero_grad()
            logits = model(x[batch]).squeeze(-1)
            loss = criterion(logits, y[batch])
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu().item()))
        loss_history.append(round(sum(losses) / len(losses), 6) if losses else 0.0)
    return loss_history, True


def _train_pairwise_ranknet(model: Any, optimizer: Any, x: Any, y: Any, rows: list[dict[str, Any]]) -> tuple[list[float], bool]:
    import torch

    grouped: dict[str, dict[str, list[int]]] = defaultdict(lambda: {"pos": [], "neg": []})
    for index, row in enumerate(rows):
        key = str(row.get("user_id", ""))
        grouped[key]["pos" if row.get("label", 0) else "neg"].append(index)
    pairs = []
    rng = random.Random(NEURAL_SEED)
    for group in grouped.values():
        for pos_index in group["pos"]:
            negatives = group["neg"][:]
            rng.shuffle(negatives)
            for neg_index in negatives[:3]:
                pairs.append((pos_index, neg_index))
    if not pairs:
        return [], False
    pair_tensor = torch.tensor(pairs[:5000], dtype=torch.long, device=x.device)
    target = torch.ones(pair_tensor.shape[0], dtype=torch.float32, device=x.device)
    loss_history = []
    criterion = torch.nn.BCEWithLogitsLoss()
    for _ in range(NEURAL_EPOCHS):
        order = torch.randperm(pair_tensor.shape[0], device=x.device)
        losses = []
        for start in range(0, pair_tensor.shape[0], NEURAL_BATCH_SIZE):
            batch = pair_tensor[order[start : start + NEURAL_BATCH_SIZE]]
            optimizer.zero_grad()
            pos_scores = model(x[batch[:, 0]]).squeeze(-1)
            neg_scores = model(x[batch[:, 1]]).squeeze(-1)
            loss = criterion(pos_scores - neg_scores, target[: batch.shape[0]])
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu().item()))
        loss_history.append(round(sum(losses) / len(losses), 6) if losses else 0.0)
    return loss_history, True


def _blocked_training_result(method: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    return {"metrics": {"schema_version": "phase_4_neural_ranker_training_v1", "method_id": method["name"], "method_family": method["method_family"], "status": "BLOCKED", "promotion_eligible": False, "diagnostic_only": True, "reasons": reasons}}


def _variant_row(variant_name: str, candidate_type: str, lane: str, promotion_eligible: bool, diagnostic_only: bool, run_id: str, command_text: str, result: dict[str, Any], metrics: dict[str, Any], frozen_rows: list[dict[str, Any]], baseline_frozen_rows: list[dict[str, Any]], baseline_freeze: dict[str, Any], strict_status: dict[str, Any], registry_entry: dict[str, Any]) -> dict[str, Any]:
    freeze = _freeze_values(metrics)
    status, drift = _status_and_drift(freeze, baseline_freeze)
    return {
        "run_id": run_id,
        "run_index": 0,
        "candidate_id": variant_name,
        "candidate_type": candidate_type,
        "lane": lane,
        "promotion_eligible": promotion_eligible,
        "diagnostic_only": diagnostic_only,
        "status": status,
        "strict_status": strict_status,
        "ranking_experiment_registry": registry_entry,
        "drift": drift,
        "frozen_candidate_comparison": compare_frozen_candidate_signatures(baseline_frozen_rows, frozen_rows),
        "config_path": str(BASELINE_CONFIG),
        "output_dir": str(Path(result["metrics_path"]).parent),
        "command_text": command_text,
        "metrics_path": result["metrics_path"],
        "recommendations_path": result["recommendations_path"],
        "ranking_cases_path": result["ranking_cases_path"],
        "ranking_case_summary_path": result["ranking_case_summary_path"],
        "report_path": result["report_path"],
        "frozen_candidates_path": result.get("frozen_candidates_path") or metrics.get("frozen_candidates_path"),
        "frozen_candidates_exported": True,
        "metrics": {key: metrics.get(key) for key in METRIC_FIELDS},
        "raw_metrics": metrics,
        "frozen_rows": frozen_rows,
        "freeze": freeze,
    }


def _method_registry_row(row: dict[str, Any]) -> dict[str, Any]:
    return build_ranking_method_registry_entry(
        method_id=row["candidate_id"],
        method_family=row["candidate_type"],
        lane=row["lane"],
        state="champion",
        promotion_eligible=bool(row["promotion_eligible"]),
        diagnostic_only=bool(row["diagnostic_only"]),
        reasons=row.get("strict_status", {}).get("reasons", []),
        champion_id=_BASELINE_VARIANT,
        gpu_resource=build_ranking_gpu_resource_summary(gpu_required=False),
    )


def _neural_method_registry_rows(dependency_status: dict[str, Any], neural_training: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for method in NEURAL_METHODS:
        training_metrics = neural_training.get(method["name"], {}).get("metrics", {})
        state = "diagnostic" if training_metrics.get("status") == "PASS" else "blocked"
        rows.append(
            build_ranking_method_registry_entry(
                method_id=method["name"],
                method_family=method["method_family"],
                lane=method["lane"],
                state=state,
                promotion_eligible=False,
                diagnostic_only=True,
                reasons=training_metrics.get("reasons", ["diagnostic_training_not_run"]),
                gpu_resource=build_ranking_gpu_resource_summary(
                    gpu_required=True,
                    gpu_available=bool(dependency_status.get("cuda_available")),
                    device=dependency_status.get("cuda_device_name"),
                    dependency_status="torch-cuda-ok" if dependency_status.get("cuda_available") else "torch-cuda-unavailable",
                ),
            )
        )
    return rows


def _blocked_method_registry_rows(dependency_status: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        build_ranking_method_registry_entry(
            method_id=method["name"],
            method_family=method["method_family"],
            lane=method["lane"],
            state="blocked",
            promotion_eligible=False,
            diagnostic_only=True,
            reasons=method["reasons"],
            gpu_resource=build_ranking_gpu_resource_summary(
                gpu_required=True,
                gpu_available=bool(dependency_status.get("cuda_available")),
                device=dependency_status.get("cuda_device_name"),
                dependency_status="torch-cuda-ok" if dependency_status.get("cuda_available") else "torch-cuda-unavailable",
                fallback_status="diagnostic-cpu-smoke" if dependency_status.get("torch_available") and not dependency_status.get("cuda_available") else None,
            ),
        )
        for method in BLOCKED_NEURAL_METHODS
    ]


def _dependency_status() -> dict[str, Any]:
    status: dict[str, Any] = {"torch_available": importlib.util.find_spec("torch") is not None, "tensorflow_available": importlib.util.find_spec("tensorflow") is not None, "keras_available": importlib.util.find_spec("keras") is not None}
    if not status["torch_available"]:
        status |= {"cuda_available": False, "cuda_device_count": 0, "cuda_device_name": None, "torch_version": None}
        return status
    import torch

    status["torch_version"] = str(torch.__version__)
    status["cuda_available"] = bool(torch.cuda.is_available())
    status["cuda_device_count"] = torch.cuda.device_count() if torch.cuda.is_available() else 0
    status["cuda_device_name"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    return status


def _public_run_row(row: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in row.items() if key not in {"raw_metrics", "frozen_rows", "freeze"}}
    registry = row["ranking_experiment_registry"]
    public["candidate_pool_size"] = registry.get("candidate_pool_size")
    public["top_k"] = registry.get("top_k")
    public["frozen_candidate_match"] = row.get("frozen_candidate_comparison", {}).get("match")
    public["frozen_candidate_status"] = "PASS" if public["frozen_candidate_match"] else "INVALID"
    return public


def _registry_config(metrics: dict[str, Any], strategy_name: str) -> dict[str, Any]:
    config = dict(metrics.get("config_summary", {}) or {})
    config["strategy_name"] = strategy_name
    config["candidate_pool_size"] = metrics.get("candidate_pool_size") or config.get("candidate_pool_size") or 200
    config["top_k"] = metrics.get("top_k") or config.get("top_k") or 5
    return config


def _read_frozen_rows(variant_name: str, result: dict[str, Any], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    frozen_candidates_path = result.get("frozen_candidates_path") or metrics.get("frozen_candidates_path")
    if not frozen_candidates_path or not Path(frozen_candidates_path).exists():
        raise ValueError(f"{variant_name} did not export frozen_candidates.jsonl")
    return read_jsonl(frozen_candidates_path)


def _freeze_values(metrics: dict[str, Any]) -> dict[str, Any]:
    return {field: metrics.get(field) for field in FREEZE_FIELDS}


def _baseline_status() -> dict[str, Any]:
    return {"status": "BASELINE", "promotable": False, "diagnostic_only": False, "reasons": ["same_run_baseline"], "metric_delta": {}}


def _not_applicable_feature_contract_gate() -> dict[str, Any]:
    return {"schema_version": "ranking_feature_contract_gate_v1", "status": "NOT_APPLICABLE", "checked_rows": 0, "checked_feature_count": 0, "reasons": ["neural_ranker_not_serving_variant"]}


def _not_applicable_leakage_gate() -> dict[str, Any]:
    return {"schema_version": "ranking_feature_leakage_gate_v1", "status": "NOT_APPLICABLE", "checked_rows": 0, "reasons": ["neural_ranker_not_serving_variant"]}


def _gpu_resource_strategy(dependency_status: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": "ranking_gpu_strategy_v1", "current_phase_gpu_required": True, "torch_available": dependency_status.get("torch_available"), "cuda_available": dependency_status.get("cuda_available"), "device": dependency_status.get("cuda_device_name"), "future_gpu_required_families": ["lambdarank", "listnet", "listmle", "wide_deep", "deepfm", "dcn", "xdeepfm"], "unavailable_status": "blocked-gpu-unavailable", "cpu_smoke_status": "diagnostic-cpu-smoke", "promotion_gate": "neural_rankers_are_diagnostic_until_serving_adapter_valid_test_split_and_adr_exist"}


def _command_text(output_dir: Path, limit_users: int | None) -> str:
    parts = ["./.venv/Scripts/python.exe", "rs_lab/experiments/ranking/run_phase_4_neural_ranker.py", "--output-dir", str(output_dir)]
    if limit_users is not None:
        parts.extend(["--limit-users", str(limit_users)])
    return " ".join(parts)


def _resolve_path(path: str | Path) -> Path:
    target = Path(path)
    if target.is_absolute():
        return target
    return ROOT / target


def _write_report(path: Path, comparison: dict[str, Any]) -> None:
    lines = [
        "# Phase 4 Neural Ranker Diagnostics",
        "",
        f"- Run id: `{comparison['run_id']}`",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Selected route: `{comparison['final_decision']['selected_route']}`",
        f"- Decision status: `{comparison['final_decision']['status']}`",
        "- Scope: PyTorch/CUDA diagnostic training only; no neural ranker promotion claim.",
        "",
        "## Dependency status",
        "",
    ]
    for key, value in comparison["dependency_status"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Method registry", "", "| method | family | state | gpu_status | reasons |", "| --- | --- | --- | --- | --- |"])
    for row in comparison["method_registry"]:
        lines.append("| " + " | ".join([row["method_id"], row["method_family"], row["state"], row["gpu_resource"]["status"], ", ".join(row.get("reasons", []))]) + " |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
