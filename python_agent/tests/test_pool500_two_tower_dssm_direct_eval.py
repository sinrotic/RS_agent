from __future__ import annotations

import json
from pathlib import Path

from rs_lab.experiments.recall.two_tower_DSSM.run_pool500_two_tower_dssm_direct_eval import run_two_tower_dssm_direct_eval


def test_two_tower_dssm_direct_eval_scores_without_using_labels_for_generation(tmp_path: Path) -> None:
    source_manifest = _write_source_manifest(tmp_path / "source")
    eval_users = tmp_path / "users.jsonl"
    train_sequences = tmp_path / "train_sequences.jsonl"
    labels = tmp_path / "labels.jsonl"
    output_manifest = tmp_path / "direct_eval_manifest.json"

    _write_jsonl(
        eval_users,
        [
            {"user_id": "u1", "segment": "hot"},
            {"user_id": "u2", "segment": "cold-ish"},
        ],
    )
    _write_jsonl(
        train_sequences,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["A"], "recent_item_sequence": ["A"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["missing"], "recent_item_sequence": ["missing"]},
        ],
    )
    _write_jsonl(
        labels,
        [
            {"user_id": "u1", "parent_asin": "B", "label_binary": 1},
            {"user_id": "u1", "parent_asin": "C", "label_binary": 0},
            {"user_id": "u2", "parent_asin": "C", "label_binary": 1},
        ],
    )

    manifest = run_two_tower_dssm_direct_eval(
        source_index_manifest_path=source_manifest,
        eval_users_path=eval_users,
        train_sequences_path=train_sequences,
        label_paths=[labels],
        output_manifest_path=output_manifest,
        metric_ks=[1],
        enforce_venv=False,
    )

    assert output_manifest.is_file()
    assert manifest["schema_version"] == "raw_two_tower_dssm_direct_eval_v1"
    assert manifest["eval_scope"] == "two_tower_dssm_direct_only"
    assert manifest["no_oracle_label_injection"] is True
    assert manifest["candidate_generation_inputs"] == [str(train_sequences), str(tmp_path / "source" / "recall_index.jsonl")]
    assert manifest["label_paths"] == [str(labels)]
    assert manifest["query_user_count"] == 1
    assert manifest["queryless_user_count"] == 1
    assert manifest["query_source_counts"] == {"recent_positive_item_sequence_average_vectors": 1}
    assert manifest["queryless_reason_counts"] == {"seed_items_missing_item_vectors": 1}
    assert manifest["search_config"]["artifact_user_embedding_first"] is True
    assert manifest["search_config"]["project_seed_average"] is True
    assert manifest["underfilled_user_count"] == 1
    assert manifest["metrics"]["recall_at_1"] == 0.5
    assert manifest["metrics"]["hit_rate_at_1"] == 0.5
    assert manifest["segment_metrics"]["hot"]["hit_rate_at_1"] == 1.0
    assert manifest["segment_metrics"]["cold-ish"]["hit_rate_at_1"] == 0.0
    assert manifest["raw_two_tower_dssm_unique_positive_hits"] == 1


def test_two_tower_dssm_direct_eval_uses_artifact_user_embedding_when_present(tmp_path: Path) -> None:
    source_manifest = _write_source_manifest(tmp_path / "source", include_user_embeddings=True)
    eval_users = tmp_path / "users.jsonl"
    train_sequences = tmp_path / "train_sequences.jsonl"
    labels = tmp_path / "labels.jsonl"
    output_manifest = tmp_path / "direct_eval_manifest.json"

    _write_jsonl(eval_users, [{"user_id": "u2", "segment": "artifact"}])
    _write_jsonl(train_sequences, [{"user_id": "u2", "recent_positive_item_sequence": ["missing"], "recent_item_sequence": ["missing"]}])
    _write_jsonl(labels, [{"user_id": "u2", "parent_asin": "C", "label_binary": 1}])

    manifest = run_two_tower_dssm_direct_eval(
        source_index_manifest_path=source_manifest,
        eval_users_path=eval_users,
        train_sequences_path=train_sequences,
        label_paths=[labels],
        output_manifest_path=output_manifest,
        metric_ks=[1],
        enforce_venv=False,
    )

    assert manifest["query_user_count"] == 1
    assert manifest["queryless_user_count"] == 0
    assert manifest["query_source_counts"] == {"artifact_user_embedding": 1}
    assert manifest["candidate_generation_inputs"] == [
        str(train_sequences),
        str(tmp_path / "source" / "recall_index.jsonl"),
        str(tmp_path / "source" / "user_embeddings.jsonl"),
    ]
    assert manifest["metrics"]["recall_at_1"] == 1.0
    assert manifest["metrics"]["hit_rate_at_1"] == 1.0


def _write_source_manifest(root: Path, *, include_user_embeddings: bool = False) -> Path:
    root.mkdir()
    index = root / "recall_index.jsonl"
    item_vocab = root / "training_item_universe.jsonl"
    item_vocab_manifest = root / "two_tower_dssm_item_vocab_manifest.json"
    _write_jsonl(
        index,
        [
            {"parent_asin": "A", "embedding": [1.0, 0.0]},
            {"parent_asin": "B", "embedding": [1.0, 0.0]},
            {"parent_asin": "C", "embedding": [0.0, 1.0]},
        ],
    )
    user_embeddings = root / "user_embeddings.jsonl"
    if include_user_embeddings:
        _write_jsonl(user_embeddings, [{"user_id": "u2", "embedding": [0.0, 1.0]}])
    _write_jsonl(
        item_vocab,
        [
            {"parent_asin": "A", "item_id": "A"},
            {"parent_asin": "B", "item_id": "B"},
            {"parent_asin": "C", "item_id": "C"},
        ],
    )
    item_vocab_manifest.write_text(
        json.dumps(
            {
                "schema_version": "two_tower_item_vocab_v1",
                "item_vocab_path": str(item_vocab),
                "source_paths": {"canonical_interactions_train": str(root / "canonical_interactions.train.jsonl")},
                "item_count": 3,
                "metadata_join_added_items": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    source_manifest = {
        "schema_version": "two_tower_dssm_source_index_v1",
        "source": "two_tower_dssm",
        "canonical_source": "two_tower_dssm",
        "source_name": "two_tower_dssm",
        "variant": "dssm",
        "model_type": "dssm_two_tower_v1",
        "index_scope": "RECENT_2Y_DERIVED_INDEX",
        "source_status": "FULL_DERIVED_INDEX_DIAGNOSTIC",
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "embedding_path": str(index),
        "index_path": str(index),
        "item_vocab_manifest": str(item_vocab_manifest),
        "row_count": 3,
        "embedding_row_count": 3,
        "index_row_count": 3,
        "model_parameters": {},
    }
    if include_user_embeddings:
        source_manifest["user_embedding_path"] = str(user_embeddings)
        source_manifest["user_embedding_row_count"] = 1
    manifest = root / "source_index_manifest.json"
    manifest.write_text(json.dumps(source_manifest, ensure_ascii=False), encoding="utf-8")
    return manifest


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
