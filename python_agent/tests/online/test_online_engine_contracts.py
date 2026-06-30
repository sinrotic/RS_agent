from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_core.data.clients import ArtifactClient, CandidatePoolClient, DataClient
from rs_core.data.contracts import CandidatePoolContract
from rs_core.online.contracts import (
    ONLINE_PUBLIC_TRACE_ALLOWED_FIELDS,
    ONLINE_PUBLIC_TRACE_FORBIDDEN_FIELDS,
    POOL_EVIDENCE_FIELD_BOUNDARY,
    RankingRequest,
    RankingTrace,
    RecallTrace,
)
from rs_core.online.engine import OnlineRecommendationEngine
from rs_core.online import recall as online_recall
from rs_core.online.ranking import rank_candidates
from rs_core.common.recsys_types import MergedCandidate

pytestmark = [pytest.mark.unit]

FORBIDDEN_PUBLIC_MARKERS = {
    "agent_tool_trace",
    "diagnostics_path",
    "ground_truth",
    "holdout",
    "label_binary",
    "oracle",
    "score_trace",
    "training_samples",
}


def test_online_engine_ready_is_public_safe_without_bound_recommender() -> None:
    ready = OnlineRecommendationEngine().ready()

    assert ready["status"] == "degraded"
    assert ready["engine"] == "OnlineRecommendationEngine"
    assert ready["reason"] == "no_recommender_bound"
    assert ready["dependencies"] == {
        "candidate_pool_client": "CandidatePoolClient",
        "feature_client": "FeatureClient",
        "artifact_client": "ArtifactClient",
    }
    assert _leaked_markers(ready) == []


def test_online_recommend_contract_has_public_fallback_shape() -> None:
    result = OnlineRecommendationEngine().recommend({"user_sequence": {"recent_item_ids": ["i1"]}, "top_k": 1})

    assert set(result) == {"request_id", "display", "items", "candidate_count", "fallback_used", "ranking_trace"}
    assert result["display"] == {"assistant_message": "online engine is available without a bound recommender", "items": []}
    assert result["items"] == []
    assert result["candidate_count"] == 0
    assert result["fallback_used"] is True
    assert result["ranking_trace"] == {"route": "unbound_fallback"}
    assert _leaked_markers(result) == []


def test_online_recall_contract_uses_public_trace_and_rejects_oracle_fields() -> None:
    engine = OnlineRecommendationEngine()
    result = engine.recall({"user_sequence": {"recent_item_ids": ["i3", "i2", "i1"]}, "candidate_pool_size": 2})

    assert set(result) == {"request_id", "candidate_item_ids", "candidate_count", "retrieval_summary"}
    assert result["candidate_item_ids"] == ["i3", "i2"]
    assert result["candidate_count"] == 2
    assert result["retrieval_summary"] == RecallTrace(target_pool_size=2, path_count=1).to_dict()
    assert _leaked_markers(result) == []

    with pytest.raises(ValueError, match="evaluation-only fields"):
        engine.recall({"user_sequence": {"recent_item_ids": ["i1"], "label_binary": 1}})


def test_online_recall_contract_uses_candidate_pool_client() -> None:
    candidate_pool_client = _RecordingCandidatePoolClient()
    result = OnlineRecommendationEngine(candidate_pool_client=candidate_pool_client).recall(
        {"user_sequence": {"recent_item_ids": ["i3", "i2", "i3"]}, "candidate_pool_size": 3}
    )

    assert result["candidate_item_ids"] == ["i3", "i2"]
    assert candidate_pool_client.calls == [
        ("online_recall_sequence_contract", ["i3", "i2", "i3"]),
    ]


def test_pool500_recommender_public_recall_delegates_to_runtime_tool() -> None:
    from rs_core.online.runtime.pool500 import OnlinePool500Recommender

    recommender = OnlinePool500Recommender.__new__(OnlinePool500Recommender)
    calls: list[dict[str, object]] = []

    def fake_tool_retrieve_candidates(
        user_sequence: dict[str, object],
        *,
        prior_turn_items: set[str] | None = None,
        candidate_pool_size: int | None = None,
    ) -> dict[str, object]:
        calls.append({
            "user_sequence": user_sequence,
            "prior_turn_items": sorted(prior_turn_items or set()),
            "candidate_pool_size": candidate_pool_size,
        })
        return {
            "candidate_item_ids": ["i3", "i2"],
            "candidate_count": 2,
            "retrieval_summary": {"target_pool_size": candidate_pool_size, "path_count": 1},
        }

    recommender.tool_retrieve_candidates = fake_tool_retrieve_candidates  # type: ignore[method-assign]

    result = recommender.recall({
        "user_id": "u1",
        "user_sequence": {"recent_item_ids": ["i1"]},
        "candidate_pool_size": 2,
        "prior_turn_items": ["i0"],
    })

    assert result["candidate_item_ids"] == ["i3", "i2"]
    assert result["candidate_count"] == 2
    assert result["retrieval_summary"] == {"target_pool_size": 2, "path_count": 1}
    assert calls == [
        {
            "user_sequence": {"recent_item_ids": ["i1"], "user_id": "u1"},
            "prior_turn_items": ["i0"],
            "candidate_pool_size": 2,
        }
    ]


def test_online_rank_contract_deduplicates_and_uses_public_trace() -> None:
    result = OnlineRecommendationEngine().rank(RankingRequest(candidate_item_ids=["i2", "i1", "i2"], return_top_k=2))

    assert result == {
        "ranked_item_ids": ["i2", "i1"],
        "ranking_trace": RankingTrace(returned_count=2).to_dict(),
    }
    assert _leaked_markers(result) == []


def test_online_recall_exports_source_helpers_from_canonical_owner() -> None:
    source_labels = sorted(
        online_recall.CANONICAL_SOURCES
        | set(online_recall.SOURCE_ALIASES)
        | set(online_recall.GROUP_SOURCE_EXPANSIONS)
        | online_recall.FORBIDDEN_SOURCE_LABELS
    )

    for source in source_labels:
        assert online_recall.canonicalize_source_label(source)
        assert isinstance(online_recall.canonicalize_source_set([source]), set)
        assert isinstance(online_recall.forbidden_source_labels([source]), set)
        assert isinstance(online_recall.unknown_source_labels([source]), set)


def test_online_rank_fallback_parity_with_legacy_stable_input_smoke() -> None:
    candidates = [
        MergedCandidate(item_id="i2", sources=["popular"], source_scores={"popular": 1.0}),
        MergedCandidate(item_id="i1", sources=["popular"], source_scores={"popular": 1.0}),
    ]
    legacy = rank_candidates("u1", candidates, {"top_k": 2, "rank_weights": {"popular": 1.0}})
    result = OnlineRecommendationEngine().rank(
        RankingRequest(
            candidate_item_ids=[str(item["parent_asin"]) for item in legacy.items],
            return_top_k=2,
        )
    )

    assert result["ranked_item_ids"] == [str(item["parent_asin"]) for item in legacy.items]
    assert result["ranking_trace"] == RankingTrace(returned_count=2).to_dict()
    assert _leaked_markers(result) == []


def test_online_rank_cold_deepfm_shadow_contract_does_not_replace_public_order(tmp_path: Path) -> None:
    model_path = tmp_path / "deepfm_model.json"
    model_path.write_text(json.dumps(_deepfm_model()), encoding="utf-8")
    result = OnlineRecommendationEngine(artifact_client=ArtifactClient(DataClient(project_root=tmp_path))).rank(
        RankingRequest(
            candidate_item_ids=["i2", "i1", "i2"],
            return_top_k=2,
            ranking_context={
                "cold_deepfm_shadow": {
                    "enabled": True,
                    "user_id": "u1",
                    "deepfm_model_artifact": {
                        "artifact_id": "deepfm-shadow-smoke",
                        "uri": "deepfm_model.json",
                        "kind": "deepfm_model",
                    },
                    "candidate_features": {
                        "i1": {"score_semantic": 9.0},
                        "i2": {"score_semantic": 1.0},
                    },
                }
            },
        )
    )

    assert result == {
        "ranked_item_ids": ["i2", "i1"],
        "ranking_trace": {
            "ranker": "cold_deepfm_shadow_contract",
            "returned_count": 2,
            "route": "cold_deepfm_diagnostic_no_promotion",
        },
    }
    assert _leaked_markers(result) == []


def test_online_rank_route_reads_shadow_model_through_artifact_client() -> None:
    from fastapi.testclient import TestClient
    from rs_core.serving.api.online_app import create_app
    from rs_core.serving.runtime.split_engines import get_online_engine

    artifact_client = _RecordingArtifactClient()
    app = create_app()
    app.dependency_overrides[get_online_engine] = lambda: OnlineRecommendationEngine(artifact_client=artifact_client)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/rank",
                json={
                    "candidate_item_ids": ["i2", "i1"],
                    "return_top_k": 2,
                    "ranking_context": {
                        "cold_deepfm_shadow": {
                            "enabled": True,
                            "deepfm_model_artifact": {"artifact_id": "deepfm-shadow", "uri": "models/deepfm.json"},
                            "candidate_features": {
                                "i1": {"score_semantic": 9.0},
                                "i2": {"score_semantic": 1.0},
                            },
                        }
                    },
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["ranked_item_ids"] == ["i2", "i1"]
    assert response.json()["ranking_trace"]["route"] == "cold_deepfm_diagnostic_no_promotion"
    assert artifact_client.calls == [("deepfm-shadow", "models/deepfm.json", "ranking_model")]


def test_online_service_rejects_oracle_fields_on_public_recommendation_routes() -> None:
    from fastapi.testclient import TestClient
    from rs_core.serving.api.online_app import create_app

    with TestClient(create_app()) as client:
        for route in ["/recommend", "/recall"]:
            response = client.post(route, json={"user_sequence": {"recent_item_ids": ["i1"], "label_binary": 1}})
            assert response.status_code == 422
            assert "evaluation-only fields" in response.text


def test_online_public_trace_field_policy_documents_pool_evidence_boundary() -> None:
    assert {"target_pool_size", "path_count"}.issubset(ONLINE_PUBLIC_TRACE_ALLOWED_FIELDS)
    assert {"ranker", "returned_count", "route"}.issubset(ONLINE_PUBLIC_TRACE_ALLOWED_FIELDS)
    assert FORBIDDEN_PUBLIC_MARKERS.issubset(ONLINE_PUBLIC_TRACE_FORBIDDEN_FIELDS)
    assert POOL_EVIDENCE_FIELD_BOUNDARY == {
        "pool200": "offline_evaluation_only_not_public_online_trace",
        "pool500": "recall_readiness_or_shadow_evidence_not_ranking_replacement",
        "shadow_evidence": "internal_diagnostics_only_not_public_response",
    }


class _RecordingArtifactClient(ArtifactClient):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str, str]] = []

    def read_json_artifact(self, artifact_id: str, uri: str | Path, kind: str = "generic") -> dict[str, object]:
        self.calls.append((artifact_id, str(uri), kind))
        return _deepfm_model()


class _RecordingCandidatePoolClient(CandidatePoolClient):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, list[str]]] = []

    def from_item_ids(self, pool_id: str, item_ids: list[str], source: str = "manual") -> CandidatePoolContract:
        self.calls.append((source, list(item_ids)))
        return super().from_item_ids(pool_id, item_ids, source)


def _leaked_markers(payload: object) -> list[str]:
    text = repr(payload).lower()
    return sorted(marker for marker in FORBIDDEN_PUBLIC_MARKERS if marker in text)


def _deepfm_model() -> dict[str, object]:
    return {
        "model_type": "deepfm_feature_cross_ranker_v1",
        "feature_names": ["score_semantic"],
        "bias": 0.0,
        "linear_weights": {"score_semantic": 1.0},
        "fm_factors": {"score_semantic": [0.0]},
        "deep_weights": [[0.0]],
        "deep_bias": [0.0],
        "deep_output": [0.0],
    }
