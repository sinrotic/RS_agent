from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

DEFAULT_DOCUMENT_COUNT = 864_288

GENERIC_TOKENS = {
    "and",
    "the",
    "with",
    "for",
    "from",
    "item",
    "product",
    "products",
    "a",
    "an",
    "of",
    "to",
    "in",
    "on",
    "by",
    "or",
    "set",
    "pack",
}

FIELD_WEIGHTS = {
    "title_clean": 5.0,
    "main_category": 4.0,
    "category": 3.0,
    "categories_flat": 2.5,
    "description_text": 0.4,
    "features_text": 0.4,
}

SCORING_FIELDS = [
    "title_clean",
    "main_category",
    "category",
    "categories_flat",
    "description_text",
    "features_text",
]

STRICT_QUERY_FIXTURES: list[dict[str, Any]] = [
    {
        "id": "medical_clipboard",
        "description": "folding medical clipboard for respiratory therapists with HIPAA patient forms",
        "core_terms": ["medical", "clipboard"],
        "must_any_groups": [["clipboard"], ["medical", "nursing", "nurse", "patient", "hipaa"]],
        "intent_phrases": ["medical clipboard", "nursing clipboard", "patient sign in", "hipaa"],
        "category_any": ["office"],
        "negative_phrases": ["keyboard", "mouse pad"],
    },
    {
        "id": "wireless_mouse",
        "description": "wireless ergonomic computer mouse for office laptop",
        "core_terms": ["wireless", "mouse"],
        "must_terms": ["mouse"],
        "must_any_groups": [["wireless", "bluetooth", "2.4g", "2.4ghz"]],
        "intent_phrases": ["wireless mouse", "bluetooth mouse"],
        "category_any": ["electronics", "computers"],
        "negative_phrases": ["mouse pad", "mousepad", "wrist rest", "desk mat", "case for"],
    },
    {
        "id": "gaming_keyboard",
        "description": "rgb mechanical gaming keyboard for pc gamers",
        "core_terms": ["gaming", "keyboard"],
        "must_terms": ["keyboard"],
        "must_any_groups": [["gaming", "gamer", "gamers"], ["rgb", "backlit", "mechanical"]],
        "intent_phrases": ["gaming keyboard", "mechanical keyboard"],
        "category_any": ["electronics", "computers"],
        "negative_phrases": ["mouse pad", "keyboard cover", "case"],
    },
    {
        "id": "usb_c_hub",
        "description": "usb c hub adapter with hdmi and ethernet for laptop",
        "core_terms": ["usb", "hub"],
        "must_terms": ["usb"],
        "must_any_groups": [["hub", "dock", "docking", "adapter"], ["hdmi", "ethernet"]],
        "intent_phrases": ["usb c hub", "usb-c hub", "docking station"],
        "category_any": ["electronics", "computers"],
        "negative_phrases": ["cable only", "case for"],
    },
    {
        "id": "yoga_mat",
        "description": "non slip yoga mat for home fitness exercise",
        "core_terms": ["yoga", "mat"],
        "must_terms": ["mat"],
        "must_any_groups": [["yoga", "pilates", "exercise", "fitness"]],
        "intent_phrases": ["yoga mat", "exercise mat", "pilates mat"],
        "category_any": ["sports", "fitness", "home"],
        "negative_phrases": [
            "chair mat",
            "desk chair",
            "office chair",
            "floor protector",
            "mouse pad",
            "cord wrap",
            "storage strap",
            "standing desk",
            "anti fatigue",
        ],
    },
    {
        "id": "dog_chew_toy",
        "description": "durable dog chew toy for aggressive chewers",
        "core_terms": ["dog", "chew"],
        "must_terms": ["dog"],
        "must_any_groups": [["chew", "chewer", "chewers", "chewable"], ["toy", "bone", "treat"]],
        "intent_phrases": ["dog chew toy", "chew toy", "dog toy"],
        "category_any": ["pet", "pets"],
        "negative_phrases": ["cord protector", "cable protector", "bookmark", "dog tag", "necklace", "pencil"],
    },
    {
        "id": "stainless_bottle",
        "description": "insulated stainless steel water bottle keeps drinks cold",
        "core_terms": ["water", "bottle"],
        "must_terms": ["bottle"],
        "must_any_groups": [["stainless", "steel", "insulated"], ["water", "drink", "drinks"]],
        "intent_phrases": ["water bottle", "stainless steel", "insulated bottle"],
        "negative_phrases": ["journal", "badge reel", "earbud"],
    },
    {
        "id": "coffee_mug",
        "description": "ceramic coffee mug with handle for hot drinks",
        "core_terms": ["coffee", "mug"],
        "must_terms": ["mug"],
        "must_any_groups": [["coffee", "tea", "drink", "drinks"]],
        "intent_phrases": ["coffee mug", "ceramic mug", "tea mug"],
        "category_any": ["home", "kitchen"],
        "negative_phrases": ["coaster", "mouse pad", "warmer", "heating pad"],
    },
    {
        "id": "led_grow_light",
        "description": "led grow light for indoor plants full spectrum",
        "core_terms": ["grow", "light"],
        "must_terms": ["light"],
        "must_any_groups": [["grow", "growing", "plant", "plants"], ["led", "spectrum"]],
        "intent_phrases": ["grow light", "plant light", "full spectrum"],
        "category_any": ["home", "tools", "garden"],
        "negative_phrases": ["light meter", "camera lens", "phone case"],
    },
    {
        "id": "baby_stroller_organizer",
        "description": "baby stroller organizer bag with cup holder",
        "core_terms": ["baby", "stroller"],
        "must_terms": ["stroller"],
        "must_any_groups": [["baby", "infant", "toddler"], ["organizer", "bag", "holder"]],
        "intent_phrases": ["stroller organizer", "baby stroller"],
        "category_any": ["baby"],
        "negative_phrases": ["desk organizer", "pencil", "pen holder", "office", "utensil", "silverware"],
    },
    {
        "id": "cat_litter_mat",
        "description": "waterproof cat litter mat traps litter from box",
        "core_terms": ["cat", "litter", "mat"],
        "must_terms": ["cat", "litter", "mat"],
        "intent_phrases": ["cat litter mat", "litter mat", "trapping mat"],
        "category_any": ["pet", "pets"],
        "negative_phrases": ["adapter", "power supply", "charger", "cord", "cable", "battery", "robot", "litter box"],
    },
    {
        "id": "running_shoes",
        "description": "lightweight running shoes for men breathable sneakers",
        "core_terms": ["running", "shoes"],
        "must_terms": ["shoes"],
        "must_any_groups": [["running", "walking", "athletic", "sports", "sneaker", "sneakers"]],
        "intent_phrases": ["running shoes", "athletic shoes", "walking shoes"],
        "category_any": ["fashion", "shoes", "sports"],
        "negative_phrases": ["airpods", "case", "fitbit", "watch band", "replacement band", "gps running watch", "boots"],
    },
]


@dataclass(frozen=True)
class PreparedPhrase:
    raw: str
    normalized: str


@dataclass(frozen=True)
class PreparedFixture:
    raw: dict[str, Any]
    query_terms: set[str]
    core_token_terms: set[str]
    core_phrases: tuple[PreparedPhrase, ...]
    must_terms: tuple[PreparedPhrase, ...]
    must_any_groups: tuple[tuple[PreparedPhrase, ...], ...]
    intent_phrases: tuple[PreparedPhrase, ...]
    category_any: tuple[PreparedPhrase, ...]
    negative_phrases: tuple[PreparedPhrase, ...]


@dataclass(frozen=True)
class PreparedRecord:
    raw: dict[str, Any]
    field_texts: dict[str, str]
    field_terms: dict[str, list[str]]
    field_counts: dict[str, Counter[str]]
    title_text: str
    category_text: str
    full_text: str


def tokens(value: Any) -> list[str]:
    if isinstance(value, list):
        value = " ".join(str(item) for item in value)
    if value is None:
        return []
    return [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9]+", str(value))
        if len(token) > 1 and token.lower() not in GENERIC_TOKENS
    ]


def normalized_text(value: Any) -> str:
    if isinstance(value, list):
        value = " ".join(str(item) for item in value)
    return " ".join(tokens(value))


def record_text(record: dict[str, Any], *, fields: list[str] | None = None) -> str:
    selected = fields or SCORING_FIELDS
    return " ".join(normalized_text(record.get(field)) for field in selected)


def phrase_present(text: str, phrase: str) -> bool:
    normalized_phrase = normalized_text(phrase)
    return _normalized_phrase_present(text, normalized_phrase)


def fixture_query_terms(fixture: dict[str, Any]) -> set[str]:
    values: list[str] = [str(fixture.get("description") or "")]
    for key in ("core_terms", "must_terms", "intent_phrases", "category_any", "negative_phrases"):
        raw = fixture.get(key) or []
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
    for group in fixture.get("must_any_groups") or []:
        if isinstance(group, list):
            values.extend(str(item) for item in group)
    return set(tokens(" ".join(values)))


def prepare_fixture(fixture: dict[str, Any]) -> PreparedFixture:
    return PreparedFixture(
        raw=fixture,
        query_terms=fixture_query_terms(fixture),
        core_token_terms=set(tokens(" ".join(str(item) for item in fixture.get("core_terms") or []))),
        core_phrases=_prepared_phrases(fixture.get("core_terms") or []),
        must_terms=_prepared_phrases(fixture.get("must_terms") or []),
        must_any_groups=tuple(_prepared_phrases(group) for group in fixture.get("must_any_groups") or [] if isinstance(group, list)),
        intent_phrases=_prepared_phrases(fixture.get("intent_phrases") or []),
        category_any=_prepared_phrases(fixture.get("category_any") or []),
        negative_phrases=_prepared_phrases(fixture.get("negative_phrases") or []),
    )


def prepare_record(record: dict[str, Any]) -> PreparedRecord:
    field_terms = {field: tokens(record.get(field)) for field in SCORING_FIELDS}
    field_texts = {field: " ".join(field_terms[field]) for field in SCORING_FIELDS}
    field_counts = {field: Counter(terms) for field, terms in field_terms.items() if terms}
    title_text = field_texts["title_clean"]
    category_text = " ".join(field_texts[field] for field in ["main_category", "category", "categories_flat"])
    full_text = " ".join(field_texts[field] for field in SCORING_FIELDS)
    return PreparedRecord(
        raw=record,
        field_texts=field_texts,
        field_terms=field_terms,
        field_counts=field_counts,
        title_text=title_text,
        category_text=category_text,
        full_text=full_text,
    )


def evaluate_intent(fixture: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    return evaluate_prepared_intent(prepare_fixture(fixture), prepare_record(record))


def evaluate_prepared_intent(fixture: PreparedFixture, record: PreparedRecord) -> dict[str, Any]:
    full_text = _padded_text(record.full_text)
    title_text = _padded_text(record.title_text)
    category_text = _padded_text(record.category_text)
    missing_must_terms = [term.raw for term in fixture.must_terms if not _normalized_phrase_present_padded(full_text, term.normalized)]

    group_hits = []
    missing_groups = []
    for group in fixture.must_any_groups:
        hits = [term.raw for term in group if _normalized_phrase_present_padded(full_text, term.normalized)]
        if hits:
            group_hits.append(hits)
        else:
            missing_groups.append([term.raw for term in group])

    core_hits = [term.raw for term in fixture.core_phrases if _normalized_phrase_present_padded(full_text, term.normalized)]
    title_core_hits = [term.raw for term in fixture.core_phrases if _normalized_phrase_present_padded(title_text, term.normalized)]
    phrase_hits = [phrase.raw for phrase in fixture.intent_phrases if _normalized_phrase_present_padded(full_text, phrase.normalized)]
    category_hits = [cat.raw for cat in fixture.category_any if _normalized_phrase_present_padded(category_text, cat.normalized)]
    negative_hits = [phrase.raw for phrase in fixture.negative_phrases if _normalized_phrase_present_padded(full_text, phrase.normalized)]

    required_pass = not missing_must_terms and not missing_groups
    strict_intent_pass = required_pass and not negative_hits
    if fixture.category_any:
        strict_intent_pass = strict_intent_pass and bool(category_hits)

    return {
        "required_pass": required_pass,
        "strict_intent_pass": strict_intent_pass,
        "core_hits": core_hits,
        "title_core_hits": title_core_hits,
        "missing_must_terms": missing_must_terms,
        "missing_any_groups": missing_groups,
        "intent_phrase_hits": phrase_hits,
        "category_match": bool(category_hits),
        "category_hits": category_hits,
        "negative_hits": negative_hits,
    }


def score_record(
    fixture: dict[str, Any],
    record: dict[str, Any],
    doc_freq: dict[str, int],
    *,
    document_count: int = DEFAULT_DOCUMENT_COUNT,
) -> tuple[float, dict[str, Any]]:
    return score_prepared_record(prepare_fixture(fixture), prepare_record(record), doc_freq, document_count=document_count)


def score_prepared_record(
    fixture: PreparedFixture,
    record: PreparedRecord,
    doc_freq: dict[str, int],
    *,
    document_count: int = DEFAULT_DOCUMENT_COUNT,
) -> tuple[float, dict[str, Any]]:
    return score_prepared_record_with_token_weights(
        fixture,
        record,
        query_token_weights(fixture, doc_freq, document_count=document_count),
    )


def score_prepared_record_with_token_weights(
    fixture: PreparedFixture,
    record: PreparedRecord,
    token_weights: dict[str, float],
) -> tuple[float, dict[str, Any]]:
    field_scores: dict[str, float] = {}
    total = 0.0
    for field, weight in FIELD_WEIGHTS.items():
        counts = record.field_counts.get(field)
        if not counts:
            continue
        subtotal = 0.0
        for token, token_weight in token_weights.items():
            tf = counts.get(token, 0)
            if tf <= 0:
                continue
            subtotal += token_weight * ((tf * 2.2) / (tf + 1.2))
        if subtotal:
            weighted = subtotal * weight
            field_scores[field] = round(weighted, 6)
            total += weighted

    intent_signals = evaluate_prepared_intent(fixture, record)
    adjustments: dict[str, float] = {}

    full_text = _padded_text(record.full_text)
    title_text = _padded_text(record.title_text)
    for phrase in fixture.intent_phrases:
        if _normalized_phrase_present_padded(title_text, phrase.normalized):
            adjustments[f"title_phrase:{phrase.raw}"] = 60.0
            total += 60.0
        elif _normalized_phrase_present_padded(full_text, phrase.normalized):
            adjustments[f"body_phrase:{phrase.raw}"] = 25.0
            total += 25.0

    title_core_hit_count = 0
    for term in fixture.core_phrases:
        if _normalized_phrase_present_padded(title_text, term.normalized):
            title_core_hit_count += 1
            adjustments[f"title_core:{term.raw}"] = 28.0
            total += 28.0
        elif _normalized_phrase_present_padded(full_text, term.normalized):
            adjustments[f"body_core:{term.raw}"] = 5.0
            total += 5.0
        else:
            adjustments[f"missing_core:{term.raw}"] = -90.0
            total -= 90.0
    if fixture.core_phrases and title_core_hit_count < len(fixture.core_phrases):
        penalty = -55.0 * float(len(fixture.core_phrases) - title_core_hit_count)
        adjustments["title_core_coverage_gap"] = penalty
        total += penalty

    if intent_signals["category_match"]:
        adjustments["category_prior"] = 45.0
        total += 45.0
    elif fixture.category_any:
        adjustments["missing_category_prior"] = -20.0
        total -= 20.0

    for negative in intent_signals["negative_hits"]:
        penalty = -120.0 if phrase_present(record.title_text, negative) else -80.0
        adjustments[f"negative:{negative}"] = penalty
        total += penalty

    if not intent_signals["required_pass"]:
        adjustments["required_intent_miss"] = -120.0
        total -= 120.0

    details = {
        "field_scores": field_scores,
        "adjustments": {key: round(value, 6) for key, value in adjustments.items()},
        **intent_signals,
    }
    return round(total, 6), details


def query_token_weights(
    fixture: PreparedFixture,
    doc_freq: dict[str, int],
    *,
    document_count: int = DEFAULT_DOCUMENT_COUNT,
) -> dict[str, float]:
    weights: dict[str, float] = {}
    for token in fixture.query_terms:
        df = max(1, doc_freq.get(token, 1))
        idf = math.log(1.0 + (document_count - df + 0.5) / (df + 0.5))
        role_weight = 3.0 if token in fixture.core_token_terms else 1.0
        weights[token] = role_weight * idf
    return weights


def _prepared_phrases(values: list[Any]) -> tuple[PreparedPhrase, ...]:
    return tuple(PreparedPhrase(raw=str(item), normalized=normalized_text(str(item))) for item in values)


def _normalized_phrase_present(text: str, normalized_phrase: str) -> bool:
    if not normalized_phrase:
        return False
    return _normalized_phrase_present_padded(_padded_text(text), normalized_phrase)


def _padded_text(text: str) -> str:
    return f" {text} "


def _normalized_phrase_present_padded(padded_text: str, normalized_phrase: str) -> bool:
    if not normalized_phrase:
        return False
    return f" {normalized_phrase} " in padded_text
