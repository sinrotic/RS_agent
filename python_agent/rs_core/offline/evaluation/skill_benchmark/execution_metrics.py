"""执行指标契约：完整分母、显式缺失和按模型调用去重；不推断满意度。"""

from collections import Counter

VERSION = "rs-agent-execution-metrics/1"
TERMINAL_REASONS = frozenset({
    "FINAL_ANSWER", "INTERRUPTED", "HOOK_STOPPED", "MAX_LOOP", "MODEL_ERROR", "TOOL_ERROR",
})
TOKEN_FIELDS = (
    "prompt_tokens", "completion_tokens", "total_tokens",
    "cache_read_input_tokens", "cache_write_input_tokens",
)


def summarize_model_usage(calls):
    """calls 必须含每次真实模型尝试，失败/重试也在内；缺失 usage 用空映射。"""
    unique = {}
    for call in calls:
        call_id = call.get("model_call_id")
        if not isinstance(call_id, str) or not call_id:
            raise ValueError("模型调用缺少 model_call_id")
        if call_id in unique and unique[call_id] != call:
            raise ValueError("同一模型调用的记录冲突；累计流式 usage 需先归一为最终快照")
        unique[call_id] = call
    count = len(unique)
    fields = {}
    for name in TOKEN_FIELDS:
        values = [call.get("usage", {}).get(name) for call in unique.values()]
        if any(value is not None and (type(value) is not int or value < 0) for value in values):
            raise ValueError(f"{name} 必须为非负整数或缺失")
        observed = [value for value in values if value is not None]
        fields[name] = {
            "total": sum(observed) if count and len(observed) == count else None,
            "known_subtotal": sum(observed) if observed else None,
            "observed_calls": len(observed),
            "planned_calls": count,
            "coverage": len(observed) / count if count else None,
        }
    return {"model_calls": count, "fields": fields, "cost": None}


def summarize_execution(turns, *, planned_turns):
    """调用方传入每个已执行 Turn 的终态和独立业务校验，不用 HTTP 200 代替完成。"""
    if type(planned_turns) is not int or planned_turns < 0:
        raise ValueError("planned_turns 必须为非负整数")
    identities, statuses = set(), Counter()
    completed = terminal = 0
    latency, first_token = [], []
    for turn in turns:
        identity = (turn.get("session_id"), turn.get("turn_id"))
        if any(not isinstance(value, str) or not value for value in identity) or identity in identities:
            raise ValueError("Turn 标识缺失或重复")
        identities.add(identity)
        reason = turn.get("finish_reason")
        statuses[reason or "unknown"] += 1
        terminal += reason in TERMINAL_REASONS
        # NEXT_TURN 是内部循环转移；未知终态、unknown 校验、仅得到输出均不能算完成。
        completed += (reason == "FINAL_ANSWER" and turn.get("business_complete") is True
                      and turn.get("hard_gate") in {"passed", "not_applicable"})
        for field, target in (("elapsed_ms", latency), ("first_token_ms", first_token)):
            value = turn.get(field)
            if value is not None:
                if type(value) not in {int, float} or not 0 <= value < float("inf"):
                    raise ValueError(f"{field} 必须为非负有限数或缺失")
                target.append(value)
    if len(identities) > planned_turns:
        raise ValueError("已记录 Turn 数超过计划分母")
    return {
        "schema_version": VERSION, "planned_turns": planned_turns,
        "recorded_turns": len(identities), "missing_turns": planned_turns - len(identities),
        "terminal_turns": terminal, "completed_turns": completed,
        "completion_rate": completed / planned_turns if planned_turns else None,
        "finish_reasons": dict(statuses),
        "elapsed_ms": {"mean": sum(latency) / len(latency) if latency else None,
                       "observed_turns": len(latency)},
        "first_token_ms": {"mean": sum(first_token) / len(first_token) if first_token else None,
                           "observed_turns": len(first_token)},
        "satisfaction": None,
    }
