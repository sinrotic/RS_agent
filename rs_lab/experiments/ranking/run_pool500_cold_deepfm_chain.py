from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, write_json
from rs_core.common.runtime import enforce_project_venv
from rs_core.recsys.cold_deepfm import run_cold_deepfm_chain
from rs_core.workflow.pool500_ranking_adapter import adapt_pool500_rows_to_candidates

SCHEMA_VERSION = "pool500_cold_deepfm_chain_report_v1"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "ranking" / "pool500_cold_deepfm_chain_smoke"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run diagnostic pool500 COLD coarse rank -> DeepFM fine rank chain.")
    parser.add_argument("--pool500-candidates", required=True)
    parser.add_argument("--label-artifact", required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--cold-top-n", type=int, default=200)
    parser.add_argument("--deepfm-top-k", type=int, default=20)
    parser.add_argument("--cold-candidate-threshold", type=int, default=200)
    parser.add_argument("--limit-users", type=int, default=None)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_pool500_cold_deepfm_chain_from_files(
        pool500_candidates_path=Path(args.pool500_candidates),
        label_artifact_path=Path(args.label_artifact),
        output_dir=Path(args.output_dir),
        cold_top_n=args.cold_top_n,
        deepfm_top_k=args.deepfm_top_k,
        cold_candidate_threshold=args.cold_candidate_threshold,
        limit_users=args.limit_users,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps(report["output_paths"], ensure_ascii=False, indent=2))


def run_pool500_cold_deepfm_chain_from_files(
    *,
    pool500_candidates_path: Path,
    label_artifact_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    cold_top_n: int = 200,
    deepfm_top_k: int = 20,
    cold_candidate_threshold: int | None = 200,
    limit_users: int | None = None,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_rows = list(iter_jsonl(pool500_candidates_path))
    label_rows = list(iter_jsonl(label_artifact_path))
    adapter_result = adapt_pool500_rows_to_candidates(candidate_rows)
    blockers = list(adapter_result.get("blockers", []))
    candidates_by_user = adapter_result.get("candidates_by_user", {}) if adapter_result.get("status") == "PASS" else {}
    chain = run_cold_deepfm_chain(
        candidates_by_user,
        label_rows,
        cold_top_n=cold_top_n,
        deepfm_top_k=deepfm_top_k,
        cold_candidate_threshold=cold_candidate_threshold,
        limit_users=limit_users,
    )
    blockers.extend(chain.get("blockers", []))
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not blockers else "STOP",
        "generated_at": datetime.now(UTC).isoformat(),
        "report_semantics": "diagnostic shadow ranking report",
        "diagnostic_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool500_candidates_path": str(pool500_candidates_path.resolve()),
        "label_artifact_path": str(label_artifact_path.resolve()),
        "limit_users": limit_users,
        "cold_top_n": cold_top_n,
        "deepfm_top_k": deepfm_top_k,
        "cold_candidate_threshold": cold_candidate_threshold,
        "ranking_strategy": chain.get("ranking_strategy"),
        "adapter_summary": _adapter_summary(adapter_result),
        "training_sample_summary": chain.get("training_sample_summary", {}),
        "feature_contract_gate": chain.get("feature_contract_gate", {}),
        "leakage_gate": chain.get("leakage_gate", {}),
        "label_split_gate": chain.get("label_split_gate", {}),
        "cold": chain.get("cold", {}),
        "deepfm": chain.get("deepfm", {}),
        "final_rankings": chain.get("final_rankings", {}),
        "blockers": blockers,
    }
    comparison_path = output_dir / "comparison.json"
    report_path = output_dir / "comparison.md"
    report["output_paths"] = {"comparison_json": str(comparison_path), "comparison_md": str(report_path)}
    write_json(comparison_path, report)
    report_path.write_text(_markdown(report), encoding="utf-8")
    return report


def _adapter_summary(adapter_result: dict[str, Any]) -> dict[str, Any]:
    candidates_by_user = adapter_result.get("candidates_by_user", {}) if isinstance(adapter_result, dict) else {}
    candidate_counts = [len(candidates) for candidates in candidates_by_user.values()]
    return {
        "schema_version": adapter_result.get("schema_version") if isinstance(adapter_result, dict) else None,
        "status": adapter_result.get("status") if isinstance(adapter_result, dict) else "STOP",
        "users": len(candidates_by_user),
        "candidate_count_min": min(candidate_counts, default=0),
        "candidate_count_max": max(candidate_counts, default=0),
        "candidate_count_avg": round(sum(candidate_counts) / len(candidate_counts), 6) if candidate_counts else 0.0,
        "blocker_count": len(adapter_result.get("blockers", [])) if isinstance(adapter_result, dict) else 0,
        "diagnostic_count": len(adapter_result.get("diagnostics", [])) if isinstance(adapter_result, dict) else 0,
    }


def _markdown(report: dict[str, Any]) -> str:
    sample = report.get("training_sample_summary", {})
    cold = report.get("cold", {})
    deepfm = report.get("deepfm", {})
    return "\n".join(
        [
            "# Pool500 COLD → DeepFM 诊断链路",
            "",
            f"- 状态：{report.get('status')}",
            f"- 诊断边界：diagnostic_only={report.get('diagnostic_only')}，ranking_replacement_allowed={report.get('ranking_replacement_allowed')}",
            f"- 排序策略：{report.get('ranking_strategy')}，cold_candidate_threshold={report.get('cold_candidate_threshold')}",
            f"- 样本：users={sample.get('users', 0)}，rows={sample.get('rows', 0)}，positive_rows={sample.get('positive_rows', 0)}",
            f"- 候选正样本覆盖：{sample.get('candidate_positive_coverage', 0.0)}",
            f"- COLD：top_n={cold.get('top_n')}，positive_survival={cold.get('positive_survival_at_top_n')}",
            f"- DeepFM：top_k={deepfm.get('top_k')}，positive_survival={deepfm.get('positive_survival_at_top_k')}",
            f"- blockers：{len(report.get('blockers', []))}",
            "",
            "该报告只证明 pool500 冻结候选池上的离线 shadow 链路可运行，不声明替换当前排序主路。",
        ]
    )


if __name__ == "__main__":
    main()
