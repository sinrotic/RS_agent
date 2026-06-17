from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from rs_core.common.io import read_json
from rs_core.display.builder import item_to_display_card, validate_public_display_payload
from rs_core.recsys.candidate_merge import (
    load_usercf_recall_sidecar,
    merge_candidates,
    metadata_neighbor_candidates_for_user,
    usercf_candidates_for_user,
)
from rs_core.recsys.pool500_artifacts import Pool500ArtifactIndex, load_pool500_artifact_index
from rs_core.recsys.types import MergedCandidate, RecallCandidate
from rs_core.rsagent.policy import normalize_feedback_input, parse_feedback
from rs_core.rsagent.schema import DisplayResponse
from rs_core.workflow.hybrid_demo import recommend_for_user
from rs_core.workflow.hybrid_environment import HybridRecommendationEnvironment


@dataclass
class OnlineRecommendationResult:
    request_id: str
    display: dict[str, Any]
    items: list[dict[str, Any]]
    candidate_count: int
    fallback_used: bool
    diagnostics: dict[str, Any]


class OnlinePool500Recommender:
    def __init__(self, env: HybridRecommendationEnvironment) -> None:
        self.env = env
        self._pool500_index: Pool500ArtifactIndex | None = None
        self._pool500_index_error: str | None = None
        self._usercf_lookup: dict[str, list[RecallCandidate]] | None = None
        self._usercf_lookup_error: str | None = None
        self._co_visit_lookup: dict[str, list[RecallCandidate]] | None = None
        self._co_visit_lookup_error: str | None = None

    @classmethod
    def from_environment(cls, env: HybridRecommendationEnvironment) -> OnlinePool500Recommender:
        return cls(env)

    def readiness(self) -> dict[str, Any]:
        path = _pool500_candidates_path(self.env.config, self.env.config_path)
        source_indexes = self._source_index_readiness()
        source_index_available = any(status.get("available") for status in source_indexes.values())
        payload: dict[str, Any] = {
            "mode": "online-service" if path or source_indexes else "demo-compatible",
            "config_path": self.env.config_path,
            "session_state": "single_process_in_memory",
            "complete_pool500_available": bool(path or source_index_available),
            "online_source_indexes": source_indexes,
        }
        if not path:
            payload["pool500_artifact"] = {"enabled": False, "status": "not_configured"}
            return payload
        try:
            payload["pool500_artifact"] = self._get_pool500_index().readiness()
        except Exception as exc:  # pragma: no cover - defensive readiness path
            payload["complete_pool500_available"] = source_index_available
            payload["pool500_artifact"] = {"enabled": True, "status": "error", "candidates_path": str(path), "error": str(exc)}
        return payload

    def recommend(
        self,
        user_sequence: dict[str, Any],
        *,
        user_id: str | None = None,
        feedback_text: str | None = None,
        top_k: int = 5,
        candidate_pool_size: int | None = None,
        complete_pool500: bool = False,
    ) -> OnlineRecommendationResult:
        request_id = str(uuid4())
        normalized_sequence = _normalize_sequence(user_sequence, user_id)
        config = _request_config(self.env.config, top_k=top_k, candidate_pool_size=candidate_pool_size)
        feedback_constraints = parse_feedback(normalize_feedback_input(feedback_text)) if feedback_text else None
        extra_candidates: list[MergedCandidate] = []
        route_diagnostics: dict[str, Any] = {"route": "demo_compatible", "complete_pool500": bool(complete_pool500)}
        if complete_pool500:
            artifact_candidates, artifact_diagnostics = self._artifact_candidates_for_sequence(normalized_sequence)
            source_index_candidates, source_index_diagnostics = self._source_index_candidates_for_sequence(normalized_sequence, config)
            extra_candidates = _merge_online_extra_candidates([*artifact_candidates, *source_index_candidates])
            route_diagnostics = {
                "route": "online_recall_with_source_indexes",
                "complete_pool500": True,
                **artifact_diagnostics,
                "source_index_candidate_count": len(source_index_candidates),
                "source_index_coverage": _candidate_source_coverage(source_index_candidates),
                "online_source_indexes": source_index_diagnostics,
                "fallback_reason": "missing_user_in_online_recall" if not extra_candidates else None,
            }
        result = recommend_for_user(
            normalized_sequence,
            self.env.popular,
            self.env.itemcf_weak,
            self.env.itemcf_strong,
            self.env.category_top,
            self.env.item_category,
            config,
            semantic_index=self.env.semantic_index,
            feedback_constraints=feedback_constraints,
            inference_client=self.env.inference_client,
            turn_index=1,
            extra_candidates=extra_candidates,
        )
        final_items = self.env.enrich_display_items(result.decision.final_items)
        cards = [card for item in final_items if (card := item_to_display_card(item))]
        items = [card.to_dict() for card in cards]
        display = validate_public_display_payload(DisplayResponse(
            session_id=request_id,
            user_id=normalized_sequence["user_id"],
            turn_index=1,
            assistant_message=_public_assistant_message(items),
            items=cards,
            feedback_actions=[],
            ui_state={
                "image_fallback_enabled": True,
                "can_request_more": True,
            },
        ).to_dict())
        fallback_used = result.fallback_used or bool(route_diagnostics.get("fallback_reason"))
        return OnlineRecommendationResult(
            request_id=request_id,
            display=display,
            items=items,
            candidate_count=len(result.candidates),
            fallback_used=fallback_used,
            diagnostics={"online_route": route_diagnostics, "source_coverage": result.diagnostics.get("source_coverage", {})},
        )

    def tool_retrieve_candidates(
        self,
        user_sequence: dict[str, Any],
        *,
        prior_turn_items: set[str] | None = None,
        candidate_pool_size: int | None = None,
    ) -> dict[str, Any]:
        index = self._maybe_pool500_index()
        normalized_sequence = _normalize_sequence(user_sequence, user_sequence.get("user_id"))
        if index is None:
            return {"candidate_item_ids": [], "candidate_count": 0, "diagnostics": {"route": "demo_compatible", "pool500_artifact_enabled": False}}
        candidates = index.candidates_for_user(normalized_sequence["user_id"], seen_items=(prior_turn_items or set()) | set(normalized_sequence.get("recent_item_sequence", [])))
        if candidate_pool_size is not None:
            candidates = candidates[: int(candidate_pool_size)]
        return {
            "candidate_item_ids": [candidate.item_id for candidate in candidates],
            "candidate_count": len(candidates),
            "retrieval_summary": {
                "target_pool_size": candidate_pool_size,
                "path_count": len(index.source_counts),
            },
            "diagnostics": {"compact": True, "route": "pool500_artifact_online"},
        }

    def tool_rank_candidates(self, turn: Any | None, *, return_top_k: int | None = None) -> dict[str, Any]:
        ranked_items = list(getattr(turn, "ranking", []) or [])
        if return_top_k is not None:
            ranked_items = ranked_items[: int(return_top_k)]
        return {
            "ranked_item_ids": [str(item.get("parent_asin") or item.get("item_id")) for item in ranked_items if item.get("parent_asin") or item.get("item_id")],
            "ranked_item_count": len(ranked_items),
            "ranking_summary": {
                "ranker": "online_route_facade",
                "candidate_count": len(getattr(turn, "candidates", []) or []),
                "return_top_k": return_top_k,
            },
            "diagnostics": {"compact": True, "route": "online_route_facade"},
        }

    def _get_pool500_index(self) -> Pool500ArtifactIndex:
        if self._pool500_index is not None:
            return self._pool500_index
        path = _pool500_candidates_path(self.env.config, self.env.config_path)
        if path is None:
            raise ValueError("complete_pool500 requires pool500_candidates_path in serving config")
        try:
            self._pool500_index = load_pool500_artifact_index(path, allowed_sources=_allowed_pool500_sources(self.env.config))
            self._pool500_index_error = None
        except Exception as exc:
            self._pool500_index_error = str(exc)
            raise
        return self._pool500_index

    def _maybe_pool500_index(self) -> Pool500ArtifactIndex | None:
        path = _pool500_candidates_path(self.env.config, self.env.config_path)
        if path is None:
            return None
        return self._get_pool500_index()

    def _artifact_candidates_for_sequence(self, user_sequence: dict[str, Any]) -> tuple[list[MergedCandidate], dict[str, Any]]:
        index = self._maybe_pool500_index()
        if index is None:
            raise ValueError("complete_pool500 requires pool500_candidates_path in serving config")
        seen_items = set(user_sequence.get("recent_item_sequence", []))
        candidates = index.candidates_for_user(str(user_sequence.get("user_id") or ""), seen_items=seen_items)
        return candidates, {
            "artifact_candidate_count": len(candidates),
            "artifact_source_coverage": _candidate_source_coverage(candidates),
            "pool500_artifact_enabled": True,
        }

    def _source_index_readiness(self) -> dict[str, dict[str, Any]]:
        return {}

    def _source_index_candidates_for_sequence(self, user_sequence: dict[str, Any], config: dict[str, Any]) -> tuple[list[MergedCandidate], dict[str, Any]]:
        return [], {}


def _normalize_sequence(user_sequence: dict[str, Any], user_id: str | None) -> dict[str, Any]:
    sequence = dict(user_sequence)
    resolved_user_id = str(user_id or sequence.get("user_id") or f"online-{uuid4()}")
    sequence["user_id"] = resolved_user_id
    for key in ("recent_item_sequence", "recent_positive_item_sequence", "recent_strong_positive_item_sequence"):
        value = sequence.get(key)
        if value is None:
            sequence[key] = []
        elif isinstance(value, list):
            sequence[key] = [str(item) for item in value if item not in (None, "")]
        else:
            raise ValueError(f"user_sequence.{key} must be a list when provided")
    return sequence


def _request_config(config: dict[str, Any], *, top_k: int, candidate_pool_size: int | None) -> dict[str, Any]:
    request_config = dict(config)
    request_config["top_k"] = int(top_k)
    if candidate_pool_size is not None:
        request_config["candidate_pool_size"] = int(candidate_pool_size)
    return request_config


def _pool500_candidates_path(config: dict[str, Any], config_path: str | Path) -> Path | None:
    route = config.get("online_route") if isinstance(config.get("online_route"), dict) else {}
    artifact = config.get("pool500_artifact") if isinstance(config.get("pool500_artifact"), dict) else {}
    raw_path = route.get("pool500_candidates_path") or artifact.get("candidates_path") or config.get("pool500_candidates_path")
    if not raw_path:
        return None
    path = Path(str(raw_path))
    if path.is_absolute():
        return path
    config_dir_path = Path(config_path).parent / path
    if config_dir_path.exists():
        return config_dir_path
    return Path.cwd() / path


def _allowed_pool500_sources(config: dict[str, Any]) -> set[str] | None:
    route = config.get("online_route") if isinstance(config.get("online_route"), dict) else {}
    value = route.get("allowed_sources") or config.get("pool500_allowed_sources")
    if not isinstance(value, list) or not value:
        return None
    return {str(source) for source in value if str(source or "").strip()}


def _merge_online_extra_candidates(candidates: list[MergedCandidate]) -> list[MergedCandidate]:
    merged: dict[str, MergedCandidate] = {}
    for candidate in candidates:
        current = merged.get(candidate.item_id)
        if current is None:
            merged[candidate.item_id] = MergedCandidate(
                item_id=candidate.item_id,
                sources=list(candidate.sources),
                source_scores=dict(candidate.source_scores),
                category=candidate.category,
                metadata=dict(candidate.metadata),
            )
            continue
        for source in candidate.sources:
            if source not in current.sources:
                current.sources.append(source)
            current.source_scores[source] = max(float(current.source_scores.get(source, 0.0)), float(candidate.source_scores.get(source, 0.0)))
        if not current.category:
            current.category = candidate.category
        current.metadata.update({key: value for key, value in candidate.metadata.items() if key not in current.metadata})
    rows = list(merged.values())
    rows.sort(key=lambda item: (-sum(float(score) for score in item.source_scores.values()), item.item_id))
    return rows


def _candidate_source_coverage(candidates: list[MergedCandidate]) -> dict[str, int]:
    coverage: Counter[str] = Counter()
    for candidate in candidates:
        for source in candidate.sources:
            coverage[str(source)] += 1
    return dict(sorted(coverage.items()))


def _public_assistant_message(items: list[dict[str, Any]]) -> str:
    if not items:
        return "暂时没有找到合适的商品，你可以补充更多历史行为或偏好。"
    return "我根据你的历史行为和当前偏好，为你推荐了这些商品。"
