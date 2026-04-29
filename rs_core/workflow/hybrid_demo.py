from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from rs_core.common.config import load_config
from rs_core.common.io import read_jsonl, write_json, write_jsonl
from rs_core.recsys.candidate_merge import (
    load_category_candidates,
    load_itemcf_by_source,
    load_popular_candidates,
    load_semantic_index,
    merge_for_user,
)
from rs_core.recsys.evaluation import evaluate, heldout_positives
from rs_core.recsys.ranking import rank_candidates
from rs_core.rsagent.decision import make_agent_decision
from rs_core.rsagent.inference_policy import RerankPolicyClient, apply_optional_inference_policy, resolve_inference_policy_config
from rs_core.rsagent.policy import apply_feedback_to_candidates, normalize_feedback_input, parse_feedback
from rs_core.rsagent.schema import FeedbackConstraints, RecommendationTurnResult

ROOT = Path(__file__).resolve().parents[2]


def run_hybrid_demo(
    config_path: str | Path,
    limit_users: int | None = None,
    inference_client: RerankPolicyClient | None = None,
    config_overrides: dict[str, Any] | None = None,
    feedback_constraints: FeedbackConstraints | None = None,
    feedback_text: str | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    if config_overrides:
        config = _merge_nested(config, config_overrides)
    if feedback_constraints is None:
        feedback_constraints = _feedback_constraints_from_config(config, feedback_text)
    clean_dir = _resolve_path(config.get("clean_dir", "data/processed/amazon_2023_recall_clean_smoke_e2e"))
    views_dir = _resolve_path(config.get("views_dir", "data/processed/amazon_2023_recall_views_smoke_e2e"))
    output_dir = _resolve_path(config.get("output_dir", "outputs/hybrid_demo_small"))
    report_path = _resolve_path(config.get("report_path", "dic/HYBRID_DEMO_SMALL_REPORT.md"))

    paths = _required_paths(clean_dir, views_dir)
    if config.get("semantic_enabled"):
        paths["semantic"] = views_dir / "semantic_recall_inputs.jsonl"
    _ensure_inputs(paths)

    popular = load_popular_candidates(paths["popular"], limit=int(config.get("popular_fallback_count", 50)))
    category_top = load_category_candidates(paths["category_top"])
    evaluation_mode = str(config.get("evaluation_mode", "valid_test"))
    if evaluation_mode not in {"valid_test", "leave_one_positive_out"}:
        raise ValueError(f"Unsupported evaluation_mode: {evaluation_mode}")

    train_sequences = read_jsonl(paths["sequences"])
    if limit_users is not None:
        train_sequences = train_sequences[:limit_users]
    holdout = []
    lopo_stats: dict[str, int] = {}
    if evaluation_mode == "leave_one_positive_out":
        train_sequences, holdout, lopo_stats = _leave_one_positive_out_sequences(train_sequences)
    itemcf_seed_items = _itemcf_seed_items(train_sequences)
    itemcf_weak = load_itemcf_by_source(paths["itemcf_weak"], "itemcf_weak", itemcf_seed_items)
    itemcf_strong = load_itemcf_by_source(paths["itemcf_strong"], "itemcf_strong", itemcf_seed_items)
    item_category = _load_item_category(paths["category_items"])
    semantic_index = load_semantic_index(paths["semantic"], config.get("semantic_text_fields")) if config.get("semantic_enabled") else {}

    candidates_by_user = {}
    rankings_by_user = {}
    fallback_users: set[str] = set()
    source_diagnostics = _source_diagnostics(train_sequences, itemcf_weak, itemcf_strong)
    recommendation_rows = []
    for sequence in train_sequences:
        user_id = sequence.get("user_id", "")
        result = recommend_for_user(
            sequence,
            popular,
            itemcf_weak,
            itemcf_strong,
            category_top,
            item_category,
            config,
            semantic_index,
            feedback_constraints=feedback_constraints,
            inference_client=inference_client,
            turn_index=2 if feedback_constraints else 1,
        )
        candidates = result.candidates
        ranking = result.ranking
        decision = result.decision
        fallback_used = result.fallback_used
        candidates_by_user[user_id] = candidates
        rankings_by_user[user_id] = ranking
        if fallback_used:
            fallback_users.add(user_id)
        row = decision.to_dict()
        row["candidate_count"] = len(candidates)
        row["diagnostics"] = result.diagnostics
        recommendation_rows.append(row)

    if evaluation_mode == "valid_test":
        for split_name in ("valid", "test"):
            path = clean_dir / f"canonical_interactions.{split_name}.jsonl"
            if path.exists():
                holdout.extend(read_jsonl(path))
    metrics = evaluate(candidates_by_user, rankings_by_user, holdout, config, fallback_users).to_dict()
    metrics["evaluation_mode"] = evaluation_mode
    metrics["source_diagnostics"] = source_diagnostics
    if evaluation_mode == "leave_one_positive_out":
        metrics.update(lopo_stats)
    metrics["agent_evaluation_feedback"] = feedback_constraints.to_dict() if feedback_constraints else {}
    metrics["inference_policy"] = _mode_inference_summary(recommendation_rows)
    metrics["config_summary"] = _config_summary(config, clean_dir, views_dir, limit_users, evaluation_mode, lopo_stats)
    if evaluation_mode == "leave_one_positive_out":
        metrics["sample_limitations"].append(
            "Leave-one-positive-out is a demo internal train split; recall views may still be built from the full train artifact."
        )
        metrics["sample_limitations"].append(
            f"Leave-one-positive-out evaluated {lopo_stats.get('lopo_eligible_users', 0)} of "
            f"{lopo_stats.get('lopo_input_users', 0)} input users; "
            f"{lopo_stats.get('lopo_skipped_users_fewer_than_2_positives', 0)} users were skipped because they had fewer than 2 positives."
        )

    ranking_cases = _ranking_hit_cases(candidates_by_user, holdout, config)
    ranking_case_summary = _ranking_case_summary(ranking_cases)
    recommendations_path = output_dir / "recommendations.jsonl"
    metrics_path = output_dir / "metrics.json"
    ranking_cases_path = output_dir / "ranking_hit_cases.jsonl"
    ranking_case_summary_path = output_dir / "ranking_case_summary.json"
    write_jsonl(recommendations_path, recommendation_rows)
    write_jsonl(ranking_cases_path, ranking_cases)
    write_json(ranking_case_summary_path, ranking_case_summary)
    write_json(metrics_path, metrics)
    _write_report(report_path, config, metrics, recommendation_rows, ranking_case_summary)

    return {
        "recommendations_path": str(recommendations_path),
        "metrics_path": str(metrics_path),
        "ranking_cases_path": str(ranking_cases_path),
        "ranking_case_summary_path": str(ranking_case_summary_path),
        "report_path": str(report_path),
        "metrics": metrics,
    }


def run_qwen_evaluation_harness(
    config_path: str | Path,
    limit_users: int | None = None,
    inference_client: RerankPolicyClient | None = None,
    feedback_text: str = "I prefer Audio and bluetooth",
    output_dir: str | Path | None = None,
    qwen_model_id: str | None = None,
    qwen_max_new_tokens: int | None = None,
) -> dict[str, Any]:
    base_config = load_config(config_path)
    base_output_dir = _resolve_path(output_dir or base_config.get("evaluation_harness_output_dir", "outputs/qwen_evaluation_harness"))
    feedback_constraints = parse_feedback(normalize_feedback_input(feedback_text))
    feedback_defaults = _feedback_evaluation_defaults(base_config)
    qwen_overrides = _merge_nested(_qwen_evaluation_defaults(base_config), feedback_defaults)
    if qwen_model_id:
        qwen_overrides.setdefault("inference_policy", {}).setdefault("model", {})["model_id"] = qwen_model_id
    if qwen_max_new_tokens is not None:
        qwen_overrides.setdefault("inference_policy", {}).setdefault("model", {})["max_new_tokens"] = qwen_max_new_tokens
    qwen_client = inference_client or _build_harness_inference_client(base_config, qwen_overrides)
    mode_specs = [
        ("deterministic_baseline", {"inference_policy": {"enabled": False}, "rerank_policy": {"enabled": False}}, None, None),
        ("rule_feedback_rerank", _merge_nested({"inference_policy": {"enabled": False}}, feedback_defaults), feedback_constraints, None),
        ("qwen_feedback_rerank", qwen_overrides, feedback_constraints, qwen_client),
    ]
    mode_results: dict[str, Any] = {}
    for mode_name, overrides, constraints, client in mode_specs:
        report_path = base_output_dir / mode_name / "report.md"
        mode_overrides = _merge_nested(
            overrides,
            {
                "output_dir": str(base_output_dir / mode_name),
                "report_path": str(report_path),
                "strategy_name": f"evaluation_{mode_name}",
            },
        )
        mode_results[mode_name] = run_hybrid_demo(
            config_path,
            limit_users=limit_users,
            inference_client=client,
            config_overrides=mode_overrides,
            feedback_constraints=constraints,
        )
    comparison = _evaluation_comparison(mode_results, feedback_text)
    comparison_path = base_output_dir / "comparison.json"
    report_path = base_output_dir / "comparison.md"
    write_json(comparison_path, comparison)
    report_path.write_text(_evaluation_comparison_report(comparison), encoding="utf-8")
    return {
        "comparison_path": str(comparison_path),
        "report_path": str(report_path),
        "modes": {mode: {key: value for key, value in result.items() if key != "metrics"} for mode, result in mode_results.items()},
        "comparison": comparison,
    }


def _build_harness_inference_client(config: dict[str, Any], config_overrides: dict[str, Any]) -> RerankPolicyClient | None:
    policy = resolve_inference_policy_config(_merge_nested(config, config_overrides))
    if not policy.get("enabled") or policy.get("provider") != "qwen_local":
        return None
    from rs_core.rsagent.qwen_client import QwenLocalClient

    return QwenLocalClient(policy)


def _feedback_constraints_from_config(config: dict[str, Any], feedback_text: str | None) -> FeedbackConstraints | None:
    text = feedback_text if feedback_text is not None else config.get("evaluation_feedback")
    if not text:
        return None
    return parse_feedback(normalize_feedback_input(str(text)))


def _qwen_evaluation_defaults(config: dict[str, Any]) -> dict[str, Any]:
    configured = dict(config.get("inference_policy", {}) or {})
    model = dict(configured.get("model", {}) or {})
    prompt = dict(configured.get("prompt", {}) or {})
    signals = dict(configured.get("signals", {}) or {})
    model.setdefault("max_new_tokens", 256)
    model.setdefault("do_sample", False)
    prompt.setdefault("max_candidates", 5)
    prompt.setdefault("metadata_fields", ["title_clean", "category", "main_category"])
    prompt.setdefault("max_metadata_chars_per_field", 120)
    signals.setdefault("max_signals", 1)
    return {
        "inference_policy": {
            **configured,
            "enabled": True,
            "model": model,
            "prompt": prompt,
            "signals": signals,
        }
    }


def _feedback_evaluation_defaults(config: dict[str, Any]) -> dict[str, Any]:
    rank_weights = dict(config.get("rank_weights", {}))
    rank_weights.setdefault("feedback_category", 10.0)
    rank_weights.setdefault("feedback_keyword", 10.0)
    rank_weights.setdefault("feedback_keyword_penalty", 10.0)
    rank_weights.setdefault("feedback_model_rerank", 10.0)
    return {
        "feedback_category_boost": config.get("feedback_category_boost", 1.0),
        "feedback_keyword_boost": config.get("feedback_keyword_boost", 1.0),
        "feedback_keyword_penalty": config.get("feedback_keyword_penalty", 1.0),
        "rank_weights": rank_weights,
    }


def _mode_inference_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summaries = [row.get("diagnostics", {}).get("inference_policy", {}) for row in rows]
    accepted = sum(int(summary.get("accepted_signal_count", 0) or 0) for summary in summaries)
    rejected = sum(int(summary.get("rejected_signal_count", 0) or 0) for summary in summaries)
    fallback_count = sum(1 for summary in summaries if summary.get("fallback_used"))
    routes = Counter(str(summary.get("route", "missing")) for summary in summaries)
    model_ids = sorted({str(summary.get("model_id")) for summary in summaries if summary.get("model_id")})
    return {
        "accepted_signal_count": accepted,
        "rejected_signal_count": rejected,
        "fallback_count": fallback_count,
        "routes": dict(sorted(routes.items())),
        "model_ids": model_ids,
    }


def _evaluation_comparison(mode_results: dict[str, dict[str, Any]], feedback_text: str) -> dict[str, Any]:
    metric_keys = [
        "hit_rate_at_k",
        "candidate_hit_rate_at_pool",
        "ranked_hit_users",
        "candidate_hit_users",
        "fallback_rate",
        "candidate_count_avg",
        "category_diversity_avg",
    ]
    modes: dict[str, Any] = {}
    for mode, result in mode_results.items():
        metrics = result.get("metrics", {})
        modes[mode] = {
            "metrics": {key: metrics.get(key) for key in metric_keys},
            "agent_evaluation_feedback": metrics.get("agent_evaluation_feedback", {}),
            "inference_policy": metrics.get("inference_policy", {}),
            "paths": {key: value for key, value in result.items() if key.endswith("_path")},
        }
    return {
        "feedback_text": feedback_text,
        "mode_order": list(mode_results.keys()),
        "modes": modes,
        "rank_delta": _evaluation_rank_delta_summary(mode_results),
    }


def _evaluation_rank_delta_summary(mode_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cases_by_mode = {
        mode: _ranking_cases_by_key(read_jsonl(result["ranking_cases_path"]))
        for mode, result in mode_results.items()
        if result.get("ranking_cases_path")
    }
    baseline = cases_by_mode.get("deterministic_baseline", {})
    qwen = cases_by_mode.get("qwen_feedback_rerank", {})
    rule = cases_by_mode.get("rule_feedback_rerank", {})
    rank_deltas: list[int] = []
    rule_rank_deltas: list[int] = []
    improved = worsened = unchanged = 0
    topk_gained = topk_lost = 0
    signal_on_target = 0
    signal_on_non_target = 0
    non_target_signal_above_target = 0
    harmful_non_target_signal_cases = 0
    examples: list[dict[str, Any]] = []
    for key, qwen_case in sorted(qwen.items()):
        base_case = baseline.get(key)
        if not base_case:
            continue
        base_rank = int(base_case.get("target_rank", 0) or 0)
        qwen_rank = int(qwen_case.get("target_rank", 0) or 0)
        if not base_rank or not qwen_rank:
            continue
        delta = base_rank - qwen_rank
        rank_deltas.append(delta)
        if delta > 0:
            improved += 1
        elif delta < 0:
            worsened += 1
        else:
            unchanged += 1
        if not base_case.get("is_topk_hit") and qwen_case.get("is_topk_hit"):
            topk_gained += 1
        if base_case.get("is_topk_hit") and not qwen_case.get("is_topk_hit"):
            topk_lost += 1
        rule_case = rule.get(key)
        if rule_case:
            rule_rank = int(rule_case.get("target_rank", 0) or 0)
            if rule_rank:
                rule_rank_deltas.append(rule_rank - qwen_rank)
        target_has_signal = _case_target_has_qwen_signal(qwen_case)
        non_target_signal_count = _case_non_target_qwen_signal_count(qwen_case)
        if target_has_signal:
            signal_on_target += 1
        if non_target_signal_count:
            signal_on_non_target += 1
            non_target_signal_above_target += non_target_signal_count
            if delta <= 0:
                harmful_non_target_signal_cases += 1
        examples.append({
            "user_id": qwen_case.get("user_id"),
            "target_item": qwen_case.get("target_item"),
            "deterministic_rank": base_rank,
            "rule_rank": int(rule_case.get("target_rank", 0) or 0) if rule_case else None,
            "qwen_rank": qwen_rank,
            "rank_improvement_delta": delta,
            "qwen_topk_hit": bool(qwen_case.get("is_topk_hit")),
            "qwen_signal_on_target": target_has_signal,
            "qwen_non_target_signals_above_target": non_target_signal_count,
        })
    return {
        "baseline_mode": "deterministic_baseline",
        "qwen_mode": "qwen_feedback_rerank",
        "comparable_cases": len(rank_deltas),
        "target_rank_improved_count": improved,
        "target_rank_worsened_count": worsened,
        "target_rank_unchanged_count": unchanged,
        "target_rank_delta_avg": _avg([float(value) for value in rank_deltas]),
        "target_rank_delta_vs_rule_avg": _avg([float(value) for value in rule_rank_deltas]),
        "topk_gained_count": topk_gained,
        "topk_lost_count": topk_lost,
        "qwen_signal_on_target_count": signal_on_target,
        "qwen_signal_on_non_target_count": signal_on_non_target,
        "qwen_non_target_signals_above_target_count": non_target_signal_above_target,
        "harmful_non_target_signal_cases": harmful_non_target_signal_cases,
        "examples": examples[:10],
    }


def _ranking_cases_by_key(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(row.get("user_id", "")), str(row.get("target_item", ""))): row
        for row in rows
        if row.get("user_id") and row.get("target_item")
    }


def _case_target_has_qwen_signal(row: dict[str, Any]) -> bool:
    target = row.get("target_item")
    for item in row.get("top_items", []):
        if item.get("parent_asin") == target:
            return _item_has_qwen_signal(item)
    return "feedback_model_rerank" in set(row.get("target_sources", []))


def _case_non_target_qwen_signal_count(row: dict[str, Any]) -> int:
    target = row.get("target_item")
    return sum(
        1
        for item in row.get("items_above_target", [])
        if item.get("parent_asin") != target and _item_has_qwen_signal(item)
    )


def _item_has_qwen_signal(item: dict[str, Any]) -> bool:
    return any(event.get("type") == "qwen_rerank_signal" for event in item.get("rerank_events", []))


def _evaluation_comparison_report(comparison: dict[str, Any]) -> str:
    metric_keys = [
        "hit_rate_at_k",
        "candidate_hit_rate_at_pool",
        "ranked_hit_users",
        "candidate_hit_users",
        "fallback_rate",
        "candidate_count_avg",
        "category_diversity_avg",
    ]
    lines = [
        "# Qwen Evaluation Harness Comparison",
        "",
        "## Scope",
        "",
        "Compares deterministic baseline, deterministic feedback rerank, and optional Qwen feedback rerank over the same recommendation inputs.",
        "",
        f"- feedback_text: `{comparison.get('feedback_text', '')}`",
        "",
        "## Metrics",
        "",
        "| Mode | " + " | ".join(metric_keys) + " |",
        "| --- | " + " | ".join("---" for _ in metric_keys) + " |",
    ]
    for mode in comparison.get("mode_order", []):
        metrics = comparison.get("modes", {}).get(mode, {}).get("metrics", {})
        lines.append("| " + mode + " | " + " | ".join(str(metrics.get(key)) for key in metric_keys) + " |")
    rank_delta = comparison.get("rank_delta", {})
    lines.extend([
        "",
        "## Rank Delta Summary",
        "",
        f"- comparable_cases: {rank_delta.get('comparable_cases')}",
        f"- target_rank_improved_count: {rank_delta.get('target_rank_improved_count')}",
        f"- target_rank_worsened_count: {rank_delta.get('target_rank_worsened_count')}",
        f"- target_rank_unchanged_count: {rank_delta.get('target_rank_unchanged_count')}",
        f"- target_rank_delta_avg: {rank_delta.get('target_rank_delta_avg')}",
        f"- topk_gained_count: {rank_delta.get('topk_gained_count')}",
        f"- topk_lost_count: {rank_delta.get('topk_lost_count')}",
        f"- qwen_signal_on_target_count: {rank_delta.get('qwen_signal_on_target_count')}",
        f"- qwen_signal_on_non_target_count: {rank_delta.get('qwen_signal_on_non_target_count')}",
        f"- harmful_non_target_signal_cases: {rank_delta.get('harmful_non_target_signal_cases')}",
        "",
        "| User | Target | deterministic_rank | rule_rank | qwen_rank | rank_improvement_delta | signal_on_target | non_target_signals_above |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for example in rank_delta.get("examples", []):
        lines.append(
            f"| {example.get('user_id')} | {example.get('target_item')} | "
            f"{example.get('deterministic_rank')} | {example.get('rule_rank')} | {example.get('qwen_rank')} | "
            f"{example.get('rank_improvement_delta')} | {example.get('qwen_signal_on_target')} | "
            f"{example.get('qwen_non_target_signals_above_target')} |"
        )
    lines.extend([
        "",
        "## Inference Policy Diagnostics",
        "",
        "| Mode | accepted_signals | rejected_signals | fallback_count | routes |",
        "| --- | --- | --- | --- | --- |",
    ])
    for mode in comparison.get("mode_order", []):
        policy = comparison.get("modes", {}).get(mode, {}).get("inference_policy", {})
        lines.append(
            f"| {mode} | {policy.get('accepted_signal_count')} | {policy.get('rejected_signal_count')} | "
            f"{policy.get('fallback_count')} | `{json.dumps(policy.get('routes', {}), ensure_ascii=False)}` |"
        )
    lines.extend(["", "## Artifacts", ""])
    for mode in comparison.get("mode_order", []):
        paths = comparison.get("modes", {}).get(mode, {}).get("paths", {})
        lines.append(f"### {mode}")
        lines.append("")
        for key, value in sorted(paths.items()):
            lines.append(f"- {key}: `{value}`")
        lines.append("")
    return "\n".join(lines)


def recommend_for_user(
    user_sequence: dict[str, Any],
    popular: list[Any],
    itemcf_weak: dict[str, list[Any]],
    itemcf_strong: dict[str, list[Any]],
    category_top: dict[str, list[Any]],
    item_category: dict[str, str],
    config: dict[str, Any],
    semantic_index: dict[str, dict[str, Any]] | None = None,
    feedback_constraints: FeedbackConstraints | None = None,
    prior_turn_items: set[str] | None = None,
    inference_client: RerankPolicyClient | None = None,
    turn_index: int | None = None,
) -> RecommendationTurnResult:
    user_id = user_sequence.get("user_id", "")
    candidates, fallback_used = merge_for_user(
        user_sequence, popular, itemcf_weak, itemcf_strong, category_top, item_category, config, semantic_index
    )
    candidates, feedback_diagnostics = apply_feedback_to_candidates(
        candidates, feedback_constraints, config, prior_turn_items
    )
    candidates, inference_diagnostics = apply_optional_inference_policy(
        user_sequence=user_sequence,
        candidates=candidates,
        feedback_constraints=feedback_constraints,
        config=config,
        client=inference_client,
        turn_index=turn_index,
    )
    ranking = rank_candidates(user_id, candidates, config)
    ranking.fallback_used = fallback_used
    diagnostics = {
        "candidate_count": len(candidates),
        "source_coverage": _candidate_source_coverage(candidates),
        **feedback_diagnostics,
        **inference_diagnostics,
    }
    decision = make_agent_decision(user_id, ranking, config, diagnostics)
    return RecommendationTurnResult(
        candidates=candidates,
        ranking=ranking,
        decision=decision,
        fallback_used=fallback_used,
        diagnostics=diagnostics,
    )


def _merge_nested(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_nested(merged[key], value)
        else:
            merged[key] = value
    return merged


def _candidate_source_coverage(candidates: list[Any]) -> dict[str, int]:
    coverage: Counter[str] = Counter()
    for candidate in candidates:
        for source in candidate.sources:
            coverage[source] += 1
    return dict(sorted(coverage.items()))


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _required_paths(clean_dir: Path, views_dir: Path) -> dict[str, Path]:
    return {
        "sequences": clean_dir / "user_sequences.train.jsonl",
        "popular": views_dir / "popular_recall.jsonl",
        "itemcf_weak": views_dir / "itemcf_recall_weak.jsonl",
        "itemcf_strong": views_dir / "itemcf_recall_strong.jsonl",
        "category_items": views_dir / "category_recall_items.jsonl",
        "category_top": views_dir / "category_top_items.jsonl",
    }


def _ensure_inputs(paths: dict[str, Path]) -> None:
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing hybrid demo inputs: " + ", ".join(missing))


def _load_item_category(path: Path) -> dict[str, str]:
    mapping = {}
    for row in read_jsonl(path):
        if row.get("parent_asin"):
            mapping[row["parent_asin"]] = row.get("main_category") or row.get("category", "")
    return mapping


def _leave_one_positive_out_sequences(
    train_sequences: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    evaluation_sequences = []
    holdout = []
    stats = {
        "lopo_input_users": len(train_sequences),
        "lopo_eligible_users": 0,
        "lopo_skipped_users_fewer_than_2_positives": 0,
    }
    for sequence in train_sequences:
        positives = sequence.get("recent_positive_item_sequence", [])
        positive_timestamps = sequence.get("recent_positive_timestamp_sequence", [])
        if len(positives) < 2:
            stats["lopo_skipped_users_fewer_than_2_positives"] += 1
            continue
        stats["lopo_eligible_users"] += 1
        heldout_item = positives[-1]
        updated = dict(sequence)
        updated["recent_item_sequence"], updated["recent_timestamp_sequence"] = _remove_item_timestamps(
            sequence.get("recent_item_sequence", []),
            sequence.get("recent_timestamp_sequence", []),
            heldout_item,
        )
        updated["recent_positive_item_sequence"], updated["recent_positive_timestamp_sequence"] = _remove_item_timestamps(
            positives,
            positive_timestamps,
            heldout_item,
        )
        updated["recent_strong_positive_item_sequence"], updated["recent_strong_positive_timestamp_sequence"] = _remove_item_timestamps(
            sequence.get("recent_strong_positive_item_sequence", []),
            sequence.get("recent_strong_positive_timestamp_sequence", []),
            heldout_item,
        )
        updated["sequence_len"] = len(updated.get("recent_item_sequence", []))
        updated["positive_sequence_len"] = len(updated.get("recent_positive_item_sequence", []))
        updated["strong_positive_sequence_len"] = len(updated.get("recent_strong_positive_item_sequence", []))
        evaluation_sequences.append(updated)
        holdout.append({"user_id": sequence.get("user_id", ""), "parent_asin": heldout_item, "label_binary": 1})
    return evaluation_sequences, holdout, stats


def _remove_item_timestamps(
    items: list[Any],
    timestamps: list[Any],
    target_item: Any,
) -> tuple[list[Any], list[Any]]:
    updated_items = []
    updated_timestamps = []
    timestamps_are_aligned = len(timestamps) == len(items)
    for index, item in enumerate(items):
        if item == target_item:
            continue
        updated_items.append(item)
        if timestamps_are_aligned:
            updated_timestamps.append(timestamps[index])
    return updated_items, updated_timestamps


def _source_diagnostics(
    train_sequences: list[dict[str, Any]],
    itemcf_weak: dict[str, list[Any]],
    itemcf_strong: dict[str, list[Any]],
) -> dict[str, int]:
    users_with_positive_seeds = 0
    users_with_itemcf_seed_hits = 0
    users_with_itemcf_raw_candidates = 0
    itemcf_raw_candidates = 0
    itemcf_raw_unseen_candidates = 0
    itemcf_seed_items = set(itemcf_weak) | set(itemcf_strong)
    for sequence in train_sequences:
        seen_items = set(sequence.get("recent_item_sequence", []))
        seeds = set(sequence.get("recent_positive_item_sequence", [])) | set(
            sequence.get("recent_strong_positive_item_sequence", [])
        )
        if seeds:
            users_with_positive_seeds += 1
        if seeds & itemcf_seed_items:
            users_with_itemcf_seed_hits += 1
        raw_items = []
        for seed in seeds:
            raw_items.extend(candidate.item_id for candidate in itemcf_weak.get(seed, []))
            raw_items.extend(candidate.item_id for candidate in itemcf_strong.get(seed, []))
        if raw_items:
            users_with_itemcf_raw_candidates += 1
        itemcf_raw_candidates += len(raw_items)
        itemcf_raw_unseen_candidates += sum(1 for item_id in raw_items if item_id not in seen_items)
    return {
        "users_with_positive_seeds": users_with_positive_seeds,
        "users_with_itemcf_seed_hits": users_with_itemcf_seed_hits,
        "users_with_itemcf_raw_candidates": users_with_itemcf_raw_candidates,
        "itemcf_raw_candidates": itemcf_raw_candidates,
        "itemcf_raw_unseen_candidates": itemcf_raw_unseen_candidates,
    }


def _itemcf_seed_items(train_sequences: list[dict[str, Any]]) -> set[str]:
    seeds: set[str] = set()
    for sequence in train_sequences:
        seeds.update(sequence.get("recent_positive_item_sequence", []))
        seeds.update(sequence.get("recent_strong_positive_item_sequence", []))
    return seeds


def _ranking_hit_cases(
    candidates_by_user: dict[str, list[Any]],
    holdout_records: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    positives = heldout_positives(holdout_records)
    rows: list[dict[str, Any]] = []
    for user_id in sorted(candidates_by_user):
        targets = positives.get(user_id, set())
        if not targets:
            continue
        candidates = candidates_by_user[user_id]
        full_ranking = rank_candidates(user_id, candidates, config, top_k=len(candidates) or int(config.get("top_k", 5))).items
        for target in sorted(targets):
            rank = _rank_of_item(full_ranking, target)
            if rank is None:
                continue
            item = full_ranking[rank - 1]
            rows.append({
                "user_id": user_id,
                "target_item": target,
                "target_rank": rank,
                "target_score": item.get("score"),
                "target_sources": item.get("sources", []),
                "target_source_scores": _candidate_source_scores(candidates, target),
                "top_k": int(config.get("top_k", 5)),
                "is_topk_hit": rank <= int(config.get("top_k", 5)),
                "items_above_target": full_ranking[: rank - 1],
                "top_items": full_ranking[: int(config.get("top_k", 5))],
            })
    return rows


def _ranking_case_summary(ranking_cases: list[dict[str, Any]]) -> dict[str, Any]:
    missed_cases = [row for row in ranking_cases if not row.get("is_topk_hit")]
    above_source_combinations: Counter[str] = Counter()
    top_item_source_combinations: Counter[str] = Counter()
    target_source_combinations: Counter[str] = Counter()
    score_gaps: list[float] = []
    semantic_only_above = 0
    above_items_total = 0
    for row in missed_cases:
        target_source_combinations[_source_key(row.get("target_sources", []))] += 1
        target_score = float(row.get("target_score") or 0.0)
        top_items = row.get("top_items", [])
        if top_items:
            score_gaps.append(round(float(top_items[0].get("score") or 0.0) - target_score, 6))
        for item in row.get("items_above_target", []):
            key = _source_key(item.get("sources", []))
            above_source_combinations[key] += 1
            above_items_total += 1
            if key == "semantic":
                semantic_only_above += 1
        for item in top_items:
            top_item_source_combinations[_source_key(item.get("sources", []))] += 1
    return {
        "total_hit_cases": len(ranking_cases),
        "topk_hit_cases": len(ranking_cases) - len(missed_cases),
        "missed_topk_cases": len(missed_cases),
        "target_source_combinations": dict(sorted(target_source_combinations.items())),
        "items_above_source_combinations": dict(above_source_combinations.most_common()),
        "top_item_source_combinations": dict(top_item_source_combinations.most_common()),
        "items_above_total": above_items_total,
        "semantic_only_items_above_share": round(semantic_only_above / above_items_total, 6) if above_items_total else 0.0,
        "top1_score_gap_avg": _avg(score_gaps),
        "top1_score_gap_max": max(score_gaps) if score_gaps else 0.0,
        "top1_score_gap_min": min(score_gaps) if score_gaps else 0.0,
    }


def _source_key(sources: list[Any]) -> str:
    return "+".join(sorted(str(source) for source in sources)) or "unknown"


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _rank_of_item(items: list[dict[str, Any]], item_id: str) -> int | None:
    for index, item in enumerate(items, start=1):
        if item.get("parent_asin") == item_id:
            return index
    return None


def _candidate_source_scores(candidates: list[Any], item_id: str) -> dict[str, float]:
    for candidate in candidates:
        if candidate.item_id == item_id:
            return {source: float(score) for source, score in sorted(candidate.source_scores.items())}
    return {}


def _config_summary(
    config: dict[str, Any],
    clean_dir: Path,
    views_dir: Path,
    limit_users: int | None,
    evaluation_mode: str,
    lopo_stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    summary = {
        "clean_dir": str(clean_dir),
        "views_dir": str(views_dir),
        "evaluation_mode": evaluation_mode,
        "top_k": config.get("top_k", 5),
        "candidate_pool_size": config.get("candidate_pool_size", 50),
        "limit_users": limit_users,
        "rank_weights": config.get("rank_weights", {}),
        "rerank_policy": config.get("rerank_policy", {}),
        "item_feature_rerank": config.get("item_feature_rerank", {}),
        "topk_source_minimums": config.get("topk_source_minimums", {}),
        "candidate_source_minimums": config.get("candidate_source_minimums", {}),
        "semantic_enabled": bool(config.get("semantic_enabled", False)),
        "semantic_per_user": config.get("semantic_per_user"),
        "semantic_min_overlap": config.get("semantic_min_overlap"),
        "semantic_score_mode": config.get("semantic_score_mode", "raw"),
        "semantic_category_weight": config.get("semantic_category_weight", 2.0),
        "semantic_text_fields": config.get("semantic_text_fields"),
    }
    if lopo_stats:
        summary.update(lopo_stats)
    return summary


def _write_report(
    path: Path,
    config: dict[str, Any],
    metrics: dict[str, Any],
    rows: list[dict[str, Any]],
    ranking_case_summary: dict[str, Any] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    examples = rows[: int(config.get("sample_examples", 3))]
    lines = [
        "# Hybrid Demo Small Report",
        "",
        "## Config Summary",
        "",
        "```json",
        json.dumps(metrics.get("config_summary", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Metrics and Ablation",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    for key in [
        "evaluation_mode",
        "users_total",
        "users_with_holdout",
        "users_evaluated",
        "lopo_input_users",
        "lopo_eligible_users",
        "lopo_skipped_users_fewer_than_2_positives",
        "hit_rate_denominator",
        "candidate_count_avg",
        "fallback_rate",
        "candidate_hit_rate_at_pool",
        "candidate_hit_users",
        "candidate_hit_rank_min",
        "candidate_hit_rank_avg",
        "candidate_hit_rank_p50",
        "candidate_hit_missed_topk_users",
        "ranked_hit_users",
        "hit_rate_at_k",
        "popular_only_hit_rate_at_k",
        "itemcf_only_hit_rate_at_k",
        "hybrid_hit_rate_at_k",
        "hybrid_no_itemcf_hit_rate_at_k",
        "category_diversity_avg",
    ]:
        lines.append(f"| {key} | {metrics.get(key)} |")
    lines.extend([
        "",
        "## Fallback and Source Coverage",
        "",
        f"- fallback_rate: {metrics.get('fallback_rate')}",
        f"- recall_source_coverage: `{json.dumps(metrics.get('recall_source_coverage', {}), ensure_ascii=False)}`",
        f"- topk_source_coverage: `{json.dumps(metrics.get('topk_source_coverage', {}), ensure_ascii=False)}`",
        f"- source_diagnostics: `{json.dumps(metrics.get('source_diagnostics', {}), ensure_ascii=False)}`",
        "",
        "## Recall Bottleneck Diagnostics",
        "",
        f"- candidate_hit_rate_at_pool: {metrics.get('candidate_hit_rate_at_pool')}",
        f"- candidate_hit_users: {metrics.get('candidate_hit_users')}",
        f"- ranked_hit_users: {metrics.get('ranked_hit_users')}",
        f"- candidate_hit_missed_topk_users: {metrics.get('candidate_hit_missed_topk_users')}",
        f"- candidate_hit_rank_min: {metrics.get('candidate_hit_rank_min')}",
        f"- candidate_hit_rank_avg: {metrics.get('candidate_hit_rank_avg')}",
        f"- candidate_hit_rank_p50: {metrics.get('candidate_hit_rank_p50')}",
        f"- candidate_hit_source_coverage: `{json.dumps(metrics.get('candidate_hit_source_coverage', {}), ensure_ascii=False)}`",
        "",
        "## Ranking Case Summary",
        "",
        f"- total_hit_cases: {(ranking_case_summary or {}).get('total_hit_cases', 0)}",
        f"- topk_hit_cases: {(ranking_case_summary or {}).get('topk_hit_cases', 0)}",
        f"- missed_topk_cases: {(ranking_case_summary or {}).get('missed_topk_cases', 0)}",
        f"- semantic_only_items_above_share: {(ranking_case_summary or {}).get('semantic_only_items_above_share', 0.0)}",
        f"- top1_score_gap_avg: {(ranking_case_summary or {}).get('top1_score_gap_avg', 0.0)}",
        f"- target_source_combinations: `{json.dumps((ranking_case_summary or {}).get('target_source_combinations', {}), ensure_ascii=False)}`",
        f"- items_above_source_combinations: `{json.dumps((ranking_case_summary or {}).get('items_above_source_combinations', {}), ensure_ascii=False)}`",
        "",
        "## Sample Limitations",
        "",
    ])
    for limitation in metrics.get("sample_limitations", []):
        lines.append(f"- {limitation}")
    if not metrics.get("sample_limitations"):
        lines.append("- None reported.")
    lines.extend(["", "## Recommendation Examples", ""])
    for row in examples:
        lines.append(f"### User {row.get('user_id')}")
        lines.append("")
        lines.append(f"- strategy: {row.get('strategy_name')}")
        lines.append(f"- risk_flags: {', '.join(row.get('risk_flags', [])) or 'none'}")
        lines.append("- items:")
        for item in row.get("final_items", [])[:5]:
            lines.append(f"  - {item.get('parent_asin')} score={item.get('score')} sources={','.join(item.get('sources', []))}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
