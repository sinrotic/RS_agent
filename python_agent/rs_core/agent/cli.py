from __future__ import annotations

import argparse
import json
from pathlib import Path

from rs_core.common.config import load_config
from rs_core.common.io import write_json, write_jsonl
from rs_core.display import session_to_display_records, validate_public_display_payload
from rs_core.offline.evaluation.ranking import heldout_positives
from rs_core.agent.inference import resolve_inference_policy_config
from rs_core.agent.feedback import normalize_feedback_input
from rs_core.agent.model_clients.qwen_client import QwenLocalClient
from rs_core.agent.reward import build_reward_evidence, compute_turn_reward
from rs_core.agent.rollout import session_to_rollout_records
from rs_core.workflow.hybrid_environment import HybridRecommendationEnvironment

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "outputs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the RS_agent CLI recommendation loop.")
    parser.add_argument("--config", default="configs/demo/hybrid_demo/hybrid_demo_agent_local_smoke.yaml", help="Path to hybrid demo config.")
    parser.add_argument("--user-id", default=None, help="User id to run. Defaults to first loaded user.")
    parser.add_argument("--limit-users", type=int, default=None, help="Limit loaded users for smoke runs.")
    parser.add_argument("--max-turns", type=int, default=2, help="Maximum interactive turns.")
    parser.add_argument("--simulate-two-turn", action="store_true", help="Run deterministic initial + feedback turns without stdin.")
    parser.add_argument("--simulate-conversation", action="store_true", help="Run deterministic multi-turn conversational recommendation demo without stdin.")
    parser.add_argument("--feedback", default="I want fresh recommendations again, prefer semantic and Audio, avoid Accessories", help="Simulated feedback text.")
    parser.add_argument("--output-dir", default="agent_cli", help="Output subdirectory under project outputs/ for session artifacts.")
    parser.add_argument("--inference-policy", choices=["config", "off", "qwen"], default="config", help="Override optional inference rerank policy.")
    parser.add_argument("--qwen-model-id", default=None, help="Local Qwen model path or cached model id for inference.")
    parser.add_argument("--inference-strict", action="store_true", help="Raise instead of falling back when inference fails.")
    return parser.parse_args()


def run_cli_session(
    config: str,
    user_id: str | None = None,
    limit_users: int | None = None,
    output_dir: str | Path = "agent_cli",
    simulate_two_turn: bool = False,
    feedback: str = "I want fresh recommendations again, prefer semantic and Audio, avoid Accessories",
    max_turns: int = 2,
    inference_policy: str = "config",
    qwen_model_id: str | None = None,
    inference_strict: bool = False,
    simulate_conversation: bool = False,
) -> dict[str, str]:
    config_overrides = _inference_config_overrides(inference_policy, qwen_model_id, inference_strict)
    inference_client = _build_cli_inference_client(config, config_overrides)
    env = HybridRecommendationEnvironment.from_config(
        config,
        limit_users=limit_users,
        inference_client=inference_client,
        config_overrides=_merge_nested(_cli_feedback_default_overrides(), config_overrides),
    )
    session = env.start_session(user_id)
    print(f"Session: {session.session_id} | user: {session.user_id}")
    first = env.step(session, "")
    _attach_reward(first, env, session.user_id)
    _print_turn(first.turn_index, first.recommendation.to_dict())
    if simulate_conversation:
        for message in _scripted_conversation_messages(feedback):
            turn = env.converse(session, message)
            _attach_reward(turn, env, session.user_id)
            _print_turn(turn.turn_index, turn.recommendation.to_dict())
    elif simulate_two_turn:
        second = env.step(session, normalize_feedback_input(feedback))
        _attach_reward(second, env, session.user_id)
        _print_turn(second.turn_index, second.recommendation.to_dict())
    else:
        turns_remaining = max(0, max_turns - 1)
        for _ in range(turns_remaining):
            user_input = normalize_feedback_input(input("feedback> ").strip())
            if user_input in {"/quit", "quit", "exit"}:
                break
            turn = env.step(session, user_input)
            _attach_reward(turn, env, session.user_id)
            _print_turn(turn.turn_index, turn.recommendation.to_dict())
    target = _resolve_output_dir(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    user_sequence = env.sequences_by_user[session.user_id]
    session_path = target / "session.json"
    turns_path = target / "session_turns.jsonl"
    rollout_path = target / "grpo_rollouts.jsonl"
    display_responses_path = target / "display_responses.jsonl"
    display_demo_path = target / "display_demo.json"
    report_path = target / "rs_agent_cli_baseline_comparison.md"
    display_records = [validate_public_display_payload(record) for record in session_to_display_records(session)]
    write_json(session_path, session.to_dict())
    write_jsonl(turns_path, [turn.to_dict() for turn in session.turns])
    write_jsonl(rollout_path, session_to_rollout_records(session, user_sequence))
    write_jsonl(display_responses_path, display_records)
    write_json(display_demo_path, display_records[-1] if display_records else {})
    report_path.write_text(_comparison_report(session, rollout_path), encoding="utf-8")
    print(f"Session written to: {session_path}")
    print(f"Turns written to: {turns_path}")
    print(f"Rollouts written to: {rollout_path}")
    print(f"Display responses written to: {display_responses_path}")
    print(f"Display demo written to: {display_demo_path}")
    print(f"Report written to: {report_path}")
    return {
        "session_path": str(session_path),
        "turns_path": str(turns_path),
        "rollout_path": str(rollout_path),
        "display_responses_path": str(display_responses_path),
        "display_demo_path": str(display_demo_path),
        "report_path": str(report_path),
    }


def _inference_config_overrides(inference_policy: str, qwen_model_id: str | None, inference_strict: bool) -> dict:
    overrides: dict = {}
    if inference_policy != "config":
        overrides.setdefault("inference_policy", {})["enabled"] = inference_policy == "qwen"
    if qwen_model_id:
        overrides.setdefault("inference_policy", {}).setdefault("model", {})["model_id"] = qwen_model_id
    if inference_strict:
        overrides.setdefault("inference_policy", {})["strict"] = True
    return overrides


def _build_cli_inference_client(config_path: str | Path, config_overrides: dict) -> QwenLocalClient | None:
    config = load_config(config_path)
    if config_overrides:
        config = _merge_nested(config, config_overrides)
    policy = resolve_inference_policy_config(config)
    if policy.get("enabled") and policy.get("provider") == "local_transformers":
        return QwenLocalClient(policy)
    return None


def _cli_feedback_default_overrides() -> dict:
    return {
        "rank_weights": {
            "feedback_category": 10.0,
            "feedback_source_semantic": 10.0,
            "feedback_source_itemcf_weak": 10.0,
            "feedback_source_itemcf_strong": 10.0,
            "feedback_keyword": 10.0,
            "feedback_keyword_penalty": 10.0,
        },
        "feedback_category_boost": 1.0,
        "feedback_source_boost": 1.0,
        "feedback_keyword_boost": 1.0,
        "feedback_keyword_penalty": 1.0,
    }


def _merge_nested(base: dict, overrides: dict) -> dict:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_nested(merged[key], value)
        else:
            merged[key] = value
    return merged


def _attach_reward(turn, env: HybridRecommendationEnvironment, user_id: str) -> None:
    holdout = heldout_positives(env.holdout_records).get(user_id, set())
    turn.reward_evidence = build_reward_evidence(turn, holdout)
    turn.reward = compute_turn_reward(turn)


def _scripted_conversation_messages(feedback: str) -> list[str]:
    return [
        "I want headphones",
        "For commute, prefer bluetooth and Audio, avoid wired",
        "why?",
        normalize_feedback_input(feedback),
    ]


def _resolve_output_dir(value: str | Path) -> Path:
    raw = Path(value)
    if raw.is_absolute():
        resolved = raw.resolve()
        allowed_root = (OUTPUT_ROOT.resolve())
        try:
            resolved.relative_to(allowed_root)
        except ValueError as exc:
            raise ValueError(f"Output path must stay under {allowed_root}: {raw}") from exc
        return resolved
    resolved = (OUTPUT_ROOT / raw).resolve()
    try:
        resolved.relative_to(OUTPUT_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"Output path escapes outputs root: {raw}") from exc
    return resolved


def _print_turn(turn_index: int, decision: dict) -> None:
    print(f"\nTurn {turn_index}")
    print(decision.get("agent_explanation", ""))
    for item in decision.get("final_items", []):
        print(f"- {item.get('parent_asin')} score={item.get('score')} sources={','.join(item.get('sources', []))}")
    risk_flags = decision.get("risk_flags", [])
    if risk_flags:
        print("risk_flags: " + ", ".join(risk_flags))


def _comparison_report(session, rollout_path: Path) -> str:
    first = session.turns[0] if session.turns else None
    last = session.turns[-1] if session.turns else None
    first_items = [item.get("parent_asin") for item in first.ranking] if first else []
    last_items = [item.get("parent_asin") for item in last.ranking] if last else []
    changed = first_items != last_items
    reward = last.reward.to_dict() if last and last.reward else {}
    return "\n".join([
        "# RS Agent CLI Baseline Comparison",
        "",
        "## Scope",
        "",
        "Compares the deterministic hybrid baseline first turn against the first interactive CLI agent loop after feedback.",
        "",
        "## Baseline Hybrid Output",
        "",
        f"- user_id: {_md_json(session.user_id)}",
        f"- top_items: {_md_json(first_items)}",
        "",
        "## Interactive Agent Output After Feedback",
        "",
        f"- top_items: {_md_json(last_items)}",
        f"- changed_after_feedback: {_md_json(changed)}",
        f"- reward: {_md_json(reward)}",
        "",
        "## Feedback Response Summary",
        "",
        *_feedback_response_summary_lines(first, last),
        "",
        "## Qualitative Case",
        "",
        f"- feedback: {_md_json(last.user_input if last else '')}",
        f"- diagnostics: {_md_json(last.diagnostics if last else {})}",
        "",
        "## Observed Failures or Unsupported Feedback",
        "",
        f"- unsupported_free_text: {_md_json(last.feedback_constraints.unsupported_free_text if last else [])}",
        "",
        "## Reward Design Rationale",
        "",
        "The reward combines holdout hit quality, feedback alignment, explanation faithfulness, and risk penalties so the rollout is useful for later GRPO without starting training in this milestone.",
        "",
        "## Next-Step Optimization Rationale",
        "",
        "Only after CLI state, reward evidence, and rollout records are stable should Qwen3.5-4B + 8-bit QLoRA + GRPO training be added.",
        "",
        f"Rollout artifact: {_md_json(str(rollout_path))}",
    ])


def _feedback_response_summary_lines(first, last) -> list[str]:
    diagnostics = last.diagnostics if last else {}
    reward_evidence = last.reward_evidence.to_dict() if last else {}
    first_items = [item.get("parent_asin") for item in first.ranking] if first else []
    last_items = [item.get("parent_asin") for item in last.ranking] if last else []
    return [
        f"- changed_after_feedback: {_md_json(first_items != last_items)}",
        f"- filtered_prior_turn_items: {_md_json(diagnostics.get('excluded_prior_turn_items', []))}",
        f"- filtered_disliked_items: {_md_json(diagnostics.get('excluded_items', []))}",
        f"- filtered_disliked_categories: {_md_json(diagnostics.get('excluded_category_items', []))}",
        f"- boosted_item_count: {_md_json(len(diagnostics.get('boosts_applied', {})))}",
        f"- feedback_effect_observed: {_md_json(reward_evidence.get('feedback_constraints_satisfied', {}).get('feedback_effect_observed'))}",
    ]


def _md_json(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False)
    fence = "`"
    while fence in encoded:
        fence += "`"
    return f"{fence}{encoded}{fence}"


def main() -> None:
    args = parse_args()
    run_cli_session(
        args.config,
        user_id=args.user_id,
        limit_users=args.limit_users,
        output_dir=args.output_dir,
        simulate_two_turn=args.simulate_two_turn,
        feedback=args.feedback,
        max_turns=args.max_turns,
        inference_policy=args.inference_policy,
        qwen_model_id=args.qwen_model_id,
        inference_strict=args.inference_strict,
        simulate_conversation=args.simulate_conversation,
    )


if __name__ == "__main__":
    main()
