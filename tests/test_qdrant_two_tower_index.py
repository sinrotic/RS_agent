from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from qdrant_fakes import install_fake_qdrant

from rs_core.recsys.candidate_merge import two_tower_candidates_for_user
from rs_core.recsys.vector_index import VectorIndex
from rs_core.recsys.vectorstores import QDRANT_TWO_TOWER_ITEM_SCHEMA_VERSION, QdrantCollectionSpec, stable_qdrant_point_id, two_tower_item_payload
from rs_core.recsys.vectorstores.qdrant_client import QdrantVectorStore, build_qdrant_client
from rs_core.recsys.vectorstores.qdrant_two_tower import QdrantTwoTowerIndex


def test_qdrant_two_tower_index_matches_local_vector_search_and_excludes_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_qdrant(monkeypatch)
    local_index = VectorIndex(
        items={
            "seed": {"embedding": [1.0, 0.0], "category": "Audio"},
            "match": {"embedding": [0.99, 0.01], "category": "Audio"},
            "other": {"embedding": [0.0, 1.0], "category": "Lighting"},
            "opposite": {"embedding": [-1.0, 0.0], "category": "Audio"},
        },
        user_embeddings={"u1": [1.0, 0.0]},
        source_name="two_tower",
        model_metadata={"variant": "unit", "model_type": "fake"},
    )
    store = QdrantVectorStore(build_qdrant_client(location=":memory:"))
    collection_name = "test_two_tower_items"
    store.ensure_collection(
        QdrantCollectionSpec(
            collection_name=collection_name,
            vector_size=2,
            schema_version=QDRANT_TWO_TOWER_ITEM_SCHEMA_VERSION,
        )
    )
    store.upsert_points(
        collection_name=collection_name,
        points=[
            (
                stable_qdrant_point_id("two_tower", item_id),
                record["embedding"],
                two_tower_item_payload(item_id=item_id, metadata=record | {"variant": "unit"}),
            )
            for item_id, record in local_index.items.items()
        ],
    )
    qdrant_index = QdrantTwoTowerIndex(
        store=store,
        collection_name=collection_name,
        items=local_index.items,
        user_embeddings=local_index.user_embeddings,
        source_name="two_tower",
        model_metadata=local_index.model_metadata,
    )

    local_results = local_index.search([1.0, 0.0], limit=2, excluded_items={"seed"})
    qdrant_results = qdrant_index.search([1.0, 0.0], limit=2, excluded_items={"seed"})

    assert local_results[0].item_id == "match"
    assert qdrant_results[0].item_id == "match"
    assert "seed" not in {row.item_id for row in qdrant_results}
    assert "opposite" not in {row.item_id for row in qdrant_results}
    assert qdrant_results[0].metadata["two_tower_backend"] == "qdrant"


def test_two_tower_candidates_accept_qdrant_backend_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_qdrant(monkeypatch)
    store = QdrantVectorStore(build_qdrant_client(location=":memory:"))
    collection_name = "test_two_tower_candidates"
    store.ensure_collection(
        QdrantCollectionSpec(
            collection_name=collection_name,
            vector_size=2,
            schema_version=QDRANT_TWO_TOWER_ITEM_SCHEMA_VERSION,
        )
    )
    items = {
        "seed": {"embedding": [1.0, 0.0], "category": "Audio"},
        "match": {"embedding": [1.0, 0.0], "category": "Audio"},
    }
    store.upsert_points(
        collection_name=collection_name,
        points=[
            *[
                (
                    stable_qdrant_point_id("two_tower", item_id),
                    record["embedding"],
                    two_tower_item_payload(item_id=item_id, metadata=record),
                )
                for item_id, record in items.items()
            ],
            (
                stable_qdrant_point_id("two_tower", "holdout_like"),
                [1.0, 0.0],
                two_tower_item_payload(item_id="holdout_like", metadata={"category": "Audio"}) | {"train_only": False},
            ),
            (
                stable_qdrant_point_id("two_tower", "disabled_candidate_generation"),
                [1.0, 0.0],
                two_tower_item_payload(item_id="disabled_candidate_generation", metadata={"category": "Audio"})
                | {"candidate_generation_allowed": False},
            ),
        ],
    )
    qdrant_index = QdrantTwoTowerIndex(
        store=store,
        collection_name=collection_name,
        items=items,
        source_name="two_tower",
    )

    rows = two_tower_candidates_for_user(
        {"user_id": "u1", "recent_positive_item_sequence": ["seed"], "recent_item_sequence": ["seed"]},
        qdrant_index,
        {"two_tower_enabled": True, "two_tower_per_user": 5},
    )

    assert [row.item_id for row in rows] == ["match"]
    assert rows[0].source == "two_tower"
    assert rows[0].metadata["two_tower_backend"] == "qdrant"
    assert rows[0].metadata["two_tower_score_mode"] == "vector_dot"
