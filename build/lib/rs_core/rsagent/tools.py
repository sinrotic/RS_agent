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
class AgentToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    phase: str = ""
    call_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class AgentToolResult:
    name: str
    phase: str
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    event: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    error_type: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class AgentToolExecutionReport:
    phase: str
    results: list[AgentToolResult] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "results": [result.to_dict() for result in self.results],
            "summary": _jsonable(self.summary),
        }


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
class GetUserContextInput:
    session_id: str = ""
    include_recent_turns: int = 3
    include_constraints: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class GetUserContextOutput:
    session_id: str
    user_id: str
    turn_count: int = 0
    current_goal: str = ""
    latest_intent: str | None = None
    latest_action: str | None = None
    pending_clarification: str | None = None
    active_constraints: dict[str, Any] = field(default_factory=dict)
    shown_item_ids: list[str] = field(default_factory=list)
    liked_item_ids: list[str] = field(default_factory=list)
    disliked_item_ids: list[str] = field(default_factory=list)
    recent_turns: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class RetrieveCandidatesInput:
    query: str = ""
    limit: int = 100
    exclude_seen_items: bool = True
    constraints: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class RetrieveCandidatesOutput:
    candidate_item_ids: list[str] = field(default_factory=list)
    candidate_count: int = 0
    retrieval_summary: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class RankCandidatesInput:
    candidate_item_ids: list[str] = field(default_factory=list)
    return_top_k: int = 20
    ranking_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class RankCandidatesOutput:
    ranked_item_ids: list[str] = field(default_factory=list)
    ranked_item_count: int = 0
    ranking_summary: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class GetItemEvidenceInput:
    item_ids: list[str] = field(default_factory=list)
    max_evidence_per_item: int = 3

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class GetItemEvidenceOutput:
    evidence: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    item_count: int = 0
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class RecordUserFeedbackInput:
    feedback_text: str = ""
    action_type: str = ""
    item_id: str | None = None
    comment: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class RecordUserFeedbackOutput:
    applied: bool
    active_constraints: dict[str, Any] = field(default_factory=dict)
    feedback_event: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class BuildRecommendationSlateInput:
    include_items: bool = True
    max_items: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class BuildRecommendationSlateOutput:
    display: dict[str, Any] = field(default_factory=dict)
    item_count: int = 0
    diagnostics: dict[str, Any] = field(default_factory=dict)

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


@dataclass(frozen=True)
class RecallPathPlan:
    name: str
    limit: int = 50
    top_k: int | None = None
    query: str = ""
    rules: list[dict[str, Any]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    source_budgets: dict[str, int] = field(default_factory=dict)
    candidate_pool: list[str] = field(default_factory=list)
    reference_item_id: str | None = None
    similar_to_item_id: str | None = None
    target_item_id: str | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class AgenticRecallRequest:
    user_id: str
    session_id: str = ""
    target_pool_size: int = 100
    global_rules: dict[str, Any] = field(default_factory=dict)
    paths: list[RecallPathPlan] = field(default_factory=list)
    ranking_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class AgenticRecallCandidate:
    item_id: str
    acquisition_path: str
    source_rank: int
    source_score: float
    item_features: dict[str, Any] = field(default_factory=dict)
    matched_rules: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class AgenticRecallOutput:
    candidates: list[AgenticRecallCandidate] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "diagnostics": _jsonable(self.diagnostics),
        }


@dataclass(frozen=True)
class CandidateFeatureRow:
    user_id: str
    item_id: str
    session_id: str = ""
    acquisition_path: str = ""
    source_rank: int = 0
    source_score: float = 0.0
    item_features: dict[str, Any] = field(default_factory=dict)
    constraint_features: dict[str, Any] = field(default_factory=dict)
    target_conditioned_catalog_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class DeepFMRankRequest:
    user_id: str
    session_id: str = ""
    return_top_k: int = 20
    ranking_context: dict[str, Any] = field(default_factory=dict)
    candidates: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class DeepFMRankOutput:
    ranked_items: list[dict[str, Any]] = field(default_factory=list)
    feature_rows: list[CandidateFeatureRow] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ranked_items": _jsonable(self.ranked_items),
            "feature_rows": [row.to_dict() for row in self.feature_rows],
            "diagnostics": _jsonable(self.diagnostics),
        }


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


def agentic_recall_candidates(
    request: AgenticRecallRequest,
    catalog_items: CatalogItems,
    seen_item_ids: set[str] | list[str] | tuple[str, ...] | None = None,
) -> AgenticRecallOutput:
    items = _normalize_catalog_items(catalog_items)
    candidates: list[AgenticRecallCandidate] = []
    seen_output_ids: set[str] = set()
    path_diagnostics = []
    dedupe = bool(request.global_rules.get("dedupe_by_parent_asin", True))
    target_pool_size = max(1, int(request.target_pool_size or 100))
    paths = request.paths or [RecallPathPlan(name="constraint_catalog_search", limit=target_pool_size, top_k=target_pool_size)]

    for path in paths:
        if len(candidates) >= target_pool_size:
            break
        limit = max(1, int(path.limit or path.top_k or 20))
        top_k = max(1, int(path.top_k or limit))
        search_request = _product_search_request_from_recall_path(path, request.global_rules)
        search_output = catalog_constraint_search(
            search_request,
            items,
            seen_item_ids=seen_item_ids,
            min_results=0,
        )
        accepted = 0
        source_counts: dict[str, int] = {}
        for source_rank, item in enumerate(search_output.matched_items[:top_k], start=1):
            item_id = _item_id_field(item)
            if not item_id:
                continue
            dedupe_key = _dedupe_key(item) if dedupe else item_id
            if dedupe_key in seen_output_ids:
                continue
            source_key = _item_source_key(path, item)
            source_budget = path.source_budgets.get(source_key)
            if source_budget is not None and source_counts.get(source_key, 0) >= source_budget:
                continue
            passed, matched_rules, filter_reason = _passes_agentic_rules(item, request.global_rules, path.rules)
            if not passed:
                continue
            source_score = _source_score(search_output.match_reasons.get(item_id, []), source_rank)
            candidates.append(AgenticRecallCandidate(
                item_id=item_id,
                acquisition_path=path.name,
                source_rank=source_rank,
                source_score=source_score,
                item_features=_candidate_item_features(item, request.ranking_context),
                matched_rules=matched_rules,
                diagnostics={
                    "path_reason": path.reason,
                    "source": source_key,
                    "source_budget": source_budget,
                    "filter_reason": filter_reason,
                },
            ))
            seen_output_ids.add(dedupe_key)
            source_counts[source_key] = source_counts.get(source_key, 0) + 1
            accepted += 1
            if len(candidates) >= target_pool_size:
                break
        path_diagnostics.append({
            "path": path.name,
            "requested_limit": limit,
            "requested_top_k": top_k,
            "matched_count": len(search_output.matched_items),
            "accepted_count": accepted,
            "source_counts": dict(source_counts),
            "relaxation_level": search_output.diagnostics.get("relaxation_level"),
        })

    return AgenticRecallOutput(
        candidates=candidates,
        diagnostics={
            "target_pool_size": target_pool_size,
            "candidate_count": len(candidates),
            "path_count": len(paths),
            "paths": path_diagnostics,
        },
    )


def deepfm_rank_candidates(request: DeepFMRankRequest) -> DeepFMRankOutput:
    feature_rows = [_candidate_feature_row(request, candidate) for candidate in request.candidates]
    scored = []
    for row in feature_rows:
        score_features = _deepfm_fallback_score_features(row, request.ranking_context)
        deepfm_score = sum(score_features.values())
        scored.append((deepfm_score, row, score_features))
    scored.sort(key=lambda entry: (-entry[0], entry[1].source_rank, entry[1].item_id))
    return_top_k = max(1, int(request.return_top_k or 20))
    ranked_items = []
    for rank, (deepfm_score, row, score_features) in enumerate(scored[:return_top_k], start=1):
        ranked_items.append({
            "item_id": row.item_id,
            "rank": rank,
            "deepfm_score": round(deepfm_score, 6),
            "acquisition_path": row.acquisition_path,
            "source_rank": row.source_rank,
            "source_score": row.source_score,
            "score_features": {key: round(value, 6) for key, value in score_features.items()},
        })
    return DeepFMRankOutput(
        ranked_items=ranked_items,
        feature_rows=feature_rows,
        diagnostics={
            "ranker": "deepfm_contract_deterministic_fallback",
            "candidate_count": len(feature_rows),
            "return_top_k": return_top_k,
            "returned_count": len(ranked_items),
        },
    )


def build_target_conditioned_catalog_text(item: dict[str, Any], ranking_context: dict[str, Any] | None = None) -> str:
    context = ranking_context or {}
    intent = str(context.get("intent_type") or context.get("query") or "").strip()
    title = str(item.get("title_clean") or item.get("title") or _item_id_field(item)).strip()
    category = str(item.get("main_category") or item.get("category") or "").strip()
    brand = str(item.get("brand") or item.get("store") or "").strip()
    price = item.get("price")
    rating = item.get("rating") or item.get("average_rating")
    features = item.get("features") or item.get("features_text") or ""
    if isinstance(features, list):
        features_text = "; ".join(str(feature) for feature in features[:4])
    else:
        features_text = str(features)[:240]
    parts = [f"Product: {title}"]
    if category:
        parts.append(f"Category: {category}")
    if brand:
        parts.append(f"Brand: {brand}")
    if price not in (None, ""):
        parts.append(f"Price: {price}")
    if rating not in (None, ""):
        parts.append(f"Rating: {rating}")
    if features_text:
        parts.append(f"Catalog features: {features_text}")
    if intent:
        parts.append(f"Target fit: {intent}")
    return " | ".join(parts)


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


def _product_search_request_from_recall_path(path: RecallPathPlan, global_rules: dict[str, Any]) -> ProductSearchRequest:
    rules = [*_rules_from_global(global_rules), *path.rules]
    reference_item_id = path.reference_item_id or path.similar_to_item_id or path.target_item_id
    category = CategoryConstraint(same_as_reference=path.name in {"similar_item_search", "cheaper_alternative_search"} and bool(reference_item_id))
    price: PriceConstraint | None = None
    if path.name == "cheaper_alternative_search" and reference_item_id:
        rules.append({"field": "price", "op": "lt", "reference_field": "price"})
    for rule in rules:
        field_name = str(rule.get("field") or "")
        op = str(rule.get("op") or "")
        values = rule.get("values", []) or [rule.get("value")]
        clean_values = [str(value) for value in values if value not in (None, "")]
        if field_name == "category" and op in {"in", "eq"}:
            category = CategoryConstraint(categories=clean_values, same_as_reference=category.same_as_reference)
        if field_name == "price" and op in {"lte", "lt"}:
            price = PriceConstraint(max_price=_number(rule.get("value")))
        if field_name == "price" and op in {"gte", "gt"}:
            price = PriceConstraint(min_price=_number(rule.get("value")))
    return ProductSearchRequest(
        query=path.query,
        price=price,
        keywords=_keyword_constraint_from_rules(path.query, rules),
        category=category,
        limit=max(1, int(path.limit or path.top_k or 20)),
        candidate_pool=path.candidate_pool,
        reference_item_id=path.reference_item_id,
        similar_to_item_id=path.similar_to_item_id,
        target_item_id=path.target_item_id,
        exclude_seen_items=bool(global_rules.get("exclude_seen_items", False)),
        constraints=rules,
    )


def _rules_from_global(global_rules: dict[str, Any]) -> list[dict[str, Any]]:
    rules = []
    for rule in global_rules.get("must_satisfy", []) or []:
        if isinstance(rule, dict):
            rules.append(dict(rule))
    for rule in global_rules.get("must_not_satisfy", []) or []:
        if not isinstance(rule, dict):
            continue
        inverted = dict(rule)
        op = str(inverted.get("op") or "")
        if op in {"in", "eq"}:
            inverted["op"] = "not_in"
        elif op == "not_in":
            inverted["op"] = "in"
        rules.append(inverted)
    return rules


def _keyword_constraint_from_rules(query: str, rules: list[dict[str, Any]]) -> KeywordConstraint:
    keywords = query.split() if query else []
    required = []
    preferred = []
    disliked = []
    for rule in rules:
        if rule.get("field") != "keyword":
            continue
        values = [str(value) for value in (rule.get("values", []) or [rule.get("value")]) if value not in (None, "")]
        op = rule.get("op")
        if op in {"required", "contains_all"}:
            required.extend(values)
        elif op == "disliked":
            disliked.extend(values)
        else:
            preferred.extend(values)
    return KeywordConstraint(keywords=keywords, required=required, preferred=preferred, disliked=disliked)


def _passes_agentic_rules(item: dict[str, Any], global_rules: dict[str, Any], path_rules: list[dict[str, Any]]) -> tuple[bool, list[dict[str, Any]], str]:
    matched = []
    for rule in global_rules.get("must_satisfy", []) or []:
        if not isinstance(rule, dict):
            continue
        if not _item_satisfies_rule(item, rule):
            return False, matched, f"must_satisfy:{rule.get('field')}"
        matched.append(rule)
    for rule in global_rules.get("must_not_satisfy", []) or []:
        if not isinstance(rule, dict):
            continue
        if _item_satisfies_rule(item, rule):
            return False, matched, f"must_not_satisfy:{rule.get('field')}"
    for rule in path_rules:
        if isinstance(rule, dict) and _item_satisfies_rule(item, rule):
            matched.append(rule)
    return True, matched, ""


def _item_satisfies_rule(item: dict[str, Any], rule: dict[str, Any]) -> bool:
    field_name = str(rule.get("field") or "")
    op = str(rule.get("op") or "")
    if field_name == "keyword":
        text = _search_text(item)
        values = [str(value) for value in (rule.get("values", []) or [rule.get("value")]) if value not in (None, "")]
        if op in {"required", "contains_all"}:
            return all(_norm_text(value) in text for value in values)
        if op == "disliked":
            return any(_norm_text(value) in text for value in values)
        return any(_norm_text(value) in text for value in values)
    value = _rule_item_value(item, field_name)
    values = rule.get("values", []) or [rule.get("value")]
    if op in {"in", "eq"}:
        return _norm_text(value) in {_norm_text(candidate) for candidate in values}
    if op == "not_in":
        return _norm_text(value) not in {_norm_text(candidate) for candidate in values}
    number = _number(value)
    expected = _number(rule.get("value"))
    if number is None or expected is None:
        return False
    if op == "lte":
        return number <= expected
    if op == "lt":
        return number < expected
    if op == "gte":
        return number >= expected
    if op == "gt":
        return number > expected
    return False


def _rule_item_value(item: dict[str, Any], field_name: str) -> Any:
    if field_name == "category":
        return item.get("main_category") or item.get("category")
    if field_name == "brand":
        return item.get("brand") or item.get("store")
    if field_name in {"rating", "average_rating"}:
        return item.get("rating") or item.get("average_rating")
    return item.get(field_name)


def _source_score(reasons: list[CatalogMatchReason], source_rank: int) -> float:
    reason_score = sum(float(reason.score or 0.0) for reason in reasons)
    return max(reason_score, 1.0 / max(source_rank, 1))


def _dedupe_key(item: dict[str, Any]) -> str:
    return str(item.get("parent_asin") or item.get("item_id") or item.get("asin") or "")


def _item_source_key(path: RecallPathPlan, item: dict[str, Any]) -> str:
    sources = item.get("sources") if isinstance(item.get("sources"), list) else []
    if sources:
        return str(sources[0])
    if path.sources:
        return str(path.sources[0])
    return path.name


def _candidate_item_features(item: dict[str, Any], ranking_context: dict[str, Any] | None = None) -> dict[str, Any]:
    feature_keys = (
        "parent_asin",
        "item_id",
        "title_clean",
        "title",
        "main_category",
        "category",
        "brand",
        "store",
        "price",
        "rating",
        "average_rating",
        "rating_number",
        "features",
        "features_text",
        "description",
        "description_text",
    )
    features = {key: item[key] for key in feature_keys if item.get(key) not in (None, "", [])}
    features["target_conditioned_catalog_text"] = build_target_conditioned_catalog_text(item, ranking_context)
    return features


def _candidate_feature_row(request: DeepFMRankRequest, candidate: dict[str, Any]) -> CandidateFeatureRow:
    item_features = candidate.get("item_features") if isinstance(candidate.get("item_features"), dict) else {}
    item_id = str(candidate.get("item_id") or item_features.get("parent_asin") or item_features.get("item_id") or "")
    constraint_features = candidate.get("constraint_features") if isinstance(candidate.get("constraint_features"), dict) else {}
    if not constraint_features:
        constraint_features = {
            "hard_constraints_satisfied": True,
            "constraint_satisfaction_score": 1.0 if candidate.get("matched_rules") else 0.5,
        }
    target_text = str(item_features.get("target_conditioned_catalog_text") or build_target_conditioned_catalog_text(item_features, request.ranking_context))
    return CandidateFeatureRow(
        user_id=request.user_id,
        item_id=item_id,
        session_id=request.session_id,
        acquisition_path=str(candidate.get("acquisition_path") or ""),
        source_rank=int(candidate.get("source_rank") or 0),
        source_score=float(candidate.get("source_score") or 0.0),
        item_features=item_features,
        constraint_features=constraint_features,
        target_conditioned_catalog_text=target_text,
    )


def _deepfm_fallback_score_features(row: CandidateFeatureRow, ranking_context: dict[str, Any]) -> dict[str, float]:
    rating = _number(row.item_features.get("rating") or row.item_features.get("average_rating")) or 0.0
    source_rank_score = 1.0 / max(row.source_rank or 1, 1)
    constraint_score = _number(row.constraint_features.get("constraint_satisfaction_score")) or 0.0
    keyword_score = _target_keyword_match_score(row.target_conditioned_catalog_text, ranking_context)
    return {
        "source_score": min(max(row.source_score, 0.0), 10.0) * 0.2,
        "source_rank": source_rank_score,
        "constraint": constraint_score,
        "quality": min(max(rating / 5.0, 0.0), 1.0),
        "target_text_match": keyword_score,
    }


def _target_keyword_match_score(text: str, ranking_context: dict[str, Any]) -> float:
    tokens = []
    for value in ranking_context.values():
        if isinstance(value, str):
            tokens.extend(value.split())
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    tokens.extend(str(part) for part in item.get("values", []) or [item.get("value", "")])
                else:
                    tokens.append(str(item))
    normalized_text = _norm_text(text)
    unique_tokens = [token for token in dict.fromkeys(_norm_text(token) for token in tokens) if len(token) > 2]
    if not unique_tokens:
        return 0.0
    matches = sum(1 for token in unique_tokens if token in normalized_text)
    return min(matches / len(unique_tokens), 1.0)


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
        name="get_user_context",
        stage="context",
        description="Summarize the active user/session context for recommendation planning.",
        input_schema_name="GetUserContextInput",
        output_schema_name="GetUserContextOutput",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        allowed_intents=DIALOGUE_PLAN_INTENTS,
    ),
    AgentToolSpec(
        name="retrieve_candidates",
        stage="candidate_generation",
        description="Retrieve a bounded candidate set for the current recommendation need.",
        input_schema_name="RetrieveCandidatesInput",
        output_schema_name="RetrieveCandidatesOutput",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        allowed_intents=frozenset({INTENT_RECOMMEND_REQUEST, INTENT_PREFERENCE_FEEDBACK, INTENT_CLARIFICATION_ANSWER}),
        can_search_catalog=True,
    ),
    AgentToolSpec(
        name="rank_candidates",
        stage="ranking",
        description="Rank retrieved candidates for the current user turn.",
        input_schema_name="RankCandidatesInput",
        output_schema_name="RankCandidatesOutput",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        allowed_intents=frozenset({INTENT_RECOMMEND_REQUEST, INTENT_PREFERENCE_FEEDBACK, INTENT_CLARIFICATION_ANSWER}),
        requires_candidate_pool=True,
    ),
    AgentToolSpec(
        name="get_item_evidence",
        stage="evidence",
        description="Build grounded item evidence for internal recommendation reasoning.",
        input_schema_name="GetItemEvidenceInput",
        output_schema_name="GetItemEvidenceOutput",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        allowed_intents=frozenset({INTENT_RECOMMEND_REQUEST, INTENT_PREFERENCE_FEEDBACK, INTENT_ASK_EXPLANATION}),
        requires_candidate_pool=True,
        uses_reference_item=True,
        uses_rag_evidence=True,
    ),
    AgentToolSpec(
        name="record_user_feedback",
        stage="feedback",
        description="Record explicit user feedback into the active session constraints.",
        input_schema_name="RecordUserFeedbackInput",
        output_schema_name="RecordUserFeedbackOutput",
        read_only=False,
        hidden=True,
        public_payload_allowed=False,
        allowed_intents=frozenset({INTENT_PREFERENCE_FEEDBACK, INTENT_CLARIFICATION_ANSWER, INTENT_ASK_EXPLANATION}),
    ),
    AgentToolSpec(
        name="build_recommendation_slate",
        stage="response_composition",
        description="Build the display-safe recommendation slate for the current turn.",
        input_schema_name="BuildRecommendationSlateInput",
        output_schema_name="BuildRecommendationSlateOutput",
        read_only=True,
        hidden=True,
        public_payload_allowed=True,
        allowed_intents=DIALOGUE_PLAN_INTENTS,
        requires_candidate_pool=True,
        uses_rag_evidence=True,
    ),
)

AGENT_CAPABILITY_MANIFEST = (
    AgentCapability(
        name="get_user_context",
        stage="context",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        description="Summarize the active user/session context for recommendation planning.",
    ),
    AgentCapability(
        name="retrieve_candidates",
        stage="candidate_generation",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        description="Retrieve candidate items from configured recommendation inputs.",
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
        name="get_item_evidence",
        stage="evidence",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        description="Build grounded product evidence for internal explanation support.",
    ),
    AgentCapability(
        name="record_user_feedback",
        stage="feedback",
        read_only=False,
        hidden=True,
        public_payload_allowed=False,
        description="Collect explicit user feedback for the active session state.",
    ),
    AgentCapability(
        name="build_recommendation_slate",
        stage="response_composition",
        read_only=True,
        hidden=True,
        public_payload_allowed=True,
        description="Prepare a display-safe recommendation slate from selected items.",
    ),
)

def get_agent_tool_spec(name: str) -> AgentToolSpec | None:
    normalized = str(name or "").strip()
    return next((tool for tool in AGENT_TOOL_MANIFEST if tool.name == normalized), None)


def normalize_agent_tool_calls(value: Any) -> list[AgentToolCall]:
    if value in (None, ""):
        return []
    if isinstance(value, AgentToolCall):
        return [value]
    if isinstance(value, str):
        return [AgentToolCall(name=value.strip())] if value.strip() else []
    if isinstance(value, list | tuple):
        calls: list[AgentToolCall] = []
        for item in value:
            calls.extend(normalize_agent_tool_calls(item))
        return calls
    if isinstance(value, dict):
        if "tool_calls" in value:
            return normalize_agent_tool_calls(value.get("tool_calls"))
        if "requested_tools" in value:
            return normalize_agent_tool_calls(value.get("requested_tools"))
        name = str(value.get("name") or value.get("tool") or value.get("tool_name") or "").strip()
        if not name:
            return []
        arguments = value.get("arguments") if isinstance(value.get("arguments"), dict) else value.get("args")
        return [AgentToolCall(
            name=name,
            arguments=dict(arguments) if isinstance(arguments, dict) else {},
            phase=str(value.get("phase") or "").strip(),
            call_id=str(value.get("call_id") or value.get("id") or "").strip(),
        )]
    return []


def validate_agent_tool_call(call: AgentToolCall, intent: str, phase: str) -> str | None:
    spec = get_agent_tool_spec(call.name)
    if spec is None:
        return "unknown_tool"
    if intent not in spec.allowed_intents:
        return "intent_not_allowed"
    if call.phase and call.phase != phase:
        return "phase_not_requested"
    if phase == "pre_recommendation" and spec.requires_candidate_pool:
        return "candidate_pool_not_available"
    return None


TOOL_EVENT_KEYS = ("constraint_filter_events", "feedback_rerank_events", "agent_tool_events")


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
