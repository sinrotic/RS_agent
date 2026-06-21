from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from rs_core.common.io import iter_jsonl, read_json
from rs_core.display.builder import item_to_display_card, validate_public_display_payload
from rs_core.recsys.candidate_merge import (
    co_visit_transition_candidates_for_user,
    load_co_visit_transition_graph_manifest,
    load_itemcf_source_manifest,
    load_two_tower_index,
    load_usercf_recall_sidecar,
    merge_candidates,
    two_tower_candidates_for_user,
    usercf_candidates_for_user,
)
from rs_core.recsys.pool500_artifacts import Pool500ArtifactIndex, load_pool500_artifact_index
from rs_core.recsys.vectorstores.qdrant_client import QdrantVectorStore
from rs_core.recsys.vectorstores.qdrant_contracts import DEFAULT_TWO_TOWER_COLLECTION, OptionalQdrantDependencyMissing
from rs_core.recsys.vectorstores.qdrant_two_tower import QdrantTwoTowerIndex
from rs_core.recsys.types import MergedCandidate, RecallCandidate
from rs_core.rsagent.policy import normalize_feedback_input, parse_feedback
from rs_core.rsagent.schema import DisplayResponse
from rs_core.workflow.hybrid_demo import recommend_for_user
from rs_core.workflow.hybrid_environment import HybridRecommendationEnvironment


FORBIDDEN_LIVE_CANDIDATE_SOURCES = {"co_visit_fallback_repair"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
        self._itemcf_lookup: dict[str, dict[str, list[RecallCandidate]]] = {}
        self._itemcf_lookup_errors: dict[str, str] = {}
        self._usercf_lookup: dict[str, list[RecallCandidate]] | None = None
        self._usercf_lookup_error: str | None = None
        self._co_visit_lookup: dict[str, list[RecallCandidate]] | None = None
        self._co_visit_lookup_error: str | None = None
        self._two_tower_index: Any | None = None
        self._two_tower_index_error: str | None = None

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
            "complete_pool500_available": False,
            "online_source_indexes_available": source_index_available,
            "online_source_indexes": source_indexes,
        }
        if not path:
            payload["pool500_artifact"] = {"enabled": False, "status": "not_configured"}
            return payload
        try:
            artifact_readiness = self._get_pool500_index().readiness()
            payload["pool500_artifact"] = artifact_readiness
            payload["complete_pool500_available"] = artifact_readiness.get("status") == "ready"
        except Exception as exc:  # pragma: no cover - defensive readiness path
            payload["pool500_artifact"] = {"enabled": True, "status": "error", "candidates_path": str(path), "error": _compact_error(exc)}
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
            source_index_candidates, source_index_diagnostics = self._source_index_candidates_for_sequence(normalized_sequence, config)
            artifact_candidates, artifact_diagnostics = self._artifact_candidates_for_sequence(normalized_sequence)
            if not artifact_diagnostics.get("pool500_artifact_enabled") and not _has_available_source_index(source_index_diagnostics):
                route_diagnostics = {
                    "route": "online_recall_degraded",
                    "complete_pool500": True,
                    **artifact_diagnostics,
                    "online_source_indexes": source_index_diagnostics,
                    "fallback_reason": "online_recall_unavailable",
                }
            else:
                extra_candidates = _merge_online_extra_candidates([*artifact_candidates, *source_index_candidates])
                repair_candidates, repair_diagnostics = self._co_visit_underfill_repair_candidates_for_sequence(
                    normalized_sequence,
                    config,
                    extra_candidates,
                )
                if repair_candidates:
                    extra_candidates = _merge_online_extra_candidates([*extra_candidates, *repair_candidates])
                route_diagnostics = {
                    "route": "online_recall_with_source_indexes",
                    "complete_pool500": True,
                    **artifact_diagnostics,
                    "source_index_candidate_count": len(source_index_candidates),
                    "source_index_coverage": _candidate_source_coverage(source_index_candidates),
                    "co_visit_underfill_repair": repair_diagnostics,
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
        fallback_used = bool(route_diagnostics.get("fallback_reason")) or result.fallback_used
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
        retrieve_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_sequence = _normalize_sequence(user_sequence, user_sequence.get("user_id"))
        policy = retrieve_policy if isinstance(retrieve_policy, dict) else {}
        seen_items = (prior_turn_items or set()) | set(normalized_sequence.get("recent_item_sequence", []))
        candidates: list[MergedCandidate] = []
        index = self._maybe_pool500_index()
        if index is not None:
            candidates.extend(_filter_live_candidates(index.candidates_for_user(normalized_sequence["user_id"], seen_items=seen_items)))
        request_config = _request_config(self.env.config, top_k=5, candidate_pool_size=candidate_pool_size)
        source_sequence = _sequence_with_reference_seed(normalized_sequence, policy.get("reference_item_id"))
        source_index_candidates, source_index_diagnostics = self._source_index_candidates_for_sequence(
            source_sequence,
            request_config,
        )
        candidates = _filter_live_candidates(_merge_online_extra_candidates([*candidates, *source_index_candidates]))
        repair_candidates, repair_diagnostics = self._co_visit_underfill_repair_candidates_for_sequence(
            normalized_sequence,
            request_config,
            candidates,
        )
        if repair_candidates:
            candidates = _merge_online_extra_candidates([*candidates, *repair_candidates])
        candidates = [candidate for candidate in candidates if candidate.item_id not in seen_items]
        if candidate_pool_size is not None:
            candidates = candidates[: int(candidate_pool_size)]
        route = "online_source_index" if index is None and source_index_candidates else "pool500_artifact_online" if index is not None else "demo_compatible"
        return {
            "candidate_item_ids": [candidate.item_id for candidate in candidates],
            "candidate_count": len(candidates),
            "candidates": candidates,
            "retrieval_summary": {
                "target_pool_size": candidate_pool_size,
                "path_count": len(_candidate_source_coverage(candidates)),
            },
            "diagnostics": {"compact": True, "route": route, "online_source_indexes": source_index_diagnostics, "co_visit_underfill_repair": repair_diagnostics},
        }

    def tool_rank_candidates(self, turn: Any | None, *, return_top_k: int | None = None) -> dict[str, Any]:
        ranking_snapshot = list(getattr(turn, "ranking", []) or [])
        normalized_top_k = _rank_return_top_k(return_top_k)
        ranked_items = ranking_snapshot[:normalized_top_k]
        ranked_item_ids = [str(item.get("parent_asin") or item.get("item_id")) for item in ranked_items if item.get("parent_asin") or item.get("item_id")]
        governance = {
            "internal_only": True,
            "public_payload_allowed": False,
            "ranking_replacement_allowed": False,
            "promotion_allowed": False,
            "diagnostic_only": True,
        }
        return {
            "ranked_item_ids": ranked_item_ids,
            "ranked_item_count": len(ranked_item_ids),
            "ranking_summary": {
                "schema_version": "rank_candidates_output_v1",
                "ranker": "online_route_facade",
                "route": "online_route_facade",
                "candidate_count": len(getattr(turn, "candidates", []) or []),
                "ranked_item_count": len(ranked_item_ids),
                "return_top_k": normalized_top_k,
                "has_ranking_snapshot": bool(ranking_snapshot),
                "governance": governance,
            },
            "diagnostics": {
                "compact": True,
                "internal_only": True,
                "public_payload_allowed": False,
                "route": "online_route_facade",
                "reason": "uses_existing_turn_ranking_snapshot",
                "truncated": len(ranking_snapshot) > len(ranked_items),
            },
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
            self._pool500_index_error = _compact_error(exc)
            raise
        return self._pool500_index

    def _maybe_pool500_index(self) -> Pool500ArtifactIndex | None:
        path = _pool500_candidates_path(self.env.config, self.env.config_path)
        if path is None:
            return None
        try:
            return self._get_pool500_index()
        except Exception:
            return None

    def _artifact_candidates_for_sequence(self, user_sequence: dict[str, Any]) -> tuple[list[MergedCandidate], dict[str, Any]]:
        index = self._maybe_pool500_index()
        if index is None:
            return [], {"pool500_artifact_enabled": False}
        seen_items = set(user_sequence.get("recent_item_sequence", []))
        candidates = _filter_live_candidates(index.candidates_for_user(str(user_sequence.get("user_id") or ""), seen_items=seen_items))
        return candidates, {
            "artifact_candidate_count": len(candidates),
            "artifact_source_coverage": _candidate_source_coverage(candidates),
            "pool500_artifact_enabled": True,
        }

    def _source_index_readiness(self) -> dict[str, dict[str, Any]]:
        readiness: dict[str, dict[str, Any]] = {}
        for source, source_config in _online_source_index_configs(self.env.config, self.env.config_path).items():
            manifest_path = source_config.get("manifest_path")
            if not source_config.get("enabled", True):
                readiness[source] = {"enabled": False, "available": False, "status": "disabled"}
                continue
            if manifest_path is None:
                readiness[source] = {"enabled": True, "available": False, "status": "missing_manifest_path"}
                continue
            status: dict[str, Any] = {"enabled": True, "available": False, "manifest_path": str(manifest_path)}
            try:
                if source == "co_visit_fallback_repair":
                    manifest = read_json(manifest_path)
                    guarded = _is_guarded_co_visit_manifest(manifest)
                    full_graph = _is_co_visit_transition_graph_manifest(manifest)
                    candidates_path = _co_visit_candidates_path(manifest, Path(manifest_path)) if guarded else None
                    status.update({
                        "available": bool(full_graph),
                        "status": "underfill_repair_index_ready" if full_graph else "diagnostic_only" if guarded and candidates_path is not None and candidates_path.exists() else "missing_diagnostic_artifact" if guarded else "not_full_online_graph",
                        "artifact_backed_guarded": guarded and candidates_path is not None and candidates_path.exists(),
                        "full_online_graph": bool(full_graph),
                        "underfill_repair_allowed": bool(full_graph and manifest.get("underfill_repair_allowed") is True),
                        "candidate_generation_allowed": False,
                    })
                elif source in {"itemcf_weak", "itemcf_strong"}:
                    manifest = read_json(manifest_path)
                    blocked = _itemcf_requires_heavy_request_scan(manifest) and not source_config.get("allow_heavy_scan", False)
                    status.update({
                        "available": Path(manifest_path).exists() and not blocked,
                        "status": "blocked_heavy_scan" if blocked else "configured" if Path(manifest_path).exists() else "missing_manifest",
                    })
                elif source == "two_tower":
                    status.update(_two_tower_source_readiness_status(source_config, manifest_path))
                else:
                    status.update({"available": Path(manifest_path).exists(), "status": "configured" if Path(manifest_path).exists() else "missing_manifest"})
            except Exception as exc:  # pragma: no cover - readiness must stay defensive
                status.update({"available": False, "status": "error", "error": _compact_error(exc)})
            readiness[source] = status
        return readiness

    def _source_index_candidates_for_sequence(self, user_sequence: dict[str, Any], config: dict[str, Any]) -> tuple[list[MergedCandidate], dict[str, Any]]:
        source_configs = _online_source_index_configs(self.env.config, self.env.config_path)
        diagnostics: dict[str, Any] = {}
        raw_candidates: list[RecallCandidate] = []
        seen_items = set(user_sequence.get("recent_item_sequence", []))
        for source, source_config in source_configs.items():
            if not source_config.get("enabled", True):
                diagnostics[source] = {"available": False, "status": "disabled", "candidate_count": 0}
                continue
            manifest_path = source_config.get("manifest_path")
            if manifest_path is None:
                diagnostics[source] = {"available": False, "status": "missing_manifest_path", "candidate_count": 0}
                continue
            try:
                if source in {"itemcf_weak", "itemcf_strong"}:
                    manifest = read_json(manifest_path)
                    if _itemcf_requires_heavy_request_scan(manifest) and not source_config.get("allow_heavy_scan", False):
                        diagnostics[source] = {"available": False, "status": "blocked_heavy_scan", "candidate_count": 0}
                        continue
                    seeds = _source_index_itemcf_seeds(user_sequence, source)
                    lookup = load_itemcf_source_manifest(manifest_path, source, allowed_src_items=seeds)
                    self._itemcf_lookup[source] = lookup
                    per_seed = int(config.get(f"{source}_per_seed", 20))
                    source_rows = [candidate for seed in seeds for candidate in lookup.get(seed, [])[:per_seed]]
                elif source == "usercf_recall":
                    if self._usercf_lookup is None:
                        self._usercf_lookup = load_usercf_recall_sidecar(manifest_path)
                    source_config = dict(config) | {"usercf_enabled": True}
                    source_rows = usercf_candidates_for_user(user_sequence, self._usercf_lookup, source_config)
                elif source == "two_tower":
                    if self._two_tower_index is None:
                        self._two_tower_index = _load_two_tower_backend(manifest_path, source_config)
                    source_config = dict(config) | {"two_tower_enabled": True}
                    source_rows = two_tower_candidates_for_user(user_sequence, self._two_tower_index, source_config)
                elif source == "co_visit_fallback_repair":
                    manifest = read_json(manifest_path)
                    guarded = _is_guarded_co_visit_manifest(manifest)
                    full_graph = _is_co_visit_transition_graph_manifest(manifest)
                    candidates_path = _co_visit_candidates_path(manifest, Path(manifest_path)) if guarded else None
                    diagnostics[source] = {
                        "available": bool(full_graph),
                        "status": "underfill_repair_index_ready" if full_graph else "diagnostic_only" if guarded else "not_serving_authorized",
                        "artifact_backed_guarded": guarded and candidates_path is not None and candidates_path.exists(),
                        "full_online_graph": bool(full_graph),
                        "underfill_repair_allowed": bool(full_graph and manifest.get("underfill_repair_allowed") is True),
                        "candidate_generation_allowed": False,
                        "candidate_count": 0,
                    }
                    continue
                else:
                    diagnostics[source] = {"available": False, "status": "unsupported_source", "candidate_count": 0}
                    continue
                diagnostics[source] = {"available": True, "status": "configured", "candidate_count": len(source_rows)}
                raw_candidates.extend(source_rows)
            except Exception as exc:
                diagnostics[source] = {"available": False, "status": "error", "error": _compact_error(exc), "candidate_count": 0}
        return _filter_live_candidates(merge_candidates(raw_candidates, seen_items=seen_items)), diagnostics

    def _co_visit_underfill_repair_candidates_for_sequence(
        self,
        user_sequence: dict[str, Any],
        config: dict[str, Any],
        current_candidates: list[MergedCandidate],
    ) -> tuple[list[MergedCandidate], dict[str, Any]]:
        source_config = _online_source_index_configs(self.env.config, self.env.config_path).get("co_visit_fallback_repair") or {}
        diagnostics: dict[str, Any] = {
            "triggered": False,
            "available": False,
            "status": "not_configured",
            "candidate_count": 0,
        }
        if not source_config.get("enabled", True):
            diagnostics["status"] = "disabled"
            return [], diagnostics
        if not source_config.get("allow_underfill_repair", False):
            diagnostics["status"] = "underfill_repair_disabled"
            return [], diagnostics
        manifest_path = source_config.get("manifest_path")
        if manifest_path is None:
            diagnostics["status"] = "missing_manifest_path"
            return [], diagnostics
        target_pool_size = int(config.get("candidate_pool_size", self.env.config.get("candidate_pool_size", 500)))
        trigger_count = int(source_config.get("underfill_trigger_count", target_pool_size))
        current_item_ids = {candidate.item_id for candidate in current_candidates}
        deficit = max(0, target_pool_size - len(current_candidates))
        diagnostics.update({"deficit_before_repair": deficit, "current_candidate_count": len(current_candidates), "target_pool_size": target_pool_size})
        if len(current_candidates) >= trigger_count:
            diagnostics["status"] = "not_underfilled"
            return [], diagnostics
        seed_window = int(source_config.get("seed_window", config.get("co_visit_seed_window", 30)))
        seed_values = user_sequence.get("recent_positive_item_sequence", []) or user_sequence.get("recent_item_sequence", [])
        seeds = _recent_unique_sequence_items(seed_values, seed_window)
        diagnostics["seed_count"] = len(seeds)
        if not seeds:
            diagnostics["status"] = "missing_seed_items"
            return [], diagnostics
        try:
            manifest = read_json(manifest_path)
            if not _is_co_visit_transition_graph_manifest(manifest):
                guarded = _is_guarded_co_visit_manifest(manifest)
                diagnostics.update({
                    "status": "diagnostic_only" if guarded else "not_full_online_graph",
                    "available": False,
                    "full_online_graph": False,
                })
                return [], diagnostics
            lookup = load_co_visit_transition_graph_manifest(manifest_path, allowed_src_items=set(seeds))
            repair_limit = int(source_config.get("per_user", config.get("co_visit_per_user", config.get("co_visit_underfill_per_user", 100))))
            if deficit > 0:
                repair_limit = min(repair_limit, deficit)
            repair_config = dict(config) | {
                "co_visit_seed_window": seed_window,
                "co_visit_per_seed": int(source_config.get("per_seed", config.get("co_visit_per_seed", config.get("co_visit_underfill_per_seed", 50)))),
                "co_visit_per_user": repair_limit,
            }
            raw_candidates = co_visit_transition_candidates_for_user(
                user_sequence,
                lookup,
                repair_config,
                exclude_items=current_item_ids,
            )
            merged = _filter_live_candidates(
                merge_candidates(raw_candidates, seen_items=set(user_sequence.get("recent_item_sequence", []))),
                allow_sources={"co_visit_fallback_repair"},
            )
            diagnostics.update({
                "triggered": bool(merged),
                "available": True,
                "status": "underfill_repair_index_ready",
                "full_online_graph": True,
                "candidate_count": len(merged),
            })
            return merged, diagnostics
        except Exception as exc:
            diagnostics.update({"available": False, "status": "error", "error": _compact_error(exc)})
            return [], diagnostics

    def _co_visit_candidates_for_user(self, manifest_path: Path, user_sequence: dict[str, Any]) -> list[RecallCandidate]:
        if self._co_visit_lookup is None:
            manifest = read_json(manifest_path)
            if not _is_guarded_co_visit_manifest(manifest):
                raise ValueError("co_visit_fallback_repair source-index must remain batch-scoped guarded artifact")
            candidates_path = _co_visit_candidates_path(manifest, manifest_path)
            if candidates_path is None:
                raise ValueError("co_visit_fallback_repair guarded manifest requires candidates_path")
            self._co_visit_lookup = _load_pregenerated_source_candidates(candidates_path, "co_visit_fallback_repair")
        source_config = dict(self.env.config) | {
            "usercf_enabled": True,
            "usercf_per_user": int(self.env.config.get("co_visit_per_user", self.env.config.get("usercf_per_user", 0))),
        }
        return usercf_candidates_for_user(user_sequence, self._co_visit_lookup, source_config)


def _sequence_with_reference_seed(user_sequence: dict[str, Any], reference_item_id: Any) -> dict[str, Any]:
    item_id = str(reference_item_id or "").strip()
    if not item_id:
        return user_sequence
    sequence = dict(user_sequence)
    for key in ("recent_item_sequence", "recent_positive_item_sequence"):
        values = [str(item) for item in sequence.get(key, []) if str(item or "").strip()]
        if item_id not in values:
            values.append(item_id)
        sequence[key] = values
    return sequence



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
    return _resolve_config_path(raw_path, config_path)


def _allowed_pool500_sources(config: dict[str, Any]) -> set[str] | None:
    route = config.get("online_route") if isinstance(config.get("online_route"), dict) else {}
    value = route.get("allowed_sources") or config.get("pool500_allowed_sources")
    if not isinstance(value, list) or not value:
        return None
    return {str(source) for source in value if str(source or "").strip()}


def _online_source_index_configs(config: dict[str, Any], config_path: str | Path) -> dict[str, dict[str, Any]]:
    route = config.get("online_route") if isinstance(config.get("online_route"), dict) else {}
    raw_indexes = route.get("source_indexes") or route.get("online_source_indexes") or route.get("source_manifests") or {}
    if not isinstance(raw_indexes, dict):
        return {}
    configs: dict[str, dict[str, Any]] = {}
    for source, raw_config in raw_indexes.items():
        source_name = str(source)
        if isinstance(raw_config, str):
            source_config: dict[str, Any] = {"enabled": True, "manifest_path": raw_config}
        elif isinstance(raw_config, dict):
            source_config = dict(raw_config)
        else:
            continue
        raw_path = source_config.get("manifest_path") or source_config.get("path") or source_config.get("source_index_manifest")
        if raw_path:
            source_config["manifest_path"] = _resolve_config_path(raw_path, config_path)
        configs[source_name] = source_config
    return configs


def _two_tower_source_readiness_status(source_config: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    backend = str(source_config.get("backend", "local_vector")).strip().lower()
    if backend != "qdrant":
        return {"available": Path(manifest_path).exists(), "status": "configured" if Path(manifest_path).exists() else "missing_manifest"}
    qdrant_config = source_config.get("qdrant") if isinstance(source_config.get("qdrant"), dict) else {}
    if not qdrant_config.get("enabled", False):
        return {"available": Path(manifest_path).exists(), "status": "configured" if Path(manifest_path).exists() else "missing_manifest"}
    try:
        store = QdrantVectorStore.from_config(qdrant_config)
        collection_name = str(qdrant_config.get("collection_name") or DEFAULT_TWO_TOWER_COLLECTION)
        store.client.get_collection(collection_name=collection_name)
    except OptionalQdrantDependencyMissing:
        return {"available": False, "status": "qdrant_dependency_missing", "backend": "qdrant"}
    except Exception:
        return {"available": False, "status": "qdrant_unavailable", "backend": "qdrant"}
    return {"available": Path(manifest_path).exists(), "status": "qdrant_configured" if Path(manifest_path).exists() else "missing_manifest", "backend": "qdrant"}


def _load_two_tower_backend(manifest_path: Path, source_config: dict[str, Any]) -> Any:
    local_index = load_two_tower_index(manifest_path)
    backend = str(source_config.get("backend", "local_vector")).strip().lower()
    if backend != "qdrant":
        return local_index
    qdrant_config = source_config.get("qdrant") if isinstance(source_config.get("qdrant"), dict) else {}
    if not qdrant_config.get("enabled", False):
        return local_index
    return QdrantTwoTowerIndex(
        store=QdrantVectorStore.from_config(qdrant_config),
        collection_name=str(qdrant_config.get("collection_name") or DEFAULT_TWO_TOWER_COLLECTION),
        items=dict(getattr(local_index, "items", {}) or {}),
        user_embeddings=dict(getattr(local_index, "user_embeddings", {}) or {}),
        source_name=str(getattr(local_index, "source_name", "two_tower") or "two_tower"),
        model_metadata=dict(getattr(local_index, "model_metadata", {}) or {}),
    )



def _resolve_config_path(raw_path: Any, config_path: str | Path) -> Path:
    path = Path(str(raw_path))
    if path.is_absolute():
        return path
    repo_path = PROJECT_ROOT / path
    if repo_path.exists():
        return repo_path
    config_dir_path = Path(config_path).resolve().parent / path
    if config_dir_path.exists():
        return config_dir_path
    return repo_path


def _source_index_itemcf_seeds(user_sequence: dict[str, Any], source: str) -> set[str]:
    if source == "itemcf_strong":
        seeds = user_sequence.get("recent_strong_positive_item_sequence", []) or user_sequence.get("recent_positive_item_sequence", [])
    else:
        seeds = user_sequence.get("recent_positive_item_sequence", [])
    return {str(item) for item in seeds if str(item or "").strip()}


def _recent_unique_sequence_items(values: Any, window: int) -> list[str]:
    if not isinstance(values, list):
        return []
    rows: list[str] = []
    seen: set[str] = set()
    for value in reversed(values[-window:]):
        item_id = str(value or "")
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        rows.append(item_id)
    return rows



def _itemcf_requires_heavy_request_scan(manifest: dict[str, Any]) -> bool:
    shard_values = manifest.get("edges_shards")
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    if not isinstance(shard_values, list):
        shard_values = outputs.get("edges_shards")
    return isinstance(shard_values, list) and len(shard_values) > 4


def _is_guarded_co_visit_manifest(manifest: dict[str, Any]) -> bool:
    return (
        manifest.get("source") == "co_visit_fallback_repair"
        and manifest.get("train_only") is True
        and manifest.get("candidate_generation_allowed") is False
        and manifest.get("ranking_input_replacement_allowed") is False
        and manifest.get("promotion_allowed") is False
        and manifest.get("pool1000_allowed") is False
        and (manifest.get("batch_scoped_evidence_only") is True or manifest.get("source_status") == "TARGET_SLICE_DIAGNOSTIC")
    )


def _is_co_visit_transition_graph_manifest(manifest: dict[str, Any]) -> bool:
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    return (
        manifest.get("source") == "co_visit_fallback_repair"
        and manifest.get("source_status") == "UNDERFILL_REPAIR_INDEX_READY"
        and manifest.get("index_scope") == "FULL_DERIVED_INDEX"
        and manifest.get("train_only") is True
        and manifest.get("candidate_materialization") == "none"
        and manifest.get("underfill_repair_allowed") is True
        and manifest.get("candidate_generation_allowed") is False
        and manifest.get("serving_candidate_source_allowed") is False
        and manifest.get("ranking_input_replacement_allowed") is False
        and manifest.get("ranking_replacement_allowed") is False
        and manifest.get("promotion_allowed") is False
        and manifest.get("pool1000_allowed") is False
        and manifest.get("final_pool500_ready_claimed") is False
        and manifest.get("batch_scoped_evidence_only") is not True
        and manifest.get("candidates_path") is None
        and outputs.get("candidates") is None
        and outputs.get("candidates_path") is None
    )



def _co_visit_candidates_path(manifest: dict[str, Any], manifest_path: Path) -> Path | None:
    raw_path = manifest.get("candidates_path")
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    raw_path = raw_path or outputs.get("candidates_path") or outputs.get("candidates")
    if not raw_path:
        return None
    path = Path(str(raw_path))
    if path.is_absolute():
        return path
    return manifest_path.parent / path


def _load_pregenerated_source_candidates(path: Path, source: str) -> dict[str, list[RecallCandidate]]:
    by_user: dict[str, list[RecallCandidate]] = defaultdict(list)
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id") or "")
        item_id = str(row.get("item_id") or row.get("parent_asin") or "")
        if not user_id or not item_id:
            continue
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        by_user[user_id].append(RecallCandidate(
            item_id=item_id,
            source=source,
            score=float(row.get("score") or 0.0),
            category=str(metadata.get("category") or row.get("category") or ""),
            metadata=dict(metadata),
        ))
    for rows in by_user.values():
        rows.sort(key=lambda item: (-item.score, item.item_id))
    return by_user


def _has_available_source_index(diagnostics: dict[str, Any]) -> bool:
    return any(isinstance(status, dict) and status.get("available") for status in diagnostics.values())


def _filter_live_candidates(candidates: list[MergedCandidate], allow_sources: set[str] | None = None) -> list[MergedCandidate]:
    allow_sources = allow_sources or set()
    filtered: list[MergedCandidate] = []
    for candidate in candidates:
        sources = [source for source in candidate.sources if source not in FORBIDDEN_LIVE_CANDIDATE_SOURCES or source in allow_sources]
        if not sources:
            continue
        source_scores = {source: score for source, score in candidate.source_scores.items() if source in sources}
        metadata = _filter_live_candidate_metadata(candidate.metadata, allow_sources=allow_sources)
        filtered.append(MergedCandidate(
            item_id=candidate.item_id,
            sources=sources,
            source_scores=source_scores,
            category=candidate.category,
            metadata=metadata,
        ))
    return filtered


def _filter_live_candidate_metadata(metadata: dict[str, Any], allow_sources: set[str] | None = None) -> dict[str, Any]:
    allow_sources = allow_sources or set()
    filtered = {
        key: value
        for key, value in metadata.items()
        if not any(str(key).startswith(source) for source in FORBIDDEN_LIVE_CANDIDATE_SOURCES if source not in allow_sources)
    }
    lineage = filtered.get("pool500_source_lineage")
    if isinstance(lineage, list):
        filtered["pool500_source_lineage"] = [
            row for row in lineage
            if not isinstance(row, dict) or row.get("source") not in FORBIDDEN_LIVE_CANDIDATE_SOURCES or row.get("source") in allow_sources
        ]
    return filtered


def _compact_error(exc: Exception) -> str:
    return exc.__class__.__name__


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


def _rank_return_top_k(value: int | None) -> int:
    if isinstance(value, bool) or value is None:
        return 20
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 20
    return max(1, min(parsed, 500))


def _public_assistant_message(items: list[dict[str, Any]]) -> str:
    if not items:
        return "暂时没有找到合适的商品，你可以补充更多历史行为或偏好。"
    return "我根据你的历史行为和当前偏好，为你推荐了这些商品。"
