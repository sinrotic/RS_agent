from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from rs_core.common.recsys_types import MergedCandidate
from rs_core.agent.contracts.schema import FeedbackConstraints

_SOURCE_ALIASES = {
    "semantic": "semantic",
    "itemcf": "itemcf_weak",
    "itemcf_weak": "itemcf_weak",
    "itemcf_strong": "itemcf_strong",
    "popular": "popular",
    "category": "category",
}
_NEGATIVE_KEYWORDS = {"dislike", "avoid", "exclude", "don't like", "do not like", "不喜欢", "不要", "排除"}
_POSITIVE_KEYWORDS = {"prefer", "like", "喜欢", "偏好", "偏重", "优先", "更偏", "更想要", "给我看", "先看", "看看", "找", "展示", "来点", "换成"}
_STOP_WORDS = {"i", "and", "or", "the", "a", "an", "for", "items", "item", "source", "sources", "category", "categories"}
_KEYWORD_ALIASES = {
    "bluetooth": ["bluetooth"],
    "wireless": ["wireless", "cordless"],
    "commute": ["commute", "commuter", "travel", "portable"],
    "gift": ["gift", "present", "gifting"],
    "battery": ["battery"],
    "long_battery": ["long battery", "battery life", "long-lasting", "longlasting"],
    "cheap": ["cheap", "budget", "affordable", "low cost", "inexpensive"],
    "wired": ["wired", "cable", "corded"],
    "desktop_organization": ["桌面整洁", "桌面收纳", "收纳", "整理"],
    "cable_management": ["线缆管理", "理线", "走线", "线缆收纳"],
    "compact": ["小体积", "小巧", "不占地方", "紧凑"],
    "accessories": ["配件", "附件"],
    "practical": ["实用", "好用"],
}
_USE_CASE_KEYWORDS = {"commute", "gift", "desktop_organization", "cable_management", "compact", "practical"}
_PRICE_FIELDS = ["price", "price_value", "price_float", "price_display"]
_DEFAULT_KEYWORD_TEXT_FIELDS = [
    "title_clean",
    "main_category",
    "category",
    "description_text",
    "features_text",
    "item_text",
    "categories_flat",
]


def parse_feedback(text: str) -> FeedbackConstraints:
    constraints = FeedbackConstraints()
    _apply_explicit_item_feedback(text, constraints)
    _apply_price_constraints(text, constraints)
    for intent, clause in _intent_clauses(text):
        matched_keywords = _keyword_matches(clause)
        matched_keyword_tokens = _keyword_alias_token_set(matched_keywords)
        tokens = [
            token
            for token in re.findall(r"[A-Za-z0-9_]+", clause)
            if token.lower() not in _STOP_WORDS and token.lower() not in matched_keyword_tokens and token.lower() != "item_id"
        ]
        if intent == "negative":
            _apply_negative_keywords(matched_keywords, constraints)
            _apply_negative_tokens(tokens, constraints)
        elif intent == "positive":
            _apply_positive_keywords(matched_keywords, constraints)
            _apply_positive_use_cases(matched_keywords, constraints)
            _apply_positive_tokens(tokens, constraints)
    lowered = text.lower()
    if any(token in lowered for token in ["more diverse", "diverse", "fresh", "again", "different", "换一批", "不一样"]):
        constraints.filter_prior_turn_items = True
    if text.strip() and not _has_supported_constraint(constraints):
        constraints.unsupported_free_text.append(_normalize_feedback_input(text))
    return constraints


def normalize_feedback_input(text: str, max_chars: int = 2000) -> str:
    return _normalize_feedback_input(text, max_chars)


def merge_feedback(base: FeedbackConstraints, update: FeedbackConstraints) -> FeedbackConstraints:
    return FeedbackConstraints(
        liked_item_ids=set(base.liked_item_ids) | set(update.liked_item_ids),
        disliked_item_ids=set(base.disliked_item_ids) | set(update.disliked_item_ids),
        disliked_categories=set(base.disliked_categories) | set(update.disliked_categories),
        preferred_categories={**base.preferred_categories, **update.preferred_categories},
        preferred_sources={**base.preferred_sources, **update.preferred_sources},
        preferred_keywords={**base.preferred_keywords, **update.preferred_keywords},
        disliked_keywords={**base.disliked_keywords, **update.disliked_keywords},
        max_price=update.max_price if update.max_price is not None else base.max_price,
        use_cases={**base.use_cases, **update.use_cases},
        filter_prior_turn_items=base.filter_prior_turn_items or update.filter_prior_turn_items,
        item_feedback_events=[*base.item_feedback_events, *update.item_feedback_events],
        unsupported_free_text=[*base.unsupported_free_text, *update.unsupported_free_text],
    )


def apply_feedback_to_candidates(
    candidates: list[MergedCandidate],
    constraints: FeedbackConstraints | None,
    config: dict[str, Any],
    prior_turn_items: set[str] | None = None,
) -> tuple[list[MergedCandidate], dict[str, Any]]:
    return constraint_filter_tool(candidates, constraints, config, prior_turn_items)


def constraint_filter_tool(
    candidates: list[MergedCandidate],
    constraints: FeedbackConstraints | None,
    config: dict[str, Any],
    prior_turn_items: set[str] | None = None,
) -> tuple[list[MergedCandidate], dict[str, Any]]:
    constraints = constraints or FeedbackConstraints()
    prior_turn_items = prior_turn_items or set()
    excluded_items = set(constraints.disliked_item_ids)
    if constraints.filter_prior_turn_items:
        excluded_items |= prior_turn_items
    excluded_categories = {category.lower() for category in constraints.disliked_categories}
    min_candidates = int(config.get("constraint_filter_min_candidates", 1))
    if min_candidates < 1:
        min_candidates = 1
    kept: list[MergedCandidate] = []
    rejected: list[tuple[MergedCandidate, list[dict[str, Any]]]] = []
    excluded_item_ids: list[str] = []
    excluded_prior_turn_items: list[str] = []
    excluded_category_items: list[str] = []
    excluded_price_items: list[str] = []
    constraint_filter_events: list[dict[str, Any]] = []
    for candidate in candidates:
        events = _candidate_constraint_events(candidate, constraints, excluded_items, excluded_categories, prior_turn_items)
        if events:
            rejected.append((candidate, events))
            continue
        kept.append(_boost_candidate(candidate, constraints, config))
    restored, active_rejections = _restore_overfiltered_candidates(kept, rejected, min_candidates, constraints, config)
    kept.extend(restored)
    for candidate, events in active_rejections:
        for event in events:
            constraint_filter_events.append(event)
            reason = event["reason"]
            if reason == "disliked_item":
                excluded_item_ids.append(candidate.item_id)
            elif reason == "prior_turn_item":
                excluded_prior_turn_items.append(candidate.item_id)
            elif reason == "disliked_category":
                excluded_category_items.append(candidate.item_id)
            elif reason == "max_price":
                excluded_price_items.append(candidate.item_id)
    over_filter_events = _over_filter_events(restored)
    constraint_filter_events.extend(over_filter_events)
    sorted_events = sorted(constraint_filter_events, key=lambda event: (event.get("item_id", ""), event["reason"]))
    diagnostics = {
        "excluded_items": sorted(set(excluded_item_ids)),
        "excluded_prior_turn_items": sorted(set(excluded_prior_turn_items)),
        "excluded_categories": sorted(constraints.disliked_categories),
        "excluded_category_items": sorted(set(excluded_category_items)),
        "excluded_price_items": sorted(set(excluded_price_items)),
        "preferred_categories": dict(sorted(constraints.preferred_categories.items())),
        "preferred_sources": dict(sorted(constraints.preferred_sources.items())),
        "preferred_keywords": dict(sorted(constraints.preferred_keywords.items())),
        "disliked_keywords": dict(sorted(constraints.disliked_keywords.items())),
        "max_price": constraints.max_price,
        "use_cases": dict(sorted(constraints.use_cases.items())),
        "filter_prior_turn_items": constraints.filter_prior_turn_items,
        "prior_turn_items": sorted(prior_turn_items),
        "unsupported_free_text": list(constraints.unsupported_free_text),
        "boosts_applied": _boost_diagnostics(kept),
        "boost_events": _boost_event_diagnostics(kept),
        "filter_events": sorted_events,
        "constraint_filter_events": sorted_events,
        "constraint_filter_summary": {
            "input_candidate_count": len(candidates),
            "output_candidate_count": len(kept),
            "filtered_candidate_count": len(active_rejections),
            "restored_candidate_count": len(restored),
            "min_candidate_count": min_candidates,
            "over_filter_protection_applied": bool(restored),
        },
    }
    return kept, diagnostics


def _candidate_constraint_events(
    candidate: MergedCandidate,
    constraints: FeedbackConstraints,
    excluded_items: set[str],
    excluded_categories: set[str],
    prior_turn_items: set[str],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if candidate.item_id in excluded_items:
        if candidate.item_id in constraints.disliked_item_ids:
            events.append(_constraint_event(candidate.item_id, "filter", "disliked_item", candidate.item_id, candidate.item_id))
        if candidate.item_id in prior_turn_items:
            events.append(_constraint_event(candidate.item_id, "filter", "prior_turn_item", candidate.item_id, candidate.item_id))
    if candidate.category and candidate.category.lower() in excluded_categories:
        configured_category = _configured_value_for_key(constraints.disliked_categories, candidate.category)
        events.append(_constraint_event(candidate.item_id, "filter", "disliked_category", candidate.category, configured_category))
    price = _candidate_price(candidate)
    if constraints.max_price is not None and price is not None and price > constraints.max_price:
        events.append(_constraint_event(candidate.item_id, "filter", "max_price", price, constraints.max_price))
    return events


def _restore_overfiltered_candidates(
    kept: list[MergedCandidate],
    rejected: list[tuple[MergedCandidate, list[dict[str, Any]]]],
    min_candidates: int,
    constraints: FeedbackConstraints,
    config: dict[str, Any],
) -> tuple[list[MergedCandidate], list[tuple[MergedCandidate, list[dict[str, Any]]]]]:
    if len(kept) >= min_candidates or not rejected:
        return [], rejected
    restore_count = min(min_candidates - len(kept), len(rejected))
    restored_rows = rejected[-restore_count:]
    active_rejections = rejected[:-restore_count]
    restored = []
    for candidate, _ in restored_rows:
        restored_candidate = _boost_candidate(candidate, constraints, config)
        metadata = dict(restored_candidate.metadata)
        metadata["constraint_filter_restored"] = True
        restored.append(replace(restored_candidate, metadata=metadata))
    return restored, active_rejections


def _over_filter_events(restored: list[MergedCandidate]) -> list[dict[str, Any]]:
    return [
        _constraint_event(candidate.item_id, "protect", "over_filter_restored", candidate.item_id, "min_candidate_protection")
        for candidate in restored
    ]


def _constraint_event(
    item_id: str,
    action: str,
    reason: str,
    matched_value: Any,
    configured_value: Any,
) -> dict[str, Any]:
    return {
        "type": "constraint_filter",
        "action": action,
        "target_item_id": item_id,
        "reason": reason,
        "item_id": item_id,
        "matched_value": matched_value,
        "configured_value": configured_value,
    }


def _candidate_price(candidate: MergedCandidate) -> float | None:
    for field in _PRICE_FIELDS:
        value = candidate.metadata.get(field)
        if value is not None:
            return _price_number(value)
    return None


def _price_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def _intent_clauses(text: str) -> list[tuple[str, str]]:
    pattern = re.compile(
        r"\b(don't like|do not like|dislike|avoid|exclude|prefer|like)\b|不喜欢|不要|排除|喜欢|偏好|偏重|优先|更偏|更想要|给我看|先看|看看|找|展示|来点|换成",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(text))
    clauses: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        keyword = match.group(0).lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        clause = text[start:end].strip(" ,.;:，。；：")
        intent = "negative" if keyword in _NEGATIVE_KEYWORDS else "positive"
        if clause:
            clauses.append((intent, clause))
    return clauses


def _apply_price_constraints(text: str, constraints: FeedbackConstraints) -> None:
    lowered = text.lower()
    if not any(token in lowered for token in ["under", "below", "less than", "budget", "以内", "低于", "不超过"]):
        return
    match = re.search(r"(?:under|below|less than|budget|以内|低于|不超过)\s*[$¥￥]?\s*(\d+(?:\.\d+)?)", lowered)
    if not match:
        match = re.search(r"[$¥￥]\s*(\d+(?:\.\d+)?)\s*(?:以内|以下|budget|max)?", lowered)
    if match:
        constraints.max_price = float(match.group(1))


def _apply_explicit_item_feedback(text: str, constraints: FeedbackConstraints) -> None:
    item_ids = _explicit_item_ids(text)
    if not item_ids:
        return
    lowered = text.lower()
    if any(token in lowered for token in ["don't like", "do not like", "dislike", "show me something different", "different direction", "closer match", "不要", "不喜欢"]):
        action = "dislike"
        target = constraints.disliked_item_ids
    elif any(token in lowered for token in ["like this item", "i like", "喜欢"]):
        action = "like"
        target = constraints.liked_item_ids
    else:
        return
    for item_id in item_ids:
        target.add(item_id)
        constraints.item_feedback_events.append({"action": action, "item_id": item_id, "source": "explicit_item_id"})


def _apply_negative_keywords(matches: list[tuple[str, str]], constraints: FeedbackConstraints) -> None:
    for keyword, _ in matches:
        constraints.disliked_keywords[keyword] = 1.0


def _apply_positive_keywords(matches: list[tuple[str, str]], constraints: FeedbackConstraints) -> None:
    for keyword, _ in matches:
        constraints.preferred_keywords[keyword] = 1.0


def _apply_positive_use_cases(matches: list[tuple[str, str]], constraints: FeedbackConstraints) -> None:
    for keyword, _ in matches:
        if keyword in _USE_CASE_KEYWORDS:
            constraints.use_cases[keyword] = 1.0


def _apply_negative_tokens(tokens: list[str], constraints: FeedbackConstraints) -> None:
    for token in tokens:
        if _canonical_keyword(token):
            continue
        if _looks_like_item_id(token):
            constraints.disliked_item_ids.add(token)
        else:
            constraints.disliked_categories.add(token)


def _apply_positive_tokens(tokens: list[str], constraints: FeedbackConstraints) -> None:
    explicit_item_ids = constraints.liked_item_ids | constraints.disliked_item_ids
    for token in tokens:
        source = _SOURCE_ALIASES.get(token.lower())
        if source:
            constraints.preferred_sources[source] = 1.0
        elif _canonical_keyword(token):
            canonical = _canonical_keyword(token)
            if canonical in _USE_CASE_KEYWORDS:
                constraints.use_cases[canonical] = 1.0
            continue
        elif _looks_like_item_id(token):
            if token not in explicit_item_ids:
                constraints.liked_item_ids.add(token)
                constraints.item_feedback_events.append({"action": "like", "item_id": token, "source": "positive_clause"})
        else:
            constraints.preferred_categories[token] = 1.0


def _explicit_item_ids(text: str) -> list[str]:
    return re.findall(r"item_id=([A-Za-z0-9_\-]+)", text)


def _looks_like_item_id(token: str) -> bool:
    return "_" in token or any(char.isdigit() for char in token)


def _has_supported_constraint(constraints: FeedbackConstraints) -> bool:
    return bool(
        constraints.liked_item_ids
        or constraints.disliked_item_ids
        or constraints.disliked_categories
        or constraints.preferred_categories
        or constraints.preferred_sources
        or constraints.preferred_keywords
        or constraints.disliked_keywords
        or constraints.max_price is not None
        or constraints.use_cases
        or constraints.filter_prior_turn_items
    )


def _normalize_feedback_input(text: str, max_chars: int = 2000) -> str:
    normalized = text.replace("\x1b", "")
    normalized = "".join(ch for ch in normalized if ch in {"\n", "\t"} or ord(ch) >= 32)
    if len(normalized) > max_chars:
        raise ValueError(f"Feedback exceeds {max_chars} characters")
    return normalized


def _boost_candidate(candidate: MergedCandidate, constraints: FeedbackConstraints, config: dict[str, Any]) -> MergedCandidate:
    source_scores = dict(candidate.source_scores)
    metadata = dict(candidate.metadata)
    category_boost = float(config.get("feedback_category_boost", 0.0))
    source_boost = float(config.get("feedback_source_boost", 0.0))
    keyword_boost = float(config.get("feedback_keyword_boost", 0.0))
    keyword_penalty = float(config.get("feedback_keyword_penalty", 0.0))
    keyword_text_fields = list(config.get("feedback_keyword_text_fields", _DEFAULT_KEYWORD_TEXT_FIELDS))
    preferred_categories = _normalized_weight_map(constraints.preferred_categories)
    preferred_sources = _normalized_weight_map(constraints.preferred_sources)
    applied: list[str] = []
    boost_events: list[dict[str, Any]] = []
    category_key = candidate.category.lower() if candidate.category else ""
    if category_key in preferred_categories and category_boost:
        configured_category, _ = preferred_categories[category_key]
        score_key = "feedback_category"
        source_scores[score_key] = max(float(source_scores.get(score_key, 0.0)), category_boost)
        applied.append(f"category:{candidate.category}")
        boost_events.append({
            "type": "preferred_category",
            "matched_value": candidate.category,
            "configured_value": configured_category,
            "score_key": score_key,
            "boost": category_boost,
        })
    for source in list(candidate.sources):
        source_key = source.lower()
        if source_key in preferred_sources and source_boost:
            configured_source, _ = preferred_sources[source_key]
            score_key = f"feedback_source_{source}"
            source_scores[score_key] = max(float(source_scores.get(score_key, 0.0)), source_boost)
            applied.append(f"source:{source}")
            boost_events.append({
                "type": "preferred_source",
                "matched_value": source,
                "configured_value": configured_source,
                "score_key": score_key,
                "boost": source_boost,
            })
    preferred_keyword_matches = _candidate_keyword_matches(candidate, constraints.preferred_keywords, keyword_text_fields)
    if preferred_keyword_matches and keyword_boost:
        score_key = "feedback_keyword"
        source_scores[score_key] = max(float(source_scores.get(score_key, 0.0)), keyword_boost)
        applied.extend(f"keyword:{match['configured_value']}" for match in preferred_keyword_matches)
        for match in preferred_keyword_matches:
            boost_events.append({
                "type": "preferred_keyword",
                "matched_value": match["matched_value"],
                "configured_value": match["configured_value"],
                "matched_alias": match["matched_alias"],
                "score_key": score_key,
                "boost": keyword_boost,
                "metadata_fields": match["metadata_fields"],
            })
    disliked_keyword_matches = _candidate_keyword_matches(candidate, constraints.disliked_keywords, keyword_text_fields)
    if disliked_keyword_matches and keyword_penalty:
        score_key = "feedback_keyword_penalty"
        penalty = -keyword_penalty
        source_scores[score_key] = min(float(source_scores.get(score_key, 0.0)), penalty)
        applied.extend(f"keyword_penalty:{match['configured_value']}" for match in disliked_keyword_matches)
        for match in disliked_keyword_matches:
            boost_events.append({
                "type": "disliked_keyword",
                "matched_value": match["matched_value"],
                "configured_value": match["configured_value"],
                "matched_alias": match["matched_alias"],
                "score_key": score_key,
                "boost": penalty,
                "metadata_fields": match["metadata_fields"],
            })
    if not applied:
        return candidate
    sources = list(candidate.sources)
    for source in source_scores:
        if source.startswith("feedback_") and source not in sources:
            sources.append(source)
    metadata["feedback_boosts"] = applied
    metadata["feedback_boost_events"] = boost_events
    return replace(candidate, sources=sources, source_scores=source_scores, metadata=metadata)


def _boost_diagnostics(candidates: list[MergedCandidate]) -> dict[str, list[str]]:
    return {
        candidate.item_id: list(candidate.metadata.get("feedback_boosts", []))
        for candidate in candidates
        if candidate.metadata.get("feedback_boosts")
    }


def _boost_event_diagnostics(candidates: list[MergedCandidate]) -> dict[str, list[dict[str, Any]]]:
    return {
        candidate.item_id: list(candidate.metadata.get("feedback_boost_events", []))
        for candidate in candidates
        if candidate.metadata.get("feedback_boost_events")
    }


def _normalized_weight_map(values: dict[str, float]) -> dict[str, tuple[str, float]]:
    return {str(value).lower(): (str(value), weight) for value, weight in values.items()}


def _keyword_matches(text: str) -> list[tuple[str, str]]:
    normalized = _normalize_keyword_text(text)
    raw_text = text.lower()
    matches: list[tuple[str, str]] = []
    occupied_tokens: set[str] = set()
    alias_entries = [
        (keyword, alias, _normalize_keyword_text(alias))
        for keyword, aliases in _KEYWORD_ALIASES.items()
        for alias in aliases
    ]
    alias_entries.sort(key=lambda entry: len(entry[2].split()), reverse=True)
    for keyword, alias, normalized_alias in alias_entries:
        alias_tokens = set(normalized_alias.split())
        if alias_tokens & occupied_tokens:
            continue
        if _contains_keyword_alias(normalized, alias) or (re.search(r"[一-鿿]", alias) and alias in raw_text):
            matches.append((keyword, alias))
            occupied_tokens.update(alias_tokens)
    return matches


def _canonical_keyword(value: str) -> str | None:
    normalized = _normalize_keyword_text(value)
    for keyword, aliases in _KEYWORD_ALIASES.items():
        if (keyword == normalized and keyword != "accessories") or any(_normalize_keyword_text(alias) == normalized for alias in aliases):
            return keyword
    return None


def _keyword_alias_token_set(matches: list[tuple[str, str]]) -> set[str]:
    tokens: set[str] = set()
    for _, alias in matches:
        tokens.update(re.findall(r"[a-z0-9_]+", alias.lower()))
    return tokens


def _candidate_keyword_matches(candidate: MergedCandidate, keywords: dict[str, float], fields: list[str]) -> list[dict[str, Any]]:
    if not keywords:
        return []
    text_by_field = _candidate_keyword_text_by_field(candidate, fields)
    matches: list[dict[str, Any]] = []
    for configured_keyword in keywords:
        canonical = _canonical_keyword(configured_keyword) or configured_keyword
        aliases = _KEYWORD_ALIASES.get(canonical, [configured_keyword])
        matched_fields: list[str] = []
        matched_alias = ""
        for field, text in text_by_field.items():
            for alias in aliases:
                if _contains_keyword_alias(text, alias):
                    matched_fields.append(field)
                    matched_alias = alias
                    break
        if matched_fields:
            matches.append({
                "matched_value": canonical,
                "configured_value": configured_keyword,
                "matched_alias": matched_alias,
                "metadata_fields": sorted(set(matched_fields)),
            })
    return matches


def _candidate_keyword_text_by_field(candidate: MergedCandidate, fields: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in fields:
        raw = candidate.metadata.get(field)
        if raw is None and field == "category":
            raw = candidate.category
        text = _flatten_text(raw)
        if text:
            values[field] = _normalize_keyword_text(text)
    return values


def _flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    return str(value)


def _contains_keyword_alias(text: str, alias: str) -> bool:
    normalized_alias = _normalize_keyword_text(alias)
    if not normalized_alias:
        return False
    return re.search(rf"(?<!\w){re.escape(normalized_alias)}(?!\w)", text) is not None


def _normalize_keyword_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9一-鿿]+", " ", text.lower())).strip()


def _configured_value_for_key(values: set[str], matched_value: str) -> str:
    key = matched_value.lower()
    for value in values:
        if value.lower() == key:
            return value
    return matched_value
