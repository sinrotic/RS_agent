from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from rs_core.recsys.types import MergedCandidate
from rs_core.rsagent.schema import FeedbackConstraints

_SOURCE_ALIASES = {
    "semantic": "semantic",
    "itemcf": "itemcf_weak",
    "itemcf_weak": "itemcf_weak",
    "itemcf_strong": "itemcf_strong",
    "popular": "popular",
    "category": "category",
}
_NEGATIVE_KEYWORDS = {"dislike", "avoid", "exclude", "不喜欢", "不要", "排除"}
_POSITIVE_KEYWORDS = {"prefer", "like", "喜欢", "偏好"}
_STOP_WORDS = {"i", "and", "or", "the", "a", "an", "for", "items", "item", "source", "sources", "category", "categories"}
_KEYWORD_ALIASES = {
    "bluetooth": ["bluetooth"],
    "wireless": ["wireless", "cordless"],
    "commute": ["commute", "commuter", "travel", "portable"],
    "battery": ["battery"],
    "long_battery": ["long battery", "battery life", "long-lasting", "longlasting"],
    "cheap": ["cheap", "budget", "affordable", "low cost", "inexpensive"],
    "wired": ["wired", "cable", "corded"],
}
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
    for intent, clause in _intent_clauses(text):
        matched_keywords = _keyword_matches(clause)
        matched_keyword_tokens = _keyword_alias_token_set(matched_keywords)
        tokens = [
            token
            for token in re.findall(r"[A-Za-z0-9_]+", clause)
            if token.lower() not in _STOP_WORDS and token.lower() not in matched_keyword_tokens
        ]
        if intent == "negative":
            _apply_negative_keywords(matched_keywords, constraints)
            _apply_negative_tokens(tokens, constraints)
        elif intent == "positive":
            _apply_positive_keywords(matched_keywords, constraints)
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
        disliked_item_ids=set(base.disliked_item_ids) | set(update.disliked_item_ids),
        disliked_categories=set(base.disliked_categories) | set(update.disliked_categories),
        preferred_categories={**base.preferred_categories, **update.preferred_categories},
        preferred_sources={**base.preferred_sources, **update.preferred_sources},
        preferred_keywords={**base.preferred_keywords, **update.preferred_keywords},
        disliked_keywords={**base.disliked_keywords, **update.disliked_keywords},
        filter_prior_turn_items=base.filter_prior_turn_items or update.filter_prior_turn_items,
        unsupported_free_text=[*base.unsupported_free_text, *update.unsupported_free_text],
    )


def apply_feedback_to_candidates(
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
    kept: list[MergedCandidate] = []
    excluded_item_ids: list[str] = []
    excluded_prior_turn_items: list[str] = []
    excluded_category_items: list[str] = []
    filter_events: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.item_id in excluded_items:
            excluded_item_ids.append(candidate.item_id)
            if candidate.item_id in constraints.disliked_item_ids:
                filter_events.append({"item_id": candidate.item_id, "type": "disliked_item", "matched_value": candidate.item_id, "configured_value": candidate.item_id})
            if candidate.item_id in prior_turn_items:
                excluded_prior_turn_items.append(candidate.item_id)
                filter_events.append({"item_id": candidate.item_id, "type": "prior_turn_item", "matched_value": candidate.item_id, "configured_value": candidate.item_id})
            continue
        if candidate.category and candidate.category.lower() in excluded_categories:
            configured_category = _configured_value_for_key(constraints.disliked_categories, candidate.category)
            excluded_category_items.append(candidate.item_id)
            filter_events.append({
                "item_id": candidate.item_id,
                "type": "disliked_category",
                "matched_value": candidate.category,
                "configured_value": configured_category,
            })
            continue
        kept.append(_boost_candidate(candidate, constraints, config))
    diagnostics = {
        "excluded_items": sorted(excluded_item_ids),
        "excluded_prior_turn_items": sorted(excluded_prior_turn_items),
        "excluded_categories": sorted(constraints.disliked_categories),
        "excluded_category_items": sorted(excluded_category_items),
        "preferred_categories": dict(sorted(constraints.preferred_categories.items())),
        "preferred_sources": dict(sorted(constraints.preferred_sources.items())),
        "preferred_keywords": dict(sorted(constraints.preferred_keywords.items())),
        "disliked_keywords": dict(sorted(constraints.disliked_keywords.items())),
        "filter_prior_turn_items": constraints.filter_prior_turn_items,
        "prior_turn_items": sorted(prior_turn_items),
        "unsupported_free_text": list(constraints.unsupported_free_text),
        "boosts_applied": _boost_diagnostics(kept),
        "boost_events": _boost_event_diagnostics(kept),
        "filter_events": sorted(filter_events, key=lambda event: (event["item_id"], event["type"])),
    }
    return kept, diagnostics


def _intent_clauses(text: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"\b(dislike|avoid|exclude|prefer|like)\b|不喜欢|不要|排除|喜欢|偏好", re.IGNORECASE)
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


def _apply_negative_keywords(matches: list[tuple[str, str]], constraints: FeedbackConstraints) -> None:
    for keyword, _ in matches:
        constraints.disliked_keywords[keyword] = 1.0


def _apply_positive_keywords(matches: list[tuple[str, str]], constraints: FeedbackConstraints) -> None:
    for keyword, _ in matches:
        constraints.preferred_keywords[keyword] = 1.0


def _apply_negative_tokens(tokens: list[str], constraints: FeedbackConstraints) -> None:
    for token in tokens:
        if _canonical_keyword(token):
            continue
        if _looks_like_item_id(token):
            constraints.disliked_item_ids.add(token)
        else:
            constraints.disliked_categories.add(token)


def _apply_positive_tokens(tokens: list[str], constraints: FeedbackConstraints) -> None:
    for token in tokens:
        source = _SOURCE_ALIASES.get(token.lower())
        if source:
            constraints.preferred_sources[source] = 1.0
        elif _canonical_keyword(token):
            continue
        else:
            constraints.preferred_categories[token] = 1.0


def _looks_like_item_id(token: str) -> bool:
    return "_" in token or any(char.isdigit() for char in token)


def _has_supported_constraint(constraints: FeedbackConstraints) -> bool:
    return bool(
        constraints.disliked_item_ids
        or constraints.disliked_categories
        or constraints.preferred_categories
        or constraints.preferred_sources
        or constraints.preferred_keywords
        or constraints.disliked_keywords
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
        if _contains_keyword_alias(normalized, alias):
            matches.append((keyword, alias))
            occupied_tokens.update(alias_tokens)
    return matches


def _canonical_keyword(value: str) -> str | None:
    normalized = _normalize_keyword_text(value)
    for keyword, aliases in _KEYWORD_ALIASES.items():
        if keyword == normalized or any(_normalize_keyword_text(alias) == normalized for alias in aliases):
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
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def _configured_value_for_key(values: set[str], matched_value: str) -> str:
    key = matched_value.lower()
    for value in values:
        if value.lower() == key:
            return value
    return matched_value
