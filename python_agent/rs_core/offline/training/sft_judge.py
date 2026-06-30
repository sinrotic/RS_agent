from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from rs_core.common.io import iter_jsonl, write_json, write_jsonl
from rs_core.offline.training.data_contracts import SFT_SAMPLE_SCHEMA_VERSION, validate_sft_sample

MULTI_TURN_SFT_SCHEMA_VERSION = "rs_agent_multi_turn_sft_sample_v1"
SFT_JUDGE_SCHEMA_VERSION = "rs_agent_sft_judge_v1"
SFT_JUDGE_RUN_SCHEMA_VERSION = "rs_agent_sft_judge_run_v1"
RUBRIC_SOURCE = "dic/standards/AGENT_SCORING_FRAMEWORK.md"

RUBRIC_WEIGHTS = {
    "intent_understanding": 15,
    "recommendation_relevance": 20,
    "candidate_pool_consistency": 15,
    "rag_grounding": 15,
    "dialogue_quality": 10,
    "explanation_quality": 10,
    "format_protocol": 10,
    "training_value": 5,
}

FORBIDDEN_PUBLIC_KEYS = {
    "diagnostics",
    "agent_runtime_trace",
    "agent_tool_summary",
    "tool_traces",
    "source_scores",
    "rag_context",
    "rag_agent_support",
    "rag_agent_shadow",
    "raw_rag_evidence",
    "trace_events",
    "commit_intents",
    "internal_output",
    "manifest",
    "retriever",
    "reward",
    "training_samples",
    "label_binary",
    "target_item",
    "ground_truth",
    "oracle",
}

LEAKAGE_TERMS = re.compile(
    r"(?<![\w])(?:"
    r"ground[\s_\-]*truth|oracle|click[\s_\-]*label|label[\s_\-]*(?:binary|score|target)|"
    r"positive[\s_\-]*sample|holdout|deepfm[\s_\-]*score|recall[\s_\-]*score|"
    r"ranking[\s_\-]*score|internal[\s_\-]*score|source[\s_\-]*scores?|"
    r"真实标签|点击标签|正样本|测试标签|留出集|评估标签|标签分|内部分|排序分|召回分|神谕"
    r")(?![\w])",
    re.IGNORECASE,
)
UNSUPPORTED_CLAIM_TERMS = re.compile(
    r"(?:\b(?:best[\s_\-]*seller|top[\s_\-]*rated|five[\s_\-]*stars?|discount(?:ed)?|sale|sales|"
    r"in[\s_\-]*stock|stock|rating|ratings?|review[\s_\-]*count)\b|"
    r"库存|现货|有货|销量|销售|折扣|促销|打折|热销|官方认证|五星|评分|高评分|好评率)",
    re.IGNORECASE,
)
UNSAFE_TOOL_TERMS = re.compile(r"(?<![\w])(?:query[\s_\-]*rag|get[\s_\-]*item[\s_\-]*evidence|raw[\s_\-]*rag|rag[\s_\-]*support|support[\s_\-]*evidence)(?![\w])", re.IGNORECASE)
ITEM_REF_TERMS = re.compile(r"(?<![\w])(?:item_id|parent_asin|asin|商品ID|商品编号)\s*[:：=#-]?\s*([A-Za-z0-9][A-Za-z0-9_-]*)(?![\w])", re.IGNORECASE)
ASIN_LIKE_TERMS = re.compile(r"(?<![A-Za-z0-9_])B[A-Z0-9]{9}(?![A-Za-z0-9_])")
TEMPLATE_TRACES = re.compile(r"prefer categories|prefer features|parent_asin", re.IGNORECASE)


@dataclass(frozen=True)
class SftJudgePolicy:
    min_accept_score: int = 85
    min_accept_light_score: int = 75
    min_rewrite_score: int = 60
    require_accept_decision_for_satisfaction: bool = True


class ThirdPartySftJudgeAgent:
    """Lightweight third-party SFT judge aligned with the project scoring rubric.

    The judge is intentionally deterministic and local: it enforces hard gates with
    project contracts first, then applies the documented 0-5 rubric. This keeps
    smoke/full-data checks safe on a 12GB-class local machine and avoids loading
    model weights just to quality-gate generated samples.
    """

    def __init__(self, policy: SftJudgePolicy | None = None) -> None:
        self.policy = policy or SftJudgePolicy()

    def judge(self, record: dict[str, Any]) -> dict[str, Any]:
        input_schema = str(record.get("schema_version") or "")
        hard_fail_reasons = _hard_fail_reasons(record)
        contract_checks = _contract_checks(record)
        if contract_checks["schema_valid"] is False:
            hard_fail_reasons.append(str(contract_checks.get("schema_error") or "schema validation failed"))

        scores, score_evidence = _rubric_scores(record, contract_checks, hard_fail=bool(hard_fail_reasons))
        total_score = _weighted_total(scores)
        if hard_fail_reasons:
            total_score = min(total_score, 59)
        decision = _decision(total_score, hard_fail=bool(hard_fail_reasons), policy=self.policy)
        sample_id = str(record.get("sample_id") or record.get("metadata", {}).get("source_sample_id") or "unknown")

        return {
            "schema_version": SFT_JUDGE_SCHEMA_VERSION,
            "sample_id": sample_id,
            "input_schema_version": input_schema,
            "rubric_source": RUBRIC_SOURCE,
            "hard_fail": bool(hard_fail_reasons),
            "hard_fail_reasons": sorted(set(hard_fail_reasons)),
            "contract_checks": contract_checks,
            "scores": scores,
            "total_score": total_score,
            "decision": decision,
            "satisfactory": decision == "accept" if self.policy.require_accept_decision_for_satisfaction else decision in {"accept", "accept_light"},
            "rewrite_suggestion": _rewrite_suggestion(decision, hard_fail_reasons, scores),
            "evidence": score_evidence,
        }

    def judge_many(self, records: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        reports = [self.judge(record) for record in records]
        return reports, summarize_judge_reports(reports, policy=self.policy)


def judge_sft_sample(record: dict[str, Any], *, policy: SftJudgePolicy | None = None) -> dict[str, Any]:
    return ThirdPartySftJudgeAgent(policy).judge(record)


def judge_sft_samples(records: Iterable[dict[str, Any]], *, policy: SftJudgePolicy | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return ThirdPartySftJudgeAgent(policy).judge_many(records)


def judge_jsonl_file(
    input_path: str | Path,
    *,
    output_path: str | Path | None = None,
    summary_path: str | Path | None = None,
    max_samples: int | None = None,
    policy: SftJudgePolicy | None = None,
) -> dict[str, Any]:
    judge = ThirdPartySftJudgeAgent(policy)
    reports: list[dict[str, Any]] = []
    for index, record in enumerate(iter_jsonl(input_path), start=1):
        if max_samples is not None and index > max_samples:
            break
        reports.append(judge.judge(record))
    summary = summarize_judge_reports(reports, policy=judge.policy, input_path=str(input_path))
    if output_path is not None:
        write_jsonl(output_path, reports)
    if summary_path is not None:
        write_json(summary_path, summary)
    return summary


def summarize_judge_reports(
    reports: list[dict[str, Any]],
    *,
    policy: SftJudgePolicy | None = None,
    input_path: str | None = None,
) -> dict[str, Any]:
    policy = policy or SftJudgePolicy()
    total = len(reports)
    decisions = Counter(str(report.get("decision") or "unknown") for report in reports)
    hard_fail_count = sum(1 for report in reports if report.get("hard_fail"))
    satisfactory_count = sum(1 for report in reports if report.get("satisfactory"))
    scores = [int(report.get("total_score") or 0) for report in reports]
    hard_reasons = Counter(reason for report in reports for reason in report.get("hard_fail_reasons", []))
    min_score = min(scores) if scores else 0
    avg_score = round(sum(scores) / total, 4) if total else 0.0
    return {
        "schema_version": SFT_JUDGE_RUN_SCHEMA_VERSION,
        "input_path": input_path,
        "rubric_source": RUBRIC_SOURCE,
        "sample_count": total,
        "avg_score": avg_score,
        "min_score": min_score,
        "decision_counts": dict(decisions),
        "hard_fail_count": hard_fail_count,
        "hard_fail_rate": round(hard_fail_count / total, 4) if total else 0.0,
        "satisfactory_count": satisfactory_count,
        "satisfactory_rate": round(satisfactory_count / total, 4) if total else 0.0,
        "all_satisfactory": bool(total) and satisfactory_count == total,
        "judge_satisfied": bool(total) and satisfactory_count == total and min_score >= policy.min_accept_score,
        "thresholds": {
            "accept": policy.min_accept_score,
            "accept_light": policy.min_accept_light_score,
            "rewrite": policy.min_rewrite_score,
        },
        "hard_fail_reasons": dict(hard_reasons),
    }


def _contract_checks(record: dict[str, Any]) -> dict[str, Any]:
    schema = str(record.get("schema_version") or "")
    checks: dict[str, Any] = {
        "schema_valid": False,
        "required_fields_present": False,
        "selected_subset_of_display": False,
        "selected_subset_of_allowed": False,
        "no_forbidden_internal_fields": not _contains_forbidden_key(record),
        "no_label_or_oracle_leakage": not _contains_leakage_text(record),
        "no_ungrounded_recommendation": True,
        "tool_supervision_safe": True,
    }
    try:
        if schema == MULTI_TURN_SFT_SCHEMA_VERSION:
            _validate_multi_turn(record)
            checks.update(_multi_turn_contract_checks(record))
        elif schema == SFT_SAMPLE_SCHEMA_VERSION:
            validate_sft_sample(record)
            checks.update(_flat_contract_checks(record))
        else:
            raise ValueError(f"unsupported SFT schema_version: {schema or '<missing>'}")
        checks["schema_valid"] = True
        checks["required_fields_present"] = True
    except Exception as exc:
        checks["schema_error"] = str(exc)
    return checks


def _multi_turn_contract_checks(record: dict[str, Any]) -> dict[str, Any]:
    selected_subset_of_display = True
    selected_subset_of_allowed = True
    no_ungrounded_recommendation = True
    tool_supervision_safe = True
    for turn in record.get("dialogue", []):
        if not isinstance(turn, dict):
            continue
        display_ids = {str(item_id) for item_id in turn.get("display_item_ids", []) if str(item_id)}
        selected_ids = {str(item_id) for item_id in turn.get("selected_item_ids", []) if str(item_id)}
        target = turn.get("target_action") if isinstance(turn.get("target_action"), dict) else {}
        allowed_ids = {str(item_id) for item_id in target.get("allowed_item_ids", []) if str(item_id)}
        selected_subset_of_display = selected_subset_of_display and selected_ids <= display_ids and (not allowed_ids or allowed_ids <= display_ids)
        selected_subset_of_allowed = selected_subset_of_allowed and (not allowed_ids or selected_ids <= allowed_ids)
        supervision = turn.get("tool_supervision") if isinstance(turn.get("tool_supervision"), dict) else {}
        should_recommend = bool(supervision.get("should_recommend", bool(display_ids)))
        if (not display_ids or not should_recommend) and _looks_like_recommendation_list(str(turn.get("assistant_message") or "")):
            no_ungrounded_recommendation = False
        tool_names = " ".join(str(name) for name in supervision.get("expected_tool_calls", []) if str(name))
        raw_tool_names = " ".join(str(event.get("tool_name") or "") for event in supervision.get("agent_tool_events", []) if isinstance(event, dict))
        if not _tool_supervision_safe(f"{tool_names} {raw_tool_names}"):
            tool_supervision_safe = False
    return {
        "selected_subset_of_display": selected_subset_of_display,
        "selected_subset_of_allowed": selected_subset_of_allowed,
        "no_ungrounded_recommendation": no_ungrounded_recommendation,
        "tool_supervision_safe": tool_supervision_safe,
    }


def _flat_contract_checks(record: dict[str, Any]) -> dict[str, Any]:
    sample = record.get("sample") if isinstance(record.get("sample"), dict) else {}
    target = sample.get("target_action") if isinstance(sample.get("target_action"), dict) else {}
    selected = {str(item_id) for item_id in target.get("selected_item_ids", []) if str(item_id)}
    allowed = {str(item_id) for item_id in target.get("allowed_item_ids", []) if str(item_id)}
    candidates = {str(candidate.get("item_id")) for candidate in sample.get("candidate_summary", []) if isinstance(candidate, dict) and candidate.get("item_id")}
    supervision = record.get("metadata", {}).get("tool_supervision") if isinstance(record.get("metadata"), dict) else {}
    return {
        "selected_subset_of_display": selected <= candidates,
        "selected_subset_of_allowed": not allowed or selected <= allowed,
        "no_ungrounded_recommendation": bool(candidates),
        "tool_supervision_safe": _tool_supervision_safe(supervision),
    }


def _hard_fail_reasons(record: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if _contains_forbidden_key(record):
        reasons.append("internal_info_leakage")
    if _contains_leakage_text(record):
        reasons.append("label_or_oracle_leakage")
    if _contains_unsupported_claim(record):
        reasons.append("unsupported_product_attribute_claim")
    if _mentions_outside_candidate_pool(record):
        reasons.append("candidate_pool_reference_violation")
    if TEMPLATE_TRACES.search(_all_text(record)):
        reasons.append("simulator_template_trace_leakage")
    checks = _contract_checks(record)
    if checks.get("selected_subset_of_display") is False or checks.get("selected_subset_of_allowed") is False:
        reasons.append("candidate_pool_violation")
    if checks.get("no_ungrounded_recommendation") is False:
        reasons.append("ungrounded_recommendation")
    if checks.get("tool_supervision_safe") is False:
        reasons.append("unsafe_tool_supervision")
    return reasons


def _rubric_scores(record: dict[str, Any], checks: dict[str, Any], *, hard_fail: bool) -> tuple[dict[str, int], dict[str, Any]]:
    if hard_fail:
        base = {
            "intent_understanding": 2,
            "recommendation_relevance": 2,
            "candidate_pool_consistency": 1 if checks.get("selected_subset_of_display") is False else 3,
            "rag_grounding": 2,
            "dialogue_quality": 2,
            "explanation_quality": 2,
            "format_protocol": 1 if checks.get("schema_valid") is False else 3,
            "training_value": 1,
        }
        return base, _evidence(record)

    evidence = _evidence(record)
    turn_count = int(evidence.get("dialogue_turn_count") or 1)
    display_turn_count = int(evidence.get("display_turn_count") or 0)
    action_types = set(evidence.get("action_types", []))
    avg_assistant_length = float(evidence.get("avg_assistant_length") or 0.0)
    unsupported_claim_count = int(evidence.get("unsupported_claim_count") or 0)
    scores = {
        "intent_understanding": 5,
        "recommendation_relevance": 5 if display_turn_count else 3,
        "candidate_pool_consistency": 5,
        "rag_grounding": max(3, 5 - unsupported_claim_count),
        "dialogue_quality": 5 if turn_count >= 3 or (turn_count >= 2 and len(action_types) >= 2) else 4,
        "explanation_quality": 5 if 20 <= avg_assistant_length <= 600 else 4,
        "format_protocol": 5,
        "training_value": 5 if display_turn_count and turn_count >= 2 else 4,
    }
    if checks.get("tool_supervision_safe") is False:
        scores["format_protocol"] = min(scores["format_protocol"], 3)
    if checks.get("no_forbidden_internal_fields") is False or checks.get("no_label_or_oracle_leakage") is False:
        scores["format_protocol"] = min(scores["format_protocol"], 2)
    return scores, evidence


def _evidence(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("schema_version") == MULTI_TURN_SFT_SCHEMA_VERSION:
        dialogue = [turn for turn in record.get("dialogue", []) if isinstance(turn, dict)]
        assistant_messages = [str(turn.get("assistant_message") or "") for turn in dialogue]
        display_ids = sorted({str(item_id) for turn in dialogue for item_id in turn.get("display_item_ids", []) if str(item_id)})
        selected_ids = sorted({str(item_id) for turn in dialogue for item_id in turn.get("selected_item_ids", []) if str(item_id)})
        return {
            "dialogue_turn_count": len(dialogue),
            "display_turn_count": sum(1 for turn in dialogue if turn.get("display_item_ids")),
            "action_types": sorted({str(turn.get("action_type") or "") for turn in dialogue if str(turn.get("action_type") or "")}),
            "display_item_ids": display_ids,
            "selected_item_ids": selected_ids,
            "violating_turn_indices": _violating_turn_indices(dialogue),
            "avg_assistant_length": round(sum(len(text) for text in assistant_messages) / len(assistant_messages), 4) if assistant_messages else 0.0,
            "unsupported_claim_count": sum(1 for text in assistant_messages if UNSUPPORTED_CLAIM_TERMS.search(text)),
        }
    sample = record.get("sample") if isinstance(record.get("sample"), dict) else {}
    target = sample.get("target_action") if isinstance(sample.get("target_action"), dict) else {}
    candidates = [str(candidate.get("item_id")) for candidate in sample.get("candidate_summary", []) if isinstance(candidate, dict) and candidate.get("item_id")]
    assistant = str(sample.get("assistant_response") or "")
    return {
        "dialogue_turn_count": 1,
        "display_turn_count": 1 if candidates else 0,
        "action_types": [str(target.get("trigger_reason") or "")],
        "display_item_ids": candidates,
        "selected_item_ids": [str(item_id) for item_id in target.get("selected_item_ids", []) if str(item_id)],
        "violating_turn_indices": [],
        "avg_assistant_length": len(assistant),
        "unsupported_claim_count": 1 if UNSUPPORTED_CLAIM_TERMS.search(assistant) else 0,
    }


def _validate_multi_turn(record: dict[str, Any]) -> None:
    from rs_core.offline.training.multi_turn_sft_generator import validate_multi_turn_sft_sample

    validate_multi_turn_sft_sample(record)


def _decision(total_score: int, *, hard_fail: bool, policy: SftJudgePolicy) -> str:
    if hard_fail:
        return "reject"
    if total_score >= policy.min_accept_score:
        return "accept"
    if total_score >= policy.min_accept_light_score:
        return "accept_light"
    if total_score >= policy.min_rewrite_score:
        return "rewrite"
    return "reject"


def _weighted_total(scores: dict[str, int]) -> int:
    total = 0.0
    for name, weight in RUBRIC_WEIGHTS.items():
        total += max(0, min(5, int(scores.get(name, 0)))) / 5 * weight
    return int(round(total))


def _rewrite_suggestion(decision: str, hard_fail_reasons: list[str], scores: dict[str, int]) -> str | None:
    if decision in {"accept", "accept_light"}:
        return None
    if hard_fail_reasons:
        return "修复硬门禁问题后再进入训练集：" + ", ".join(sorted(set(hard_fail_reasons)))
    weak_dims = [name for name, score in scores.items() if score <= 3]
    return "优先重写低分维度：" + ", ".join(weak_dims or ["training_value"])


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in FORBIDDEN_PUBLIC_KEYS:
                return True
            if _contains_forbidden_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_key(child) for child in value)
    return False


def _contains_leakage_text(value: Any) -> bool:
    return bool(LEAKAGE_TERMS.search(_all_text(value)))


def _contains_unsupported_claim(record: dict[str, Any]) -> bool:
    return any(UNSUPPORTED_CLAIM_TERMS.search(text) for text in _assistant_texts(record))


def _mentions_outside_candidate_pool(record: dict[str, Any]) -> bool:
    allowed_by_text = _candidate_ids_by_assistant_text(record)
    return any(_outside_ids(text, allowed_ids) for text, allowed_ids in allowed_by_text)


def _candidate_ids_by_assistant_text(record: dict[str, Any]) -> list[tuple[str, set[str]]]:
    if record.get("schema_version") == MULTI_TURN_SFT_SCHEMA_VERSION:
        pairs: list[tuple[str, set[str]]] = []
        last_display_ids: set[str] = set()
        for turn in record.get("dialogue", []):
            if not isinstance(turn, dict):
                continue
            display_ids = {str(item_id) for item_id in turn.get("display_item_ids", []) if str(item_id)}
            if display_ids:
                last_display_ids = set(display_ids)
            allowed_ids = display_ids or last_display_ids
            pairs.append((str(turn.get("assistant_message") or ""), allowed_ids))
        return pairs
    sample = record.get("sample") if isinstance(record.get("sample"), dict) else {}
    allowed_ids = {str(candidate.get("item_id")) for candidate in sample.get("candidate_summary", []) if isinstance(candidate, dict) and candidate.get("item_id")}
    return [(str(sample.get("assistant_response") or ""), allowed_ids)]


def _assistant_texts(record: dict[str, Any]) -> list[str]:
    return [text for text, _allowed_ids in _candidate_ids_by_assistant_text(record)]


def _outside_ids(text: str, allowed_ids: set[str]) -> set[str]:
    referenced = {match.group(1) for match in ITEM_REF_TERMS.finditer(text)}
    referenced.update(match.group(0) for match in ASIN_LIKE_TERMS.finditer(text))
    return {item_id for item_id in referenced if item_id not in allowed_ids}


def _tool_supervision_safe(value: Any) -> bool:
    return not UNSAFE_TOOL_TERMS.search(_all_text(value))


def _all_text(value: Any) -> str:
    chunks: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            chunks.append(str(key))
            chunks.append(_all_text(child))
    elif isinstance(value, list):
        for child in value:
            chunks.append(_all_text(child))
    elif isinstance(value, str):
        chunks.append(value)
    return "\n".join(chunks)


def _violating_turn_indices(dialogue: list[dict[str, Any]]) -> list[int]:
    violations: list[int] = []
    for turn in dialogue:
        display_ids = {str(item_id) for item_id in turn.get("display_item_ids", []) if str(item_id)}
        selected_ids = {str(item_id) for item_id in turn.get("selected_item_ids", []) if str(item_id)}
        target = turn.get("target_action") if isinstance(turn.get("target_action"), dict) else {}
        allowed_ids = {str(item_id) for item_id in target.get("allowed_item_ids", []) if str(item_id)}
        supervision = turn.get("tool_supervision") if isinstance(turn.get("tool_supervision"), dict) else {}
        should_recommend = bool(supervision.get("should_recommend", bool(display_ids)))
        has_violation = selected_ids - display_ids or (allowed_ids and selected_ids - allowed_ids)
        has_violation = has_violation or ((not display_ids or not should_recommend) and _looks_like_recommendation_list(str(turn.get("assistant_message") or "")))
        if has_violation:
            violations.append(int(turn.get("turn_index") or 0))
    return violations


def _looks_like_recommendation_list(text: str) -> bool:
    lowered = text.lower()
    if len(re.findall(r"(?:^|\n)\s*(?:[-*]|\d+[.)]|[一二三四五六七八九十]+[、.])\s+", text)) >= 2:
        return True
    return bool(re.search(r"\b(?:recommend|try|consider)\b.*\b(?:item|product)\b|推荐.*(?:商品|产品|这几件|以下)", lowered, re.DOTALL))
