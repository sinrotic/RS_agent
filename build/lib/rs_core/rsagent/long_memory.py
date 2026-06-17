from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from rs_core.rsagent.context import ensure_session_context_state
from rs_core.rsagent.policy import merge_feedback
from rs_core.rsagent.schema import AgentSession, FeedbackConstraints, UserPreferenceProfile

LONG_MEMORY_SCHEMA_VERSION = "rsagent_long_memory_v1"
LONG_MEMORY_STORE_SCHEMA_VERSION = "rsagent_long_memory_store_v1"
LONG_MEMORY_RECALL_STRATEGY = "deterministic_keyword_overlap_v1"


@dataclass
class LongMemoryConfig:
    enabled: bool = False
    store_type: str = "memory"
    json_path: str | None = None
    max_liked_item_ids: int = 100
    max_disliked_item_ids: int = 100
    max_preference_terms: int = 100
    persist_unsupported_free_text: bool = False
    enable_typed_entries: bool = True
    enable_relevance_recall: bool = True
    max_memory_entries: int = 200
    max_recalled_entries: int = 20
    recall_min_score: float = 0.0


@dataclass
class LongMemoryEntry:
    entry_id: str
    type: str
    value: dict[str, Any]
    source: str = "deterministic_extractor"
    confidence: float = 1.0
    evidence: dict[str, Any] = field(default_factory=dict)
    created_turn_index: int = 0
    updated_turn_index: int = 0
    updated_session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "type": self.type,
            "value": dict(self.value),
            "source": self.source,
            "confidence": float(self.confidence),
            "evidence": dict(self.evidence),
            "created_turn_index": int(self.created_turn_index),
            "updated_turn_index": int(self.updated_turn_index),
            "updated_session_id": self.updated_session_id,
        }


@dataclass
class UserLongMemory:
    user_id: str
    active_constraints: FeedbackConstraints = field(default_factory=FeedbackConstraints)
    user_profile: UserPreferenceProfile = field(default_factory=UserPreferenceProfile)
    entries: list[LongMemoryEntry] = field(default_factory=list)
    schema_version: str = LONG_MEMORY_SCHEMA_VERSION
    updated_session_id: str | None = None
    updated_turn_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "user_id": self.user_id,
            "active_constraints": self.active_constraints.to_dict(),
            "user_profile": self.user_profile.to_dict(),
            "entries": [entry.to_dict() for entry in self.entries],
            "updated_session_id": self.updated_session_id,
            "updated_turn_count": self.updated_turn_count,
        }


class LongMemoryStore(Protocol):
    def load_user_memory(self, user_id: str) -> UserLongMemory | None:
        ...

    def save_user_memory(self, memory: UserLongMemory) -> None:
        ...


class InMemoryLongMemoryStore:
    def __init__(self) -> None:
        self._by_user: dict[str, UserLongMemory] = {}

    def load_user_memory(self, user_id: str) -> UserLongMemory | None:
        memory = self._by_user.get(str(user_id))
        if memory is None:
            return None
        return user_long_memory_from_dict(memory.to_dict())

    def save_user_memory(self, memory: UserLongMemory) -> None:
        self._by_user[str(memory.user_id)] = user_long_memory_from_dict(memory.to_dict())


class JsonLongMemoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load_user_memory(self, user_id: str) -> UserLongMemory | None:
        payload = self._read_store()
        users = payload.get("users") if isinstance(payload.get("users"), dict) else {}
        raw_memory = users.get(str(user_id))
        if not isinstance(raw_memory, dict):
            return None
        return user_long_memory_from_dict(raw_memory)

    def save_user_memory(self, memory: UserLongMemory) -> None:
        payload = self._read_store()
        users = payload.get("users") if isinstance(payload.get("users"), dict) else {}
        users[str(memory.user_id)] = memory.to_dict()
        payload = {
            "schema_version": LONG_MEMORY_STORE_SCHEMA_VERSION,
            "users": users,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _read_store(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": LONG_MEMORY_STORE_SCHEMA_VERSION, "users": {}}
        text = self.path.read_text(encoding="utf-8").strip()
        if not text:
            return {"schema_version": LONG_MEMORY_STORE_SCHEMA_VERSION, "users": {}}
        payload = json.loads(text)
        if not isinstance(payload, dict):
            return {"schema_version": LONG_MEMORY_STORE_SCHEMA_VERSION, "users": {}}
        if not isinstance(payload.get("users"), dict):
            payload["users"] = {}
        payload.setdefault("schema_version", LONG_MEMORY_STORE_SCHEMA_VERSION)
        return payload


def build_long_memory_store(config: LongMemoryConfig) -> LongMemoryStore | None:
    if not config.enabled:
        return None
    store_type = config.store_type.strip().lower()
    if store_type == "memory":
        return InMemoryLongMemoryStore()
    if store_type == "json":
        if not config.json_path:
            raise ValueError("Long memory json store requires json_path")
        return JsonLongMemoryStore(config.json_path)
    raise ValueError(f"Unsupported long memory store_type: {config.store_type}")


def hydrate_session_from_long_memory(session: AgentSession, memory: UserLongMemory | None) -> bool:
    if memory is None or memory.user_id != session.user_id:
        return False
    session.active_constraints = merge_feedback(memory.active_constraints, session.active_constraints)
    ensure_session_context_state(session)
    return True


def snapshot_session_long_memory(session: AgentSession, config: LongMemoryConfig | None = None) -> UserLongMemory:
    active_config = config or LongMemoryConfig()
    ensure_session_context_state(session)
    constraints = _trim_constraints(session.active_constraints, active_config)
    profile = _trim_profile(session.user_profile, active_config)
    return UserLongMemory(
        user_id=session.user_id,
        active_constraints=constraints,
        user_profile=profile,
        entries=extract_long_memory_entries(session, active_config),
        updated_session_id=session.session_id,
        updated_turn_count=len(session.turns),
    )


def extract_long_memory_entries(session: AgentSession, config: LongMemoryConfig | None = None) -> list[LongMemoryEntry]:
    active_config = config or LongMemoryConfig()
    if not active_config.enable_typed_entries:
        return []
    constraints = _trim_constraints(session.active_constraints, active_config)
    entries: dict[str, LongMemoryEntry] = {}
    updated_turn_index = len(session.turns)
    base_evidence = {
        "source_field": "active_constraints",
        "turn_count": len(session.turns),
        "updated_session_id": session.session_id,
    }

    for item_id in _limit_sorted(constraints.liked_item_ids, active_config.max_liked_item_ids):
        _put_entry(entries, session, "liked_item", item_id, {"item_id": item_id}, 1.0, base_evidence, updated_turn_index)
    for item_id in _limit_sorted(constraints.disliked_item_ids, active_config.max_disliked_item_ids):
        _put_entry(entries, session, "disliked_item", item_id, {"item_id": item_id}, 1.0, base_evidence, updated_turn_index)
    for category in _limit_sorted(constraints.disliked_categories, active_config.max_preference_terms):
        _put_entry(entries, session, "disliked_category", category, {"category": category}, 1.0, base_evidence, updated_turn_index)
    for category, weight in _limit_mapping(constraints.preferred_categories, active_config.max_preference_terms).items():
        _put_entry(entries, session, "preferred_category", category, {"category": category, "weight": weight}, weight, base_evidence, updated_turn_index)
    for source, weight in _limit_mapping(constraints.preferred_sources, active_config.max_preference_terms).items():
        _put_entry(entries, session, "preferred_source", source, {"source": source, "weight": weight}, weight, base_evidence, updated_turn_index)
    for keyword, weight in _limit_mapping(constraints.preferred_keywords, active_config.max_preference_terms).items():
        _put_entry(entries, session, "preferred_keyword", keyword, {"keyword": keyword, "weight": weight}, weight, base_evidence, updated_turn_index)
    for keyword, weight in _limit_mapping(constraints.disliked_keywords, active_config.max_preference_terms).items():
        _put_entry(entries, session, "disliked_keyword", keyword, {"keyword": keyword, "weight": weight}, weight, base_evidence, updated_turn_index)
    for use_case, weight in _limit_mapping(constraints.use_cases, active_config.max_preference_terms).items():
        _put_entry(entries, session, "use_case", use_case, {"use_case": use_case, "weight": weight}, weight, base_evidence, updated_turn_index)
    if constraints.max_price is not None:
        _put_entry(entries, session, "max_price", "max_price", {"amount": constraints.max_price}, 1.0, base_evidence, updated_turn_index)
    if constraints.filter_prior_turn_items:
        _put_entry(
            entries,
            session,
            "freshness_preference",
            "filter_prior_turn_items",
            {"filter_prior_turn_items": True},
            1.0,
            base_evidence,
            updated_turn_index,
        )

    return sorted(entries.values(), key=lambda entry: entry.entry_id)[: max(0, active_config.max_memory_entries)]


def recall_relevant_long_memory(
    memory: UserLongMemory | None,
    query: str = "",
    session: AgentSession | None = None,
    config: LongMemoryConfig | None = None,
) -> dict[str, Any]:
    active_config = config or LongMemoryConfig()
    entries = list(memory.entries) if memory is not None else []
    if not active_config.enable_relevance_recall:
        entries = []
    query_tokens = _token_set(query)
    session_tokens = _session_token_set(session)
    prior_item_ids = session.prior_turn_items() if session is not None else set()
    scored: list[tuple[float, str, str, LongMemoryEntry]] = []
    for entry in entries:
        score = _score_memory_entry(entry, query_tokens, session_tokens, prior_item_ids)
        if score < active_config.recall_min_score:
            continue
        scored.append((-score, entry.type, _entry_sort_key(entry), entry))
    scored.sort()
    recalled = [entry for *_unused, entry in scored[: max(0, active_config.max_recalled_entries)]]
    return {
        "entries": [entry.to_dict() for entry in recalled],
        "entry_count": len(recalled),
        "available_entry_count": len(entries),
        "recall_strategy": LONG_MEMORY_RECALL_STRATEGY,
    }


def user_long_memory_from_dict(payload: dict[str, Any]) -> UserLongMemory:
    return UserLongMemory(
        user_id=str(payload.get("user_id") or ""),
        active_constraints=feedback_constraints_from_dict(_dict_or_empty(payload.get("active_constraints"))),
        user_profile=user_preference_profile_from_dict(_dict_or_empty(payload.get("user_profile"))),
        entries=long_memory_entries_from_list(payload.get("entries")),
        schema_version=str(payload.get("schema_version") or LONG_MEMORY_SCHEMA_VERSION),
        updated_session_id=_optional_str(payload.get("updated_session_id")),
        updated_turn_count=_int_value(payload.get("updated_turn_count")),
    )


def long_memory_entries_from_list(value: Any) -> list[LongMemoryEntry]:
    if not isinstance(value, list):
        return []
    entries: list[LongMemoryEntry] = []
    seen: set[str] = set()
    for item in value:
        entry = long_memory_entry_from_dict(item) if isinstance(item, dict) else None
        if entry is None or entry.entry_id in seen:
            continue
        seen.add(entry.entry_id)
        entries.append(entry)
    return entries


def long_memory_entry_from_dict(payload: dict[str, Any]) -> LongMemoryEntry | None:
    entry_id = _optional_str(payload.get("entry_id"))
    entry_type = _optional_str(payload.get("type"))
    value = payload.get("value")
    if not entry_id or not entry_type or not isinstance(value, dict):
        return None
    return LongMemoryEntry(
        entry_id=entry_id,
        type=entry_type,
        value=dict(value),
        source=str(payload.get("source") or "deterministic_extractor"),
        confidence=_float_value(payload.get("confidence"), default=1.0),
        evidence=_dict_or_empty(payload.get("evidence")),
        created_turn_index=_int_value(payload.get("created_turn_index")),
        updated_turn_index=_int_value(payload.get("updated_turn_index")),
        updated_session_id=_optional_str(payload.get("updated_session_id")),
    )


def feedback_constraints_from_dict(payload: dict[str, Any] | None) -> FeedbackConstraints:
    data = _dict_or_empty(payload)
    return FeedbackConstraints(
        liked_item_ids=set(_string_list(data.get("liked_item_ids"))),
        disliked_item_ids=set(_string_list(data.get("disliked_item_ids"))),
        disliked_categories=set(_string_list(data.get("disliked_categories"))),
        preferred_categories=_float_mapping(data.get("preferred_categories")),
        preferred_sources=_float_mapping(data.get("preferred_sources")),
        preferred_keywords=_float_mapping(data.get("preferred_keywords")),
        disliked_keywords=_float_mapping(data.get("disliked_keywords")),
        max_price=_optional_float(data.get("max_price")),
        use_cases=_float_mapping(data.get("use_cases")),
        filter_prior_turn_items=bool(data.get("filter_prior_turn_items", False)),
        item_feedback_events=_dict_list(data.get("item_feedback_events")),
        unsupported_free_text=_string_list(data.get("unsupported_free_text")),
    )


def user_preference_profile_from_dict(payload: dict[str, Any] | None) -> UserPreferenceProfile:
    data = _dict_or_empty(payload)
    return UserPreferenceProfile(
        liked_item_ids=_string_list(data.get("liked_item_ids")),
        disliked_item_ids=_string_list(data.get("disliked_item_ids")),
        disliked_categories=_string_list(data.get("disliked_categories")),
        preferred_categories=_float_mapping(data.get("preferred_categories")),
        preferred_sources=_float_mapping(data.get("preferred_sources")),
        preferred_keywords=_float_mapping(data.get("preferred_keywords")),
        disliked_keywords=_float_mapping(data.get("disliked_keywords")),
        max_price=_optional_float(data.get("max_price")),
        use_cases=_float_mapping(data.get("use_cases")),
        updated_turn_index=_int_value(data.get("updated_turn_index")),
    )


def _put_entry(
    entries: dict[str, LongMemoryEntry],
    session: AgentSession,
    entry_type: str,
    key: str,
    value: dict[str, Any],
    confidence: float,
    evidence: dict[str, Any],
    updated_turn_index: int,
) -> None:
    normalized_key = _normalize_key(key)
    if not normalized_key:
        return
    entry_id = f"{session.user_id}:{entry_type}:{normalized_key}"
    current = entries.get(entry_id)
    entry = LongMemoryEntry(
        entry_id=entry_id,
        type=entry_type,
        value={"key": key, **value},
        confidence=_bounded_confidence(confidence),
        evidence=dict(evidence),
        created_turn_index=current.created_turn_index if current else updated_turn_index,
        updated_turn_index=updated_turn_index,
        updated_session_id=session.session_id,
    )
    if current is None or entry.confidence >= current.confidence:
        entries[entry_id] = entry


def _score_memory_entry(
    entry: LongMemoryEntry,
    query_tokens: set[str],
    session_tokens: set[str],
    prior_item_ids: set[str],
) -> float:
    entry_tokens = _entry_token_set(entry)
    score = 0.0
    if query_tokens & entry_tokens:
        score += 3.0
    if session_tokens & entry_tokens:
        score += 2.0
    item_id = _optional_str(entry.value.get("item_id"))
    if item_id and item_id in prior_item_ids:
        score += 2.0
    if entry.type == "use_case" and (query_tokens | session_tokens) & entry_tokens:
        score += 2.0
    if entry.type.startswith("disliked"):
        score += 1.0
    if entry.type == "max_price":
        score += 0.5
    return score


def _entry_token_set(entry: LongMemoryEntry) -> set[str]:
    tokens: set[str] = set()
    tokens.update(_token_set(entry.type))
    tokens.update(_token_set(entry.entry_id))
    for value in entry.value.values():
        if isinstance(value, (str, int, float)):
            tokens.update(_token_set(str(value)))
    return tokens


def _session_token_set(session: AgentSession | None) -> set[str]:
    if session is None:
        return set()
    tokens: set[str] = set()
    for turn in session.turns[-3:]:
        tokens.update(_token_set(turn.user_input))
        tokens.update(_token_set(turn.assistant_response))
    for category in session.active_constraints.preferred_categories:
        tokens.update(_token_set(category))
    for keyword in session.active_constraints.preferred_keywords:
        tokens.update(_token_set(keyword))
    for use_case in session.active_constraints.use_cases:
        tokens.update(_token_set(use_case))
    return tokens


def _entry_sort_key(entry: LongMemoryEntry) -> str:
    key = entry.value.get("key")
    return _normalize_key(str(key if key not in (None, "") else entry.entry_id))


def _token_set(value: str) -> set[str]:
    return {token for token in re.split(r"[^0-9a-zA-Z_]+", value.lower()) if token}


def _normalize_key(value: str) -> str:
    return " ".join(str(value).strip().lower().split())


def _bounded_confidence(value: float) -> float:
    return max(0.0, min(1.0, abs(float(value))))


def _trim_constraints(constraints: FeedbackConstraints, config: LongMemoryConfig) -> FeedbackConstraints:
    return FeedbackConstraints(
        liked_item_ids=set(_limit_sorted(constraints.liked_item_ids, config.max_liked_item_ids)),
        disliked_item_ids=set(_limit_sorted(constraints.disliked_item_ids, config.max_disliked_item_ids)),
        disliked_categories=set(_limit_sorted(constraints.disliked_categories, config.max_preference_terms)),
        preferred_categories=_limit_mapping(constraints.preferred_categories, config.max_preference_terms),
        preferred_sources=_limit_mapping(constraints.preferred_sources, config.max_preference_terms),
        preferred_keywords=_limit_mapping(constraints.preferred_keywords, config.max_preference_terms),
        disliked_keywords=_limit_mapping(constraints.disliked_keywords, config.max_preference_terms),
        max_price=constraints.max_price,
        use_cases=_limit_mapping(constraints.use_cases, config.max_preference_terms),
        filter_prior_turn_items=constraints.filter_prior_turn_items,
        item_feedback_events=_limit_tail_list(constraints.item_feedback_events, config.max_liked_item_ids),
        unsupported_free_text=list(constraints.unsupported_free_text) if config.persist_unsupported_free_text else [],
    )


def _trim_profile(profile: UserPreferenceProfile, config: LongMemoryConfig) -> UserPreferenceProfile:
    return UserPreferenceProfile(
        liked_item_ids=_limit_list(profile.liked_item_ids, config.max_liked_item_ids),
        disliked_item_ids=_limit_list(profile.disliked_item_ids, config.max_disliked_item_ids),
        disliked_categories=_limit_list(profile.disliked_categories, config.max_preference_terms),
        preferred_categories=_limit_mapping(profile.preferred_categories, config.max_preference_terms),
        preferred_sources=_limit_mapping(profile.preferred_sources, config.max_preference_terms),
        preferred_keywords=_limit_mapping(profile.preferred_keywords, config.max_preference_terms),
        disliked_keywords=_limit_mapping(profile.disliked_keywords, config.max_preference_terms),
        max_price=profile.max_price,
        use_cases=_limit_mapping(profile.use_cases, config.max_preference_terms),
        updated_turn_index=profile.updated_turn_index,
    )


def _limit_sorted(values: set[str] | list[str], limit: int) -> list[str]:
    return sorted(str(value) for value in values if value)[:max(0, limit)]


def _limit_list(values: list[str], limit: int) -> list[str]:
    return [str(value) for value in values if value][:max(0, limit)]


def _limit_tail_list(values: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    return [dict(value) for value in values if isinstance(value, dict)][-limit:]


def _limit_mapping(values: dict[str, float], limit: int) -> dict[str, float]:
    return dict(sorted((str(key), float(value)) for key, value in values.items())[:max(0, limit)])


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item not in (None, "")]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _float_mapping(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, float] = {}
    for key, raw_value in value.items():
        try:
            result[str(key)] = float(raw_value)
        except (TypeError, ValueError):
            continue
    return result


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
