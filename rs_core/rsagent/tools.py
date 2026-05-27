from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from rs_core.rsagent.schema import (
    DIALOGUE_PLAN_INTENTS,
    INTENT_ASK_EXPLANATION,
    INTENT_CLARIFICATION_ANSWER,
    INTENT_PREFERENCE_FEEDBACK,
    INTENT_RECOMMEND_REQUEST,
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, set | frozenset):
        return sorted(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class AgentToolSpec:
    name: str
    stage: str
    description: str
    input_schema_name: str
    output_schema_name: str
    read_only: bool
    hidden: bool
    public_payload_allowed: bool
    allowed_intents: frozenset[str]
    requires_candidate_pool: bool = False
    uses_reference_item: bool = False
    can_search_catalog: bool = False
    uses_rag_evidence: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class AgentCapability:
    name: str
    stage: str
    read_only: bool
    hidden: bool
    public_payload_allowed: bool
    description: str


@dataclass(frozen=True)
class UnderstandUserNeedInput:
    user_input: str
    session_id: str = ""
    user_id: str | None = None
    last_intent: str | None = None
    pending_clarification: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class UnderstandUserNeedOutput:
    intent: str
    action: str
    constraints: dict[str, Any] = field(default_factory=dict)
    needs_clarification: bool = False
    clarification_question: str | None = None
    confidence: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class DisplayResponseDraft:
    user_need_summary: str = ""
    assistant_strategy: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    product_reasons: list[dict[str, Any]] = field(default_factory=list)
    follow_up_question: str | None = None
    feedback_actions: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class PriceConstraint:
    min_price: float | None = None
    max_price: float | None = None
    currency: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class KeywordConstraint:
    keywords: list[str] = field(default_factory=list)
    mode: str = "any"
    required: list[str] = field(default_factory=list)
    preferred: list[str] = field(default_factory=list)
    disliked: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class CategoryConstraint:
    categories: list[str] = field(default_factory=list)
    mode: str = "any"
    not_categories: list[str] = field(default_factory=list)
    same_as_reference: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class RatingConstraint:
    min_rating: float | None = None
    max_rating: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class BrandConstraint:
    brands: list[str] = field(default_factory=list)
    mode: str = "any"
    not_brands: list[str] = field(default_factory=list)
    not_eq_reference: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class ProductSearchRequest:
    query: str = ""
    price: PriceConstraint | None = None
    keywords: KeywordConstraint | None = None
    category: CategoryConstraint | None = None
    rating: RatingConstraint | None = None
    brand: BrandConstraint | None = None
    limit: int = 20
    candidate_pool: list[str] = field(default_factory=list)
    reference_item_id: str | None = None
    similar_to_item_id: str | None = None
    target_item_id: str | None = None
    exclude_item_ids: list[str] = field(default_factory=list)
    exclude_seen_items: bool = False
    constraints: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class CatalogMatchReason:
    field: str
    matched_value: str | float | int | None = None
    reason: str = ""
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class CatalogConstraintSearchOutput:
    matched_items: list[dict[str, Any]] = field(default_factory=list)
    match_reasons: dict[str, list[CatalogMatchReason]] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


CatalogItems = dict[str, dict[str, Any]] | list[dict[str, Any]] | tuple[dict[str, Any], ...]


_TEXT_FIELDS = ("title", "title_clean", "main_category", "category", "description", "features", "store", "brand")


def catalog_constraint_search(
    request: ProductSearchRequest,
    catalog_items: CatalogItems,
    seen_item_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    min_results: int | None = None,
) -> CatalogConstraintSearchOutput:
    items = _normalize_catalog_items(catalog_items)
    reference_id = request.similar_to_item_id or request.reference_item_id or request.target_item_id
    reference = items.get(reference_id or "", {})
    excluded = set(request.exclude_item_ids)
    if request.target_item_id:
        excluded.add(request.target_item_id)
    if request.exclude_seen_items:
        excluded.update(seen_item_ids or [])
    candidate_ids = list(request.candidate_pool) if request.candidate_pool else list(items)
    minimum = min_results if min_results is not None else min(request.limit, 3)

    ranked, diagnostics = _rank_catalog_candidates(request, items, candidate_ids, reference, excluded, relaxation_level=0)
    if len(ranked) < minimum:
        relaxed, relaxed_diagnostics = _rank_catalog_candidates(
            request,
            items,
            candidate_ids,
            reference,
            excluded,
            relaxation_level=1,
        )
        if len(relaxed) > len(ranked):
            ranked = relaxed
            diagnostics = relaxed_diagnostics

    matched = [item for _, item, _ in ranked[: request.limit]]
    reasons = {_item_id_field(item): item_reasons for _, item, item_reasons in ranked[: request.limit]}
    diagnostics.update({
        "catalog_item_count": len(items),
        "candidate_item_count": len(candidate_ids),
        "excluded_item_count": len(excluded),
        "matched_item_count": len(matched),
        "reference_item_id": reference_id,
    })
    return CatalogConstraintSearchOutput(matched_items=matched, match_reasons=reasons, diagnostics=diagnostics)


def _normalize_catalog_items(catalog_items: CatalogItems) -> dict[str, dict[str, Any]]:
    if isinstance(catalog_items, dict):
        normalized = {}
        for item_id, card in catalog_items.items():
            item = dict(card)
            item.setdefault("item_id", item_id)
            normalized[str(item_id)] = item
        return normalized
    normalized = {}
    for card in catalog_items:
        item = dict(card)
        item_id = _item_id_field(item)
        if item_id:
            normalized[item_id] = item
    return normalized


def _rank_catalog_candidates(
    request: ProductSearchRequest,
    items: dict[str, dict[str, Any]],
    candidate_ids: list[str],
    reference: dict[str, Any],
    excluded: set[str],
    relaxation_level: int,
) -> tuple[list[tuple[float, dict[str, Any], list[CatalogMatchReason]]], dict[str, Any]]:
    ranked = []
    filter_events = []
    for item_id in candidate_ids:
        item = items.get(str(item_id))
        if not item:
            continue
        normalized_id = _item_id_field(item)
        if normalized_id in excluded:
            filter_events.append({"item_id": normalized_id, "reason": "excluded_item"})
            continue
        hard_ok, hard_events = _passes_hard_constraints(request, item, reference, relaxation_level)
        filter_events.extend(hard_events)
        if not hard_ok:
            continue
        score, reasons = _score_catalog_item(request, item, reference, relaxation_level)
        if relaxation_level == 0 and _has_disliked_keyword(request, item):
            score -= 2.0
            reasons.append(CatalogMatchReason("keywords", None, "disliked keyword matched", -2.0))
        ranked.append((score, item, reasons))
    ranked.sort(key=lambda row: (-row[0], _item_id_field(row[1])))
    return ranked, {"relaxation_level": relaxation_level, "filtered_items": filter_events}


def _passes_hard_constraints(
    request: ProductSearchRequest,
    item: dict[str, Any],
    reference: dict[str, Any],
    relaxation_level: int,
) -> tuple[bool, list[dict[str, Any]]]:
    events = []
    item_id = _item_id_field(item)
    checks = [
        _passes_price_constraint(request, item, reference),
        _passes_category_constraint(request, item, reference),
        _passes_brand_constraint(request, item, reference),
        _passes_required_keywords(request, item, relaxation_level),
        _passes_rating_constraint(request, item),
        _passes_dict_constraints(request, item, reference),
    ]
    for passed, reason in checks:
        if not passed:
            events.append({"item_id": item_id, "reason": reason})
            return False, events
    return True, events


def _passes_price_constraint(request: ProductSearchRequest, item: dict[str, Any], reference: dict[str, Any]) -> tuple[bool, str]:
    price = _number(item.get("price"))
    if request.price:
        if request.price.min_price is not None:
            if price is None:
                return False, "price_missing"
            if price < request.price.min_price:
                return False, "price_below_min"
        if request.price.max_price is not None:
            if price is None:
                return False, "price_missing"
            if price > request.price.max_price:
                return False, "price_above_max"
    for constraint in request.constraints:
        if constraint.get("field") != "price":
            continue
        op = constraint.get("op")
        value = _constraint_value(constraint, reference, "price")
        if price is None:
            return False, "price_missing"
        if value is None:
            return False, "price_reference_missing"
        if op == "lt" and not price < value:
            return False, "price_not_lt"
        if op == "lte" and not price <= value:
            return False, "price_not_lte"
        if op == "gt" and not price > value:
            return False, "price_not_gt"
        if op == "gte" and not price >= value:
            return False, "price_not_gte"
        if op == "lt_ratio" and not price < value:
            return False, "price_not_lt_ratio"
        if op == "lte_ratio" and not price <= value:
            return False, "price_not_lte_ratio"
    return True, ""


def _passes_category_constraint(request: ProductSearchRequest, item: dict[str, Any], reference: dict[str, Any]) -> tuple[bool, str]:
    category = _norm_text(item.get("main_category") or item.get("category"))
    if request.category:
        categories = {_norm_text(value) for value in request.category.categories}
        not_categories = {_norm_text(value) for value in request.category.not_categories}
        if categories and category not in categories:
            return False, "category_not_allowed"
        if category in not_categories:
            return False, "category_blocked"
        if request.category.same_as_reference and reference:
            reference_category = _norm_text(reference.get("main_category") or reference.get("category"))
            if category != reference_category:
                return False, "category_not_same_as_reference"
    for constraint in request.constraints:
        if constraint.get("field") != "category":
            continue
        values = {_norm_text(value) for value in constraint.get("values", []) or [constraint.get("value", "")]}
        op = constraint.get("op")
        if op in {"in", "eq"} and category not in values:
            return False, "category_not_allowed"
        if op == "not_in" and category in values:
            return False, "category_blocked"
        if op == "same_as_reference" and reference:
            reference_category = _norm_text(reference.get("main_category") or reference.get("category"))
            if category != reference_category:
                return False, "category_not_same_as_reference"
    return True, ""


def _passes_brand_constraint(request: ProductSearchRequest, item: dict[str, Any], reference: dict[str, Any]) -> tuple[bool, str]:
    brand = _norm_text(item.get("brand") or item.get("store"))
    if request.brand:
        brands = {_norm_text(value) for value in request.brand.brands}
        not_brands = {_norm_text(value) for value in request.brand.not_brands}
        if brands and brand not in brands:
            return False, "brand_not_allowed"
        if brand in not_brands:
            return False, "brand_blocked"
        if request.brand.not_eq_reference and reference:
            reference_brand = _norm_text(reference.get("brand") or reference.get("store"))
            if brand == reference_brand:
                return False, "brand_same_as_reference"
    for constraint in request.constraints:
        field = constraint.get("field")
        if field not in {"brand", "store"}:
            continue
        value = _norm_text(item.get(field))
        ref_value = _norm_text(reference.get(field)) if reference else ""
        values = {_norm_text(value) for value in constraint.get("values", []) or [constraint.get("value", "")]}
        op = constraint.get("op")
        if op in {"in", "eq"} and value not in values:
            return False, f"{field}_not_allowed"
        if op in {"not_in", "not_eq"} and value in values:
            return False, f"{field}_blocked"
        if op == "not_eq_reference" and ref_value and value == ref_value:
            return False, f"{field}_same_as_reference"
    return True, ""


def _passes_required_keywords(request: ProductSearchRequest, item: dict[str, Any], relaxation_level: int) -> tuple[bool, str]:
    required = []
    if request.keywords:
        required.extend(request.keywords.required)
        if request.keywords.mode == "all":
            required.extend(request.keywords.keywords)
        if relaxation_level == 0:
            required.extend(request.keywords.preferred)
    for constraint in request.constraints:
        if constraint.get("field") == "keyword" and constraint.get("op") in {"required", "contains_all"}:
            required.extend(constraint.get("values", []) or [constraint.get("value", "")])
        if relaxation_level == 0 and constraint.get("field") == "keyword" and constraint.get("op") == "preferred":
            required.extend(constraint.get("values", []) or [constraint.get("value", "")])
    text = _search_text(item)
    for keyword in required:
        if _norm_text(keyword) not in text:
            return False, "required_keyword_missing"
    return True, ""


def _passes_rating_constraint(request: ProductSearchRequest, item: dict[str, Any]) -> tuple[bool, str]:
    rating = _number(item.get("rating") or item.get("average_rating"))
    if not request.rating or rating is None:
        return True, ""
    if request.rating.min_rating is not None and rating < request.rating.min_rating:
        return False, "rating_below_min"
    if request.rating.max_rating is not None and rating > request.rating.max_rating:
        return False, "rating_above_max"
    return True, ""


def _passes_dict_constraints(request: ProductSearchRequest, item: dict[str, Any], reference: dict[str, Any]) -> tuple[bool, str]:
    for constraint in request.constraints:
        field = constraint.get("field")
        if field in {"price", "category", "brand", "store", "keyword"}:
            continue
        op = constraint.get("op")
        if field not in item:
            if op in {"eq", "in", "required", "not_eq_reference"}:
                return False, f"{field}_missing"
            continue
        value = item.get(field)
        expected = constraint.get("value")
        if op == "eq" and value != expected:
            return False, f"{field}_not_eq"
        if op == "not_eq_reference" and reference and value == reference.get(field):
            return False, f"{field}_same_as_reference"
    return True, ""


def _score_catalog_item(
    request: ProductSearchRequest,
    item: dict[str, Any],
    reference: dict[str, Any],
    relaxation_level: int,
) -> tuple[float, list[CatalogMatchReason]]:
    score = 0.0
    reasons = []
    score += _score_reference_overlap(item, reference, reasons)
    score += _score_keywords(request, item, reasons, relaxation_level)
    score += _score_price(request, item, reference, reasons)
    score += _score_quality(item, reasons)
    return score, reasons


def _score_reference_overlap(item: dict[str, Any], reference: dict[str, Any], reasons: list[CatalogMatchReason]) -> float:
    if not reference:
        return 0.0
    score = 0.0
    for field_name in ("main_category", "category", "brand", "store"):
        value = item.get(field_name)
        if value and _norm_text(value) == _norm_text(reference.get(field_name)):
            score += 1.0
            reasons.append(CatalogMatchReason(field_name, value, f"same {field_name} as reference", 1.0))
            break
    item_tokens = set(_search_text(item).split())
    reference_tokens = set(_search_text(reference).split())
    overlap = sorted((item_tokens & reference_tokens) - {"", "and", "the", "for", "with"})[:5]
    if overlap:
        delta = min(len(overlap) * 0.2, 1.0)
        score += delta
        reasons.append(CatalogMatchReason("text", " ".join(overlap), "text overlap with reference", delta))
    return score


def _score_keywords(
    request: ProductSearchRequest,
    item: dict[str, Any],
    reasons: list[CatalogMatchReason],
    relaxation_level: int,
) -> float:
    text = _search_text(item)
    keywords = []
    if request.query:
        keywords.extend(request.query.split())
    if request.keywords:
        keywords.extend(request.keywords.keywords)
        keywords.extend(request.keywords.required)
        if relaxation_level == 0:
            keywords.extend(request.keywords.preferred)
    if relaxation_level == 0:
        for constraint in request.constraints:
            if constraint.get("field") == "keyword" and constraint.get("op") == "preferred":
                keywords.extend(constraint.get("values", []) or [constraint.get("value", "")])
    score = 0.0
    for keyword in dict.fromkeys(_norm_text(keyword) for keyword in keywords if keyword):
        if keyword and keyword in text:
            field_name = _keyword_field(item, keyword)
            score += 0.7
            reasons.append(CatalogMatchReason(field_name, keyword, f"keyword found in {field_name}", 0.7))
    return score


def _score_price(request: ProductSearchRequest, item: dict[str, Any], reference: dict[str, Any], reasons: list[CatalogMatchReason]) -> float:
    price = _number(item.get("price"))
    reference_price = _number(reference.get("price")) if reference else None
    if price is None or reference_price is None or reference_price <= 0:
        return 0.0
    for constraint in request.constraints:
        if constraint.get("field") == "price" and constraint.get("op") in {"lt", "lte", "lt_ratio", "lte_ratio"}:
            if price < reference_price:
                delta = min((reference_price - price) / reference_price, 1.0) * 2.0
                reasons.append(CatalogMatchReason("price", price, "cheaper than reference", delta))
                return delta
    if request.reference_item_id or request.similar_to_item_id:
        delta = max(0.0, 1.0 - abs(price - reference_price) / reference_price) * 0.5
        if delta:
            reasons.append(CatalogMatchReason("price", price, "price close to reference", delta))
        return delta
    return 0.0


def _score_quality(item: dict[str, Any], reasons: list[CatalogMatchReason]) -> float:
    score = 0.0
    rating = _number(item.get("rating") or item.get("average_rating"))
    if rating is not None:
        delta = max(min(rating / 5.0, 1.0), 0.0)
        score += delta
        reasons.append(CatalogMatchReason("rating", rating, "rating quality signal", delta))
    quality = _number(item.get("quality") or item.get("quality_score"))
    if quality is not None:
        delta = max(min(quality, 1.0), 0.0)
        score += delta
        reasons.append(CatalogMatchReason("quality", quality, "quality score signal", delta))
    return score


def _has_disliked_keyword(request: ProductSearchRequest, item: dict[str, Any]) -> bool:
    disliked = list(request.keywords.disliked) if request.keywords else []
    for constraint in request.constraints:
        if constraint.get("field") == "keyword" and constraint.get("op") == "disliked":
            disliked.extend(constraint.get("values", []) or [constraint.get("value", "")])
    text = _search_text(item)
    return any(_norm_text(keyword) in text for keyword in disliked if keyword)


def _constraint_value(constraint: dict[str, Any], reference: dict[str, Any], reference_field: str) -> float | None:
    value = _number(constraint.get("value"))
    reference_value = _number(reference.get(reference_field)) if reference else None
    if constraint.get("reference_item_id") or constraint.get("reference_field") or constraint.get("op") in {"lt_ratio", "lte_ratio"}:
        if reference_value is None:
            return value
        if constraint.get("op") in {"lt_ratio", "lte_ratio"}:
            return reference_value * (value if value is not None else 1.0)
        return reference_value
    return value


def _item_id_field(item: dict[str, Any]) -> str:
    for field_name in ("item_id", "parent_asin", "asin"):
        value = item.get(field_name)
        if value:
            return str(value)
    return ""


def _search_text(item: dict[str, Any]) -> str:
    values = []
    for field_name in _TEXT_FIELDS:
        value = item.get(field_name)
        if isinstance(value, list):
            values.extend(str(part) for part in value)
        elif value is not None:
            values.append(str(value))
    return _norm_text(" ".join(values))


def _keyword_field(item: dict[str, Any], keyword: str) -> str:
    for field_name in _TEXT_FIELDS:
        value = item.get(field_name)
        if isinstance(value, list):
            text = _norm_text(" ".join(str(part) for part in value))
        else:
            text = _norm_text(value)
        if keyword in text:
            return field_name
    return "text"


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def _norm_text(value: Any) -> str:
    return str(value or "").strip().lower()


AGENT_TOOL_MANIFEST = (
    AgentToolSpec(
        name="understand_user_need",
        stage="dialogue_understanding",
        description="Interpret the current user turn into internal recommendation intent and constraints.",
        input_schema_name="UnderstandUserNeedInput",
        output_schema_name="UnderstandUserNeedOutput",
        read_only=False,
        hidden=True,
        public_payload_allowed=False,
        allowed_intents=DIALOGUE_PLAN_INTENTS,
    ),
    AgentToolSpec(
        name="rerank_for_browsing",
        stage="ranking",
        description="Rerank an existing candidate pool for browsing-oriented recommendation turns.",
        input_schema_name="RecommendationTurnResult",
        output_schema_name="AgentDecision",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        allowed_intents=frozenset({INTENT_RECOMMEND_REQUEST, INTENT_PREFERENCE_FEEDBACK, INTENT_CLARIFICATION_ANSWER}),
        requires_candidate_pool=True,
    ),
    AgentToolSpec(
        name="match_specific_need_in_pool",
        stage="candidate_matching",
        description="Match specific constraints against already available candidate items.",
        input_schema_name="ProductSearchRequest",
        output_schema_name="CatalogConstraintSearchOutput",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        allowed_intents=frozenset({INTENT_RECOMMEND_REQUEST, INTENT_PREFERENCE_FEEDBACK, INTENT_CLARIFICATION_ANSWER}),
        requires_candidate_pool=True,
    ),
    AgentToolSpec(
        name="catalog_constraint_search",
        stage="catalog_search",
        description="Search catalog metadata using lightweight structured product constraints.",
        input_schema_name="ProductSearchRequest",
        output_schema_name="CatalogConstraintSearchOutput",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        allowed_intents=frozenset({INTENT_RECOMMEND_REQUEST, INTENT_PREFERENCE_FEEDBACK, INTENT_CLARIFICATION_ANSWER}),
        can_search_catalog=True,
    ),
    AgentToolSpec(
        name="build_product_reasoning",
        stage="evidence",
        description="Build grounded internal product evidence for recommendation reasoning.",
        input_schema_name="AgentDecision",
        output_schema_name="RewardEvidence",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        allowed_intents=frozenset({INTENT_RECOMMEND_REQUEST, INTENT_PREFERENCE_FEEDBACK, INTENT_ASK_EXPLANATION}),
        requires_candidate_pool=True,
        uses_reference_item=True,
        uses_rag_evidence=True,
    ),
    AgentToolSpec(
        name="compose_shopping_response",
        stage="response_composition",
        description="Compose the display-safe shopping response from selected items and grounded evidence.",
        input_schema_name="DisplayResponseDraft",
        output_schema_name="DisplayResponse",
        read_only=True,
        hidden=True,
        public_payload_allowed=True,
        allowed_intents=DIALOGUE_PLAN_INTENTS,
        uses_rag_evidence=True,
    ),
)

AGENT_CAPABILITY_MANIFEST = (
    AgentCapability(
        name="parse_preferences",
        stage="dialogue",
        read_only=False,
        hidden=True,
        public_payload_allowed=False,
        description="Parse user preference text into structured recommendation constraints.",
    ),
    AgentCapability(
        name="apply_constraints",
        stage="candidate_filtering",
        read_only=False,
        hidden=True,
        public_payload_allowed=False,
        description="Apply hard and soft user constraints before presentation.",
    ),
    AgentCapability(
        name="retrieve_candidates",
        stage="candidate_generation",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        description="Retrieve candidate items from configured recall inputs.",
    ),
    AgentCapability(
        name="rank_candidates",
        stage="ranking",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        description="Rank candidate items for the current user turn.",
    ),
    AgentCapability(
        name="build_rag_context",
        stage="evidence",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        description="Build grounded product evidence for internal explanation support.",
    ),
    AgentCapability(
        name="explain_recommendation",
        stage="dialogue",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        description="Generate a user-facing explanation from display-safe item facts.",
    ),
    AgentCapability(
        name="collect_feedback",
        stage="feedback",
        read_only=False,
        hidden=True,
        public_payload_allowed=False,
        description="Collect explicit user feedback for the active session state.",
    ),
)

TOOL_EVENT_KEYS = ("constraint_filter_events", "feedback_rerank_events")


def collect_diagnostic_tool_events(diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for key in TOOL_EVENT_KEYS:
        events.extend(event for event in diagnostics.get(key, []) if isinstance(event, dict))
    return events


def collect_turn_tool_events(turns: list[Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for turn in turns:
        events.extend(collect_diagnostic_tool_events(turn.diagnostics))
    return events


def collect_rollout_tool_events(rollouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for rollout in rollouts:
        diagnostics = rollout.get("diagnostics", {})
        events.extend(collect_diagnostic_tool_events(diagnostics))
    return events
