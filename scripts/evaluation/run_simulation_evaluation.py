from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.serving.service import DEFAULT_CONFIG, RecommendationService
from rs_core.simulation import DEFAULT_ROLE_POLICY, ModelDrivenRolePolicy, run_simulation_batch
from rs_core.simulation.model_client import DEFAULT_MODEL_CONFIG_PATH, SimulationModelClient, SimulationModelUnavailableError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run batch simulation evaluation for preset customer roles.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to hybrid demo config.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick run.")
    parser.add_argument("--roles", default=None, help="Comma-separated role ids. Defaults to all preset roles.")
    parser.add_argument("--max-turns", type=int, default=4, help="Maximum turns per simulated scene.")
    parser.add_argument("--repeats", type=int, default=1, help="Number of scenes to run per role.")
    parser.add_argument("--user-id", default=None, help="Optional fixed user_id for all simulated sessions.")
    parser.add_argument("--output-dir", default=None, help="Directory for simulation evaluation artifacts.")
    parser.add_argument("--role-policy", choices=["deterministic", "model"], default="deterministic", help="Policy used to simulate customer actions.")
    parser.add_argument("--model-config", default=str(DEFAULT_MODEL_CONFIG_PATH), help="Local JSON config for model-driven simulation policy.")
    parser.add_argument("--strict-model-policy", action="store_true", help="Fail instead of falling back when model policy is unavailable or invalid.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    service = RecommendationService(args.config, limit_users=args.limit_users)
    policy, policy_metadata = build_role_policy(args.role_policy, args.model_config, args.strict_model_policy)
    batch = run_simulation_batch(
        service,
        role_ids=parse_role_ids(args.roles),
        max_turns=args.max_turns,
        repeats=args.repeats,
        user_id=args.user_id,
        policy=policy,
    )
    batch["policy"] = policy_metadata
    paths = write_simulation_evaluation_outputs(batch, args.output_dir)
    print(f"Simulation batch JSON written to: {paths['batch_path']}")
    print(f"Metrics JSON written to: {paths['metrics_path']}")
    print(f"Evaluation report written to: {paths['report_path']}")


def parse_role_ids(value: str | None) -> list[str] | None:
    if value is None or not value.strip():
        return None
    return [role_id.strip() for role_id in value.split(",") if role_id.strip()]


def build_role_policy(policy_name: str, model_config: str | Path, strict: bool) -> tuple[Any, dict[str, Any]]:
    if policy_name == "deterministic":
        return DEFAULT_ROLE_POLICY, {"role_policy": "deterministic"}
    try:
        client = SimulationModelClient.from_file(model_config)
    except SimulationModelUnavailableError:
        if strict:
            raise
        return DEFAULT_ROLE_POLICY, {
            "role_policy": "deterministic",
            "requested_role_policy": "model",
            "fallback_used": True,
            "model_config_path": str(model_config),
        }
    return ModelDrivenRolePolicy(client, strict=strict), {
        "role_policy": "model",
        "model_config_path": str(model_config),
        "model": client.config.model,
    }


def write_simulation_evaluation_outputs(batch: dict[str, Any], output_dir: str | Path | None = None) -> dict[str, Path]:
    root = Path(output_dir) if output_dir is not None else ROOT / "outputs" / f"simulation_eval_{batch['batch_id']}"
    root.mkdir(parents=True, exist_ok=True)
    batch_path = root / "simulation_batch.json"
    metrics_path = root / "metrics.json"
    report_path = root / "simulation_eval_report.md"

    batch_path.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    metrics_path.write_text(json.dumps({"batch_id": batch["batch_id"], "policy": batch.get("policy", {}), "summary": batch["summary"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(build_simulation_evaluation_report(batch), encoding="utf-8")
    return {
        "batch_path": batch_path,
        "metrics_path": metrics_path,
        "report_path": report_path,
    }


def build_simulation_evaluation_report(batch: dict[str, Any]) -> str:
    summary = batch["summary"]
    lines = [
        "# Simulation Evaluation Report",
        "",
        "## 总览",
        "",
        f"- batch_id：`{batch['batch_id']}`",
        f"- role_policy：`{batch.get('policy', {}).get('role_policy', 'unknown')}`",
        f"- model_config_path：`{batch.get('policy', {}).get('model_config_path', 'N/A')}`",
        f"- 角色数：{summary['role_count']}",
        f"- scene 数：{summary['scene_count']}",
        f"- 平均轮数：{summary['avg_turn_count']}",
        f"- accept_rate：{summary['accept_rate']}",
        f"- 平均满意度：{summary['avg_satisfaction']}",
        f"- 平均已看商品数：{summary['avg_unique_seen_items']}",
        f"- feedback 次数：{summary['feedback_count']}",
        f"- why 次数：{summary['why_count']}",
        f"- show_different 次数：{summary['show_different_count']}",
        "",
        "## 角色摘要",
        "",
    ]
    for role_id, role_summary in summary["roles"].items():
        lines.extend([
            f"### {role_id}",
            "",
            f"- scene 数：{role_summary['scene_count']}",
            f"- 平均轮数：{role_summary['avg_turn_count']}",
            f"- accept_rate：{role_summary['accept_rate']}",
            f"- 平均满意度：{role_summary['avg_satisfaction']}",
            f"- action 分布：`{role_summary['action_counts']}`",
            "",
        ])
    lines.extend([
        "## Scene 明细",
        "",
    ])
    for scene in batch["scenes"]:
        metrics = scene["metrics"]
        role = scene["role"]
        lines.extend([
            f"- `{scene['scene_id']}`：role=`{role['role_id']}`，turns={metrics['turn_count']}，final_action={metrics['final_action']}，accepted={metrics['accepted']}，satisfaction={metrics['satisfaction']}",
        ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
