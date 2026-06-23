from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.evaluation.agent_artifact import build_agent_eval_artifact
from rs_core.serving.application.recommendation_service import RecommendationService
from rs_core.serving.runtime.config import DEFAULT_CONFIG
from rs_core.simulation import DEFAULT_ROLE_POLICY, run_simulation_batch
from scripts.evaluation.run_simulation_evaluation import parse_role_ids

VARIANT_OVERRIDES = {
    "baseline": {"feedback_rerank": {"enabled": False}},
    "enhanced_feedback_rerank": {
        "feedback_rerank": {
            "enabled": True,
            "explicit_negative_filter": True,
            "negative_similarity_demote": 0.3,
            "positive_similarity_boost": 0.3,
            "similarity_sources": ["itemcf_strong", "itemcf_weak"],
        }
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run baseline/enhanced Agent evaluation.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to hybrid demo config.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for quick runs.")
    parser.add_argument("--roles", default=None, help="Comma-separated role ids. Defaults to all preset roles.")
    parser.add_argument("--max-turns", type=int, default=4, help="Maximum turns per simulated scene.")
    parser.add_argument("--repeats", type=int, default=1, help="Number of scenes per role.")
    parser.add_argument("--user-id", default=None, help="Optional fixed user_id for all simulated sessions.")
    parser.add_argument("--variants", default="baseline,enhanced_feedback_rerank", help="Comma-separated variants to evaluate.")
    parser.add_argument("--output-dir", default=None, help="Directory for Agent evaluation artifacts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_id = f"agent-eval-{uuid4()}"
    variants = parse_variants(args.variants)
    result = run_agent_evaluation(
        config=args.config,
        variants=variants,
        limit_users=args.limit_users,
        roles=parse_role_ids(args.roles),
        max_turns=args.max_turns,
        repeats=args.repeats,
        user_id=args.user_id,
        run_id=run_id,
    )
    paths = write_agent_evaluation_outputs(result, args.output_dir)
    print(f"Agent evaluation JSON written to: {paths['evaluation_path']}")
    print(f"Scorecard JSON written to: {paths['scorecard_path']}")
    print(f"Training signals JSON written to: {paths['training_signals_path']}")
    print(f"Comparison report written to: {paths['report_path']}")


def run_agent_evaluation(
    config: str | Path,
    variants: list[str],
    limit_users: int | None = None,
    roles: list[str] | None = None,
    max_turns: int = 4,
    repeats: int = 1,
    user_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    current_run_id = run_id or f"agent-eval-{uuid4()}"
    variant_results = []
    for variant in variants:
        service = RecommendationService(config, limit_users=limit_users, config_overrides=VARIANT_OVERRIDES[variant])
        batch = run_simulation_batch(
            service,
            role_ids=roles,
            max_turns=max_turns,
            repeats=repeats,
            user_id=user_id,
            policy=DEFAULT_ROLE_POLICY,
            batch_id=f"{current_run_id}-{variant}",
        )
        artifacts = []
        for scene in batch["scenes"]:
            session_id = scene["session"]["session_id"]
            session = service.get_agent_session(session_id)
            artifacts.append(build_agent_eval_artifact(session, scene, agent_variant=variant, run_id=current_run_id))
        variant_results.append({
            "variant": variant,
            "batch": batch,
            "artifacts": artifacts,
            "summary_scorecard": _summary_scorecard(artifacts),
            "training_signal_metrics": _training_signal_metrics(artifacts),
        })
    return {
        "schema_version": "rs_agent_evaluation_run_v1",
        "run_id": current_run_id,
        "variants": variant_results,
        "comparison": _comparison(variant_results),
    }


def parse_variants(value: str) -> list[str]:
    variants = [variant.strip() for variant in value.split(",") if variant.strip()]
    unknown = [variant for variant in variants if variant not in VARIANT_OVERRIDES]
    if unknown:
        raise ValueError(f"Unsupported variants: {unknown}")
    return variants


def write_agent_evaluation_outputs(result: dict[str, Any], output_dir: str | Path | None = None) -> dict[str, Path]:
    root = Path(output_dir) if output_dir is not None else ROOT / "outputs" / result["run_id"]
    root.mkdir(parents=True, exist_ok=True)
    evaluation_path = root / "agent_evaluation.json"
    scorecard_path = root / "scorecard.json"
    training_signals_path = root / "training_signals.json"
    report_path = root / "comparison_report.md"
    evaluation_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    scorecard_path.write_text(json.dumps({variant["variant"]: variant["summary_scorecard"] for variant in result["variants"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    training_signals_path.write_text(json.dumps({variant["variant"]: variant["training_signal_metrics"] for variant in result["variants"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(build_comparison_report(result), encoding="utf-8")
    return {
        "evaluation_path": evaluation_path,
        "scorecard_path": scorecard_path,
        "training_signals_path": training_signals_path,
        "report_path": report_path,
    }


def build_comparison_report(result: dict[str, Any]) -> str:
    lines = [
        "# Agent Evaluation Comparison Report",
        "",
        "## 总览",
        "",
        f"- run_id：`{result['run_id']}`",
        f"- variants：`{[variant['variant'] for variant in result['variants']]}`",
        "",
        "## Variant scorecard",
        "",
    ]
    for variant in result["variants"]:
        scorecard = variant["summary_scorecard"]
        lines.extend([
            f"### {variant['variant']}",
            "",
            f"- overall_score：{scorecard['overall_score']}",
            f"- scene_count：{scorecard['scene_count']}",
            f"- tool_event_count：{variant['training_signal_metrics']['tool_event_count']}",
            f"- training signals：`{variant['training_signal_metrics']}`",
            "",
        ])
        for name, score in scorecard["dimension_scores"].items():
            lines.append(f"  - {name}：{score}")
        lines.append("")
    lines.extend(["## 对比结论", ""])
    for item in result["comparison"]:
        lines.append(f"- `{item['metric']}`：{item['values']}")
    lines.extend([
        "",
        "## 说明",
        "",
        "- 第一版评估使用离线/仿真/内部事件证据的规则化 scorecard，不代表已经完成 SFT 或 GRPO。",
        "- `feedback_rerank` 事件只存在于 internal artifact，public session export 仍保持安全视图。",
    ])
    return "\n".join(lines) + "\n"


def _summary_scorecard(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    if not artifacts:
        return {"scene_count": 0, "overall_score": 0.0, "dimension_scores": {}}
    dimension_names = artifacts[0]["scorecard"]["dimensions"].keys()
    return {
        "scene_count": len(artifacts),
        "overall_score": round(_avg(artifact["scorecard"]["overall_score"] for artifact in artifacts), 6),
        "dimension_scores": {
            name: round(_avg(artifact["scorecard"]["dimensions"][name]["score"] for artifact in artifacts), 6)
            for name in dimension_names
        },
    }


def _training_signal_metrics(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = {"sft_count": 0, "reward_count": 0, "preference_count": 0, "trajectory_turn_count": 0, "tool_event_count": 0}
    for artifact in artifacts:
        signal_metrics = artifact["training_signals"]["metrics"]
        for key in ("sft_count", "reward_count", "preference_count", "trajectory_turn_count"):
            metrics[key] += int(signal_metrics.get(key, 0) or 0)
        metrics["tool_event_count"] += len(artifact.get("tool_events", []))
    return metrics


def _comparison(variant_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "metric": "overall_score",
            "values": {variant["variant"]: variant["summary_scorecard"]["overall_score"] for variant in variant_results},
        },
        {
            "metric": "tool_event_count",
            "values": {variant["variant"]: variant["training_signal_metrics"]["tool_event_count"] for variant in variant_results},
        },
    ]


def _avg(values: Any) -> float:
    rows = [float(value) for value in values]
    return sum(rows) / len(rows) if rows else 0.0


if __name__ == "__main__":
    main()
