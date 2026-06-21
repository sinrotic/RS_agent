from __future__ import annotations

import json
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
    routing_attributes: dict[str, Any] = field(default_factory=dict)
    boundary_prompt: str = ""

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
class AgentToolInputValidation:
    valid: bool
    reason: str = ""
    normalized_arguments: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


RANK_CANDIDATES_ALLOWED_ARGUMENTS = frozenset({"candidate_item_ids", "candidates", "return_top_k", "ranking_context"})
RANK_CANDIDATES_MAX_RETURN_TOP_K = 500


def validate_rank_candidates_arguments(arguments: dict[str, Any] | None) -> AgentToolInputValidation:
    raw_arguments = {} if arguments is None else arguments
    if not isinstance(raw_arguments, dict):
        return _invalid_rank_candidates_input("invalid_rank_candidates_arguments_type", {})

    unknown_fields = sorted(set(raw_arguments) - set(RANK_CANDIDATES_ALLOWED_ARGUMENTS))
    if unknown_fields:
        return _invalid_rank_candidates_input("invalid_rank_candidates_arguments_unknown_fields", {"unknown_fields": unknown_fields})

    normalized: dict[str, Any] = {"return_top_k": 20}
    if "return_top_k" in raw_arguments:
        parsed_top_k = _parse_rank_candidates_return_top_k(raw_arguments.get("return_top_k"))
        if isinstance(parsed_top_k, str):
            return _invalid_rank_candidates_input(parsed_top_k, {})
        normalized["return_top_k"] = parsed_top_k

    if "candidate_item_ids" in raw_arguments:
        value = raw_arguments.get("candidate_item_ids")
        if not isinstance(value, list | tuple | set):
            return _invalid_rank_candidates_input("invalid_rank_candidates_candidate_item_ids_type", {})
        normalized["candidate_item_ids"] = _dedupe_non_empty_strings(value)

    if "candidates" in raw_arguments:
        value = raw_arguments.get("candidates")
        if not isinstance(value, list):
            return _invalid_rank_candidates_input("invalid_rank_candidates_candidates_type", {})
        candidates: list[dict[str, Any]] = []
        for candidate in value:
            if not isinstance(candidate, dict):
                return _invalid_rank_candidates_input("invalid_rank_candidates_candidate_entry_type", {})
            item_features = candidate.get("item_features") if isinstance(candidate.get("item_features"), dict) else {}
            if not (candidate.get("item_id") or candidate.get("parent_asin") or candidate.get("asin") or item_features.get("item_id") or item_features.get("parent_asin")):
                return _invalid_rank_candidates_input("invalid_rank_candidates_candidate_entry_type", {})
            candidates.append(dict(candidate))
        normalized["candidates"] = candidates

    if "ranking_context" in raw_arguments:
        value = raw_arguments.get("ranking_context")
        if not isinstance(value, dict):
            return _invalid_rank_candidates_input("invalid_rank_candidates_ranking_context_type", {})
        normalized["ranking_context"] = dict(value)

    return AgentToolInputValidation(
        valid=True,
        normalized_arguments=normalized,
        diagnostics=_rank_candidates_input_diagnostics(),
    )


def _parse_rank_candidates_return_top_k(value: Any) -> int | str:
    if isinstance(value, bool) or isinstance(value, float):
        return "invalid_rank_candidates_return_top_k_type"
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        return "invalid_rank_candidates_return_top_k_type"
    if parsed <= 0 or parsed > RANK_CANDIDATES_MAX_RETURN_TOP_K:
        return "invalid_rank_candidates_return_top_k_range"
    return parsed


def _dedupe_non_empty_strings(values: list[Any] | tuple[Any, ...] | set[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item_id = str(value or "").strip()
        if item_id and item_id not in seen:
            seen.add(item_id)
            normalized.append(item_id)
    return normalized


def _invalid_rank_candidates_input(reason: str, extra_diagnostics: dict[str, Any]) -> AgentToolInputValidation:
    return AgentToolInputValidation(
        valid=False,
        reason=reason,
        diagnostics={**_rank_candidates_input_diagnostics(), **extra_diagnostics},
    )


def _rank_candidates_input_diagnostics() -> dict[str, Any]:
    return {"compact": True, "internal_only": True, "public_payload_allowed": False}


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
class QueryRagInput:
    query: str = ""
    purpose: str = "query_planning"
    scope: str = "catalog_knowledge"
    fields: list[str] = field(default_factory=list)
    max_evidence_total: int = 8
    max_text_chars: int = 220

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class QueryRagOutput:
    query: str = ""
    query_rewrite: str = ""
    semantic_query_hint: str = ""
    suggested_query_terms: list[str] = field(default_factory=list)
    retrieval_hints: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class RecallIntent:
    intent_type: str = "recommend_request"
    scenario: str = ""
    need_specificity: str = "auto"
    reference_item_id: str | None = None
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class RecallProfilePolicy:
    use_current_query: bool = True
    use_recent_history: bool = True
    history_weight: str = "balanced"

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class RecallRoutePolicy:
    semantic: str = "auto"
    similar_item: str = "auto"
    user_neighbor: str = "auto"
    behavioral: str = "auto"
    fallback: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class RecallConstraints:
    preferred_categories: list[str] = field(default_factory=list)
    disliked_categories: list[str] = field(default_factory=list)
    preferred_keywords: list[str] = field(default_factory=list)
    disliked_keywords: list[str] = field(default_factory=list)
    preferred_brands: list[str] = field(default_factory=list)
    disliked_brands: list[str] = field(default_factory=list)
    price_min: float | None = None
    price_max: float | None = None
    exclude_seen_items: bool = True
    exclude_prior_turn_items: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class RecallDiversityPolicy:
    dedupe_by_parent_asin: bool = True
    source_balance: str = "auto"
    max_per_source: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class RecallRouteDecision:
    route: str
    status: str
    reason: str = ""
    eligible: bool = False
    returned_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class RecallRetrievalSummary:
    schema_version: str = "retrieve_candidates_output_v3"
    target_pool_size: int | None = None
    returned_count: int = 0
    underfill: bool = False
    route_count: int = 0
    path_count: int | None = None
    retrieval_mode: str = "auto"
    profile_usage: str = "balanced"
    expansion_policy: str = "balanced"

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class RetrieveCandidatesInput:
    query: str = ""
    target_pool_size: int = 500
    retrieval_mode: str = "auto"
    profile_usage: str = "balanced"
    expansion_policy: str = "balanced"
    reference_item_id: str | None = None
    intent: RecallIntent = field(default_factory=RecallIntent)
    profile_policy: RecallProfilePolicy = field(default_factory=RecallProfilePolicy)
    route_policy: RecallRoutePolicy = field(default_factory=RecallRoutePolicy)
    constraints: RecallConstraints | dict[str, Any] = field(default_factory=RecallConstraints)
    diversity: RecallDiversityPolicy = field(default_factory=RecallDiversityPolicy)
    # Backward-compatible aliases used by the current deterministic planner.
    limit: int = 100
    exclude_seen_items: bool = True
    semantic_mode: str = "auto"
    use_history_profile: bool = True
    use_behavioral_recall: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class RetrieveCandidatesOutput:
    candidate_item_ids: list[str] = field(default_factory=list)
    candidate_count: int = 0
    retrieval_summary: RecallRetrievalSummary | dict[str, Any] = field(default_factory=RecallRetrievalSummary)
    route_decisions: list[RecallRouteDecision] = field(default_factory=list)
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

RETRIEVE_CANDIDATES_ROUTING_ATTRIBUTES = {
    "llm_visible_policy": {
        "retrieval_mode": ["auto", "specific_need", "personalized_feed", "broad_browse", "similar_to_item", "reference_with_constraints"],
        "profile_usage": ["none", "light", "balanced", "strong"],
        "expansion_policy": ["none", "narrow", "balanced", "broad"],
        "reference_item_id": "Optional item id that means 'like this item' for reference-aware requests.",
        "query": "Natural-language need or extra constraints; can be combined with reference_item_id.",
        "constraints": "Business constraints such as category, keyword, price, brand, or exclusions.",
        "target_pool_size": "Bounded candidate pool size requested by the planner.",
    },
    "business_modes": {
        "auto": "Backend infers a safe blend from query, history, reference item, and constraints.",
        "specific_need": "Use the current natural-language need as the primary acquisition intent.",
        "personalized_feed": "Use user profile and history for a personalized feed when the request is broad.",
        "broad_browse": "Explore broadly with light personalization for empty or generic requests.",
        "similar_to_item": "Find items like reference_item_id; query may describe how they should be similar.",
        "reference_with_constraints": "Find alternatives related to reference_item_id while honoring query or constraints.",
    },
    "backend_mapping": "The server maps business modes to semantic, traditional, reference-aware, and fallback providers; the planner must not select provider names.",
    "semantic_participation": "reference_item_id can seed semantic text and query can describe how/why items should be similar.",
    "public_output": "candidate_ids_only_no_scores_no_diagnostics_no_lineage",
    "internal_output": "business_route_decisions_allowed_without_scores_or_lineage",
}

QUERY_RAG_ROUTING_ATTRIBUTES = {
    "available_phase": "pre_recommendation",
    "candidate_pool_required": False,
    "uses": [
        "query_planning",
        "attribute_expansion",
        "concept_completion",
        "scenario_terms",
        "synonym_expansion",
        "category_knowledge",
        "query_rewrite_support",
        "clarification_grounding",
    ],
    "public_output": "compact_hints_only_no_raw_evidence_no_scores_no_lineage",
}

QUERY_RAG_BOUNDARY_PROMPT = (
    "Use query_rag only as an internal pre-retrieval catalog-knowledge helper when the user request is scenario-based, ambiguous, attribute-heavy, or expressed in natural shopping language. "
    "Use it for concept completion, attribute expansion, scenario terms, synonym coverage, category knowledge, and query rewrite support. "
    "Use its compact hints to improve retrieve_candidates.query or decide whether a clarification would materially improve the result; never use query_rag as a replacement for retrieve_candidates or rank_candidates. "
    "Do not use query_rag for candidate selection, ranking, or public evidence, and do not expose raw snippets, scores, labels, oracle fields, source paths, traces, or RAG diagnostics to the public response."
)

RETRIEVE_CANDIDATES_BOUNDARY_PROMPT = (
    "Use retrieve_candidates only as a high-level candidate acquisition tool. "
    "The planner should express the business mode through retrieval_mode, profile_usage, expansion_policy, reference_item_id, query, constraints, and target_pool_size. "
    "Use specific_need for concrete natural-language needs, personalized_feed or broad_browse for broad requests, similar_to_item when reference_item_id means 'like this item', and reference_with_constraints when query or constraints describe how the alternatives should differ. "
    "reference_item_id means '像谁'; query means '怎么像/额外约束', so reference-aware requests can still use semantic acquisition. "
    "semantic_live is available to every user, but the planner should choose the business retrieval mode rather than low-level semantic/provider switches. "
    "Backend eligibility maps these business fields to semantic, traditional, reference-aware, and fallback providers; do not choose provider names, source files, indexes, scores, or lineage. "
    "Return bounded candidate ids and compact internal business route_decisions for debugging only, never public scores, diagnostics, labels, oracle fields, trace, or recall lineage."
)

GET_ITEM_EVIDENCE_BOUNDARY_PROMPT = (
    "Use get_item_evidence after retrieval and ranking to ground explanations and recommendation support for ranked candidate items only. "
    "It must not add new candidates, change ranking, perform query expansion, or expose raw RAG/source diagnostics to the public response."
)

AGENT_TOOL_BOUNDARY_SYSTEM_PROMPT = (
    "You are a recommendation agent using a small set of hidden business tools. "
    "The user should experience natural shopping dialogue, not low-level tool orchestration. "
    "Call get_user_context before recommendation planning; optionally call query_rag before retrieve_candidates when catalog knowledge can improve query planning, "
    "concept completion, attribute expansion, scenario or synonym coverage, category knowledge, or query rewrite planning. "
    "Call retrieve_candidates for candidate acquisition and rank_candidates for ordering; query_rag must not replace either tool. "
    "After candidates are ranked, call get_item_evidence only to ground recommendation support for ranked candidate items; it must not add new candidates, must not change ranking, or expose raw RAG/source diagnostics. "
    "Ask a clarifying question before retrieval only when missing information blocks safe candidate acquisition; otherwise use available context, optional query_rag, retrieve_candidates, and rank_candidates first, then provide grouped recommendations or one high-value follow-up clarification after the slate. "
    "Record_user_feedback only for explicit feedback, and build_recommendation_slate for display-safe output. "
    "For retrieve_candidates, choose retrieval_mode/profile_usage/expansion_policy plus optional reference_item_id, query, constraints, and target_pool_size; do not expose or steer low-level provider policies. "
    "reference_item_id means the item to be like, while query describes how it should be similar or what extra constraints apply; semantic acquisition may participate even for reference-aware modes. "
    "Concrete recall providers are backend implementation details guarded by user history and serving indexes. "
    "Do not reveal source scores, method lineage, diagnostics, labels, oracle fields, training artifacts, or tool traces to the public response."
)


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
        name="query_rag",
        stage="query_planning",
        description="Retrieve compact catalog knowledge hints for internal recommendation query planning.",
        input_schema_name="QueryRagInput",
        output_schema_name="QueryRagOutput",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        allowed_intents=frozenset({INTENT_RECOMMEND_REQUEST, INTENT_PREFERENCE_FEEDBACK, INTENT_CLARIFICATION_ANSWER}),
        can_search_catalog=True,
        uses_rag_evidence=True,
        routing_attributes=QUERY_RAG_ROUTING_ATTRIBUTES,
        boundary_prompt=QUERY_RAG_BOUNDARY_PROMPT,
    ),
    AgentToolSpec(
        name="retrieve_candidates",
        stage="candidate_generation",
        description="Retrieve a bounded candidate set from a business retrieval mode, optional profile usage, expansion policy, reference item, query, and constraints.",
        input_schema_name="RetrieveCandidatesInput",
        output_schema_name="RetrieveCandidatesOutput",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        allowed_intents=frozenset({INTENT_RECOMMEND_REQUEST, INTENT_PREFERENCE_FEEDBACK, INTENT_CLARIFICATION_ANSWER}),
        can_search_catalog=True,
        routing_attributes=RETRIEVE_CANDIDATES_ROUTING_ATTRIBUTES,
        boundary_prompt=RETRIEVE_CANDIDATES_BOUNDARY_PROMPT,
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
        boundary_prompt=GET_ITEM_EVIDENCE_BOUNDARY_PROMPT,
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



def build_agent_tool_planner_system_prompt() -> str:
    """Build the hidden tool-planner system prompt contract for future LLM planners."""
    tool_contracts = []
    for tool in AGENT_TOOL_MANIFEST:
        if not tool.hidden:
            continue
        summary: dict[str, Any] = {
            "name": tool.name,
            "stage": tool.stage,
            "description": tool.description,
            "read_only": tool.read_only,
            "public_payload_allowed": tool.public_payload_allowed,
            "allowed_intents": sorted(tool.allowed_intents),
        }
        if tool.requires_candidate_pool:
            summary["requires_candidate_pool"] = True
        if tool.can_search_catalog:
            summary["can_search_catalog"] = True
        if tool.uses_rag_evidence:
            summary["uses_rag_evidence"] = True
        if tool.routing_attributes:
            summary["routing_attributes"] = _jsonable(tool.routing_attributes)
        if tool.boundary_prompt:
            summary["boundary_prompt"] = tool.boundary_prompt
        tool_contracts.append(summary)
    return "\n".join([
        AGENT_TOOL_BOUNDARY_SYSTEM_PROMPT,
        "Hidden tool manifest summary:",
        json.dumps(tool_contracts, ensure_ascii=False, sort_keys=True),
    ])


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
        name="query_rag",
        stage="query_planning",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        description="Retrieve compact catalog knowledge hints for internal recommendation planning.",
    ),
    AgentCapability(
        name="retrieve_candidates",
        stage="candidate_generation",
        read_only=True,
        hidden=True,
        public_payload_allowed=False,
        description="Retrieve candidate items through a business retrieval mode with optional profile, expansion, reference, query, and constraints.",
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
