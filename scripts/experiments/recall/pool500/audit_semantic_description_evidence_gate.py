from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FORBIDDEN_SCOPE_TOKENS = ("holdout", "valid", "test", "lopo", "oracle", "eval_label", "clean_10000", "pool1000")
PASS_GUARDED_CANDIDATE = "PASS_GUARDED_CANDIDATE"
DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
STOP = "STOP"
DEFAULT_REPORT_NAME = "semantic_description_recall_strict_report.json"


def build_semantic_description_evidence_gate(
    *,
    diagnostic_path: Path,
    min_avg_strict_precision_at_10: float = 0.8,
    max_avg_bad_intent_rate_at_10: float = 0.2,
    min_query_count: int = 1,
    evidence_role: str = "description_relevance_guard_not_final_promotion",
) -> dict[str, Any]:
    report_path = _resolve_report_path(diagnostic_path)
    report = _read_json(report_path)
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else report
    if not isinstance(summary, dict):
        raise ValueError("semantic description report must contain a summary object")

    blockers: list[str] = []
    diagnostics: list[str] = []
    if summary.get("schema_version") != "semantic_description_recall_strict_v1":
        blockers.append("schema_version_not_semantic_description_recall_strict_v1")
    if summary.get("eval_scope") != "train_metadata_description_diagnostic_only":
        blockers.append("eval_scope_not_train_metadata_description_diagnostic_only")
    if summary.get("label_inputs_role") != "not_used":
        blockers.append("label_inputs_role_not_not_used")
    if bool(summary.get("oracle_label_injection")):
        blockers.append("oracle_label_injection_true")

    query_count = int(summary.get("query_count", 0) or 0)
    avg_strict_p10 = float(summary.get("avg_strict_precision_at_10", 0.0) or 0.0)
    avg_bad_intent = float(summary.get("avg_bad_intent_rate_at_10", 0.0) or 0.0)
    if query_count < min_query_count:
        diagnostics.append("query_count_below_guard_threshold")
    if avg_strict_p10 < min_avg_strict_precision_at_10:
        diagnostics.append("avg_strict_precision_at_10_below_guard_threshold")
    if avg_bad_intent > max_avg_bad_intent_rate_at_10:
        diagnostics.append("avg_bad_intent_rate_at_10_above_guard_threshold")

    forbidden_inputs = _forbidden_inputs(report, report_path)
    if forbidden_inputs:
        blockers.append("forbidden_scope_in_semantic_description_evidence")

    decision = STOP if blockers else DIAGNOSTIC_ONLY if diagnostics else PASS_GUARDED_CANDIDATE
    return {
        "schema_version": "semantic_description_evidence_gate_v1",
        "created_at": datetime.now(UTC).isoformat(),
        "decision": decision,
        "status": "PASS" if decision == PASS_GUARDED_CANDIDATE else decision,
        "source": "semantic",
        "evidence_role": evidence_role,
        "diagnostic_report_path": str(report_path),
        "summary": {
            "schema_version": summary.get("schema_version"),
            "eval_scope": summary.get("eval_scope"),
            "label_inputs_role": summary.get("label_inputs_role"),
            "oracle_label_injection": bool(summary.get("oracle_label_injection")),
            "query_count": query_count,
            "avg_strict_precision_at_5": float(summary.get("avg_strict_precision_at_5", 0.0) or 0.0),
            "avg_strict_precision_at_10": avg_strict_p10,
            "avg_required_precision_at_10": float(summary.get("avg_required_precision_at_10", 0.0) or 0.0),
            "avg_bad_intent_rate_at_10": avg_bad_intent,
            "queries_with_strict_hit_top5": int(summary.get("queries_with_strict_hit_top5", 0) or 0),
            "queries_strict_p10_ge_0_5": int(summary.get("queries_strict_p10_ge_0_5", 0) or 0),
        },
        "thresholds": {
            "min_query_count": min_query_count,
            "min_avg_strict_precision_at_10": min_avg_strict_precision_at_10,
            "max_avg_bad_intent_rate_at_10": max_avg_bad_intent_rate_at_10,
        },
        "forbidden_scope_audit": {
            "status": "PASS" if not forbidden_inputs else "BLOCKED",
            "forbidden_tokens": list(FORBIDDEN_SCOPE_TOKENS),
            "forbidden_inputs": forbidden_inputs,
        },
        "blockers": blockers,
        "diagnostics": diagnostics,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
    }


def write_semantic_description_evidence_gate(
    *,
    diagnostic_path: Path,
    output_path: Path,
    min_avg_strict_precision_at_10: float = 0.8,
    max_avg_bad_intent_rate_at_10: float = 0.2,
    min_query_count: int = 1,
) -> dict[str, Any]:
    gate = build_semantic_description_evidence_gate(
        diagnostic_path=diagnostic_path,
        min_avg_strict_precision_at_10=min_avg_strict_precision_at_10,
        max_avg_bad_intent_rate_at_10=max_avg_bad_intent_rate_at_10,
        min_query_count=min_query_count,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return gate


def _resolve_report_path(path: Path) -> Path:
    if path.is_dir():
        return path / DEFAULT_REPORT_NAME
    return path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _forbidden_inputs(report: dict[str, Any], report_path: Path) -> list[str]:
    candidates = [str(report_path)]
    candidates.extend(_collect_strings(report.get("summary") or {}))
    # Metric field names contain `strict`/`required`, but forbidden tokens should only block path/scope-like evidence.
    forbidden: list[str] = []
    for value in candidates:
        lowered = value.lower().replace("\\", "/")
        for token in FORBIDDEN_SCOPE_TOKENS:
            if token in {"valid", "test"}:
                if f"/{token}/" in lowered or lowered.endswith(f".{token}.jsonl"):
                    forbidden.append(value)
                    break
                continue
            if token in lowered:
                forbidden.append(value)
                break
    return sorted(set(forbidden))


def _collect_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for item in value.values():
            strings.extend(_collect_strings(item))
        return strings
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(_collect_strings(item))
        return strings
    return []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit semantic description diagnostic evidence for guarded pool500 route use.")
    parser.add_argument("--diagnostic-dir", type=Path, required=True)
    parser.add_argument("--output-path", type=Path, required=True)
    parser.add_argument("--min-avg-strict-p10", type=float, default=0.8)
    parser.add_argument("--max-avg-bad-intent-p10", type=float, default=0.2)
    parser.add_argument("--min-query-count", type=int, default=1)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    gate = write_semantic_description_evidence_gate(
        diagnostic_path=args.diagnostic_dir,
        output_path=args.output_path,
        min_avg_strict_precision_at_10=args.min_avg_strict_p10,
        max_avg_bad_intent_rate_at_10=args.max_avg_bad_intent_p10,
        min_query_count=args.min_query_count,
    )
    print(json.dumps({"decision": gate["decision"], "status": gate["status"], "output_path": str(args.output_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
