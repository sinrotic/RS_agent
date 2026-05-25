from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_lab.experiments.recall.select_pool500_aligned_eval_users import (
    build_pool500_offline_eval_users,
    select_pool500_aligned_eval_users,
)

pytestmark = pytest.mark.unit


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _write_clean_manifest(tmp_path: Path) -> Path:
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    train_sequences = clean_dir / "user_sequences.train.jsonl"
    all_interactions = clean_dir / "canonical_interactions.all.jsonl"
    valid = clean_dir / "canonical_interactions.valid.jsonl"
    test = clean_dir / "canonical_interactions.test.jsonl"
    _write_jsonl(
        train_sequences,
        [
            {"user_id": "u1", "recent_item_sequence": ["a", "b"], "recent_positive_item_sequence": ["a", "b"]},
            {"user_id": "u2", "recent_item_sequence": ["c"], "recent_positive_item_sequence": ["c"]},
            {"user_id": "u3", "recent_item_sequence": ["d", "e", "f"], "recent_positive_item_sequence": ["d", "e", "f"]},
            {"user_id": "u4", "recent_item_sequence": [], "recent_positive_item_sequence": []},
        ],
    )
    _write_jsonl(
        all_interactions,
        [
            {"user_id": "u1", "parent_asin": "a"},
            {"user_id": "u1", "parent_asin": "b"},
            {"user_id": "u3", "parent_asin": "d"},
        ],
    )
    _write_jsonl(
        valid,
        [
            {"user_id": "u1", "parent_asin": "hv1", "label_binary": 1, "split": "valid"},
            {"user_id": "u1", "parent_asin": "hv2", "label_binary": 1, "split": "valid"},
            {"user_id": "u2", "parent_asin": "skip_non_positive", "label_binary": 0, "split": "valid"},
            {"user_id": "missing_history", "parent_asin": "hv3", "label_binary": 1, "split": "valid"},
        ],
    )
    _write_jsonl(
        test,
        [
            {"user_id": "u3", "parent_asin": "ht1", "label_binary": 1, "split": "test"},
            {"user_id": "u4", "parent_asin": "insufficient", "label_binary": 1, "split": "test"},
        ],
    )
    manifest = clean_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "train_user_sequences_path": str(train_sequences),
                "all_interactions_path": str(all_interactions),
                "split_paths": {"valid": str(valid), "test": str(test)},
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _write_offline_clean_manifest(tmp_path: Path) -> Path:
    clean_dir = tmp_path / "offline_clean"
    clean_dir.mkdir()
    train_sequences = clean_dir / "user_sequences.train.jsonl"
    all_interactions = clean_dir / "canonical_interactions.all.jsonl"
    valid = clean_dir / "canonical_interactions.valid.jsonl"
    test = clean_dir / "canonical_interactions.test.jsonl"
    history_counts = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
    _write_jsonl(
        train_sequences,
        [
            {
                "user_id": f"u{index:02d}",
                "recent_item_sequence": [f"h{index}_{offset}" for offset in range(count)],
                "recent_positive_item_sequence": [f"h{index}_{offset}" for offset in range(count)],
                "recent_timestamp_sequence": [1_000 + index * 100 + offset for offset in range(count)],
            }
            for index, count in enumerate(history_counts, start=1)
        ],
    )
    _write_jsonl(
        all_interactions,
        [
            {"user_id": f"u{index:02d}", "parent_asin": f"h{index}_{offset}"}
            for index, count in enumerate(history_counts, start=1)
            for offset in range(count)
        ],
    )
    _write_jsonl(
        valid,
        [
            {
                "user_id": f"u{index:02d}",
                "parent_asin": f"valid_label_{index}",
                "label_binary": 1,
                "split": "valid",
                "timestamp": 10_000 + index,
                "item_interaction_count": index,
            }
            for index in range(1, 6)
        ],
    )
    _write_jsonl(
        test,
        [
            {
                "user_id": f"u{index:02d}",
                "parent_asin": f"test_label_{index}",
                "label_binary": 1,
                "split": "test",
                "timestamp": 20_000 + index,
                "item_interaction_count": 100 + index,
            }
            for index in range(6, 11)
        ],
    )
    manifest = clean_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "train_user_sequences_path": str(train_sequences),
                "all_interactions_path": str(all_interactions),
                "split_paths": {"valid": str(valid), "test": str(test)},
            }
        ),
        encoding="utf-8",
    )
    return manifest



def test_aligned_eval_selector_writes_diagnostic_manifest(tmp_path: Path) -> None:
    clean_manifest = _write_clean_manifest(tmp_path)

    manifest = select_pool500_aligned_eval_users(
        clean_manifest_path=clean_manifest,
        output_dir=tmp_path / "out",
        max_users=10,
        seed=7,
        min_train_history=2,
        positive_sample_size=1,
        enforce_venv=False,
    )

    persisted = json.loads((tmp_path / "out" / "aligned_eval_users_manifest.json").read_text(encoding="utf-8"))
    assert persisted == manifest
    assert manifest["schema_version"] == "pool500_aligned_eval_user_selection_v1"
    assert manifest["diagnostic_only"] is True
    assert manifest["eval_label_inputs_role"] == "evaluation_only_valid_test_labels_not_recall_generation_inputs"
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["full_pool500_ready_declared"] is False
    assert manifest["target_user_ids"] == manifest["eligible_user_ids"]
    assert {profile["user_id"] for profile in manifest["profiles"]} == {"u1", "u3"}
    profiles = {profile["user_id"]: profile for profile in manifest["profiles"]}
    assert profiles["u1"]["split"] == "valid"
    assert profiles["u1"]["positive_count"] == 2
    assert profiles["u1"]["positive_items_sample_count"] == 1
    assert profiles["u1"]["all_interaction_count"] == 2
    assert profiles["u3"]["split"] == "test"
    assert manifest["summary"]["selected_split_counts"] == {"test": 1, "valid": 1}
    assert manifest["summary"]["skipped_counts"] == {"insufficient_train_history": 1, "missing_train_history": 1}
    assert manifest["summary"]["label_summary"]["positive_counts"] == {"test": 2, "valid": 3}
    assert manifest["summary"]["label_summary"]["skipped_non_positive_counts"] == {"test": 0, "valid": 1}


def test_offline_eval_builder_writes_fixed_users_and_reproducible_manifest(tmp_path: Path) -> None:
    clean_manifest = _write_offline_clean_manifest(tmp_path)

    first = build_pool500_offline_eval_users(
        clean_manifest_path=clean_manifest,
        output_dir=tmp_path / "offline_out1",
        total_users=10,
        seed=17,
        min_train_history=1,
        enforce_venv=False,
    )
    second = build_pool500_offline_eval_users(
        clean_manifest_path=clean_manifest,
        output_dir=tmp_path / "offline_out2",
        total_users=10,
        seed=17,
        min_train_history=1,
        enforce_venv=False,
    )

    persisted = json.loads((tmp_path / "offline_out1" / "manifest.json").read_text(encoding="utf-8"))
    users_jsonl = [json.loads(line) for line in (tmp_path / "offline_out1" / "users.jsonl").read_text(encoding="utf-8").splitlines()]
    users = first["users"]
    user_ids = [user["user_id"] for user in users]

    assert persisted == first
    assert users_jsonl == users
    assert first["total_user_count"] == 10
    assert first["requested_total_user_count"] == 10
    assert first["segment_targets"] == {"hot": 4, "warm": 4, "cold-ish": 2}
    assert first["segment_counts"] == {"hot": 4, "warm": 4, "cold-ish": 2}
    assert len(user_ids) == len(set(user_ids))
    assert {user["segment"] for user in users} <= {"hot", "warm", "cold-ish"}
    assert all(user["history_count"] >= 1 for user in users)
    assert all(user["label_count"] >= 1 for user in users)
    assert all(user["history_start_time"] is not None and user["history_end_time"] is not None for user in users)
    assert all(user["label_start_time"] is not None and user["label_end_time"] is not None for user in users)
    assert first["split_contract"]["history_source"] == "train_user_sequences_only"
    assert first["split_contract"]["label_source"] == "valid_or_test_positive_rows_only"
    assert first["split_contract"]["history_window"]
    assert first["split_contract"]["label_window"]
    assert first["split_contract"]["split_policy"]
    assert first["leakage_policy"]["train_history_only"] is True
    assert first["leakage_policy"]["no_label_in_candidate_generation"] is True
    assert first["leakage_policy"]["no_oracle_candidate_injection"] is True
    assert first["metric_contract"]["recall"] == {
        "primary_metrics": ["Recall@500", "HitRate@500"],
        "auxiliary_metrics": ["Recall@50", "Recall@100"],
    }
    assert first["metric_contract"]["ranking"]["primary_metrics"] == ["NDCG@10", "MRR@10", "HitRate@10"]
    assert "auxiliary_metrics" in first["metric_contract"]["ranking"]
    assert first["metric_contract"]["ranking"]["pure_ranking_requires_fixed_candidate_pool"] is True
    assert first["candidate_pool_contract"]["recall_eval"] == "candidate_pool_may_vary_by_method"
    assert first["candidate_pool_contract"]["pure_ranking_eval"] == "candidate_pool_must_be_fixed"
    assert first["candidate_pool_contract"]["end_to_end_eval"] == "candidate_pool_and_ranker_may_vary"
    assert second["user_set_hash"] == first["user_set_hash"]
    assert [user["user_id"] for user in second["users"]] == user_ids



def test_aligned_eval_selector_honors_seed_and_max_users(tmp_path: Path) -> None:
    clean_manifest = _write_clean_manifest(tmp_path)

    first = select_pool500_aligned_eval_users(
        clean_manifest_path=clean_manifest,
        output_dir=tmp_path / "out1",
        max_users=1,
        seed=1,
        min_train_history=1,
        enforce_venv=False,
    )
    second = select_pool500_aligned_eval_users(
        clean_manifest_path=clean_manifest,
        output_dir=tmp_path / "out2",
        max_users=1,
        seed=1,
        min_train_history=1,
        enforce_venv=False,
    )

    assert len(first["profiles"]) == 1
    assert first["target_user_ids"] == second["target_user_ids"]
    assert first["selection_config"]["max_users"] == 1
    assert first["selection_config"]["seed"] == 1


def test_aligned_eval_selector_rejects_train_label_input(tmp_path: Path) -> None:
    clean_manifest = _write_clean_manifest(tmp_path)
    train_labels = tmp_path / "clean" / "canonical_interactions.train.jsonl"
    _write_jsonl(train_labels, [{"user_id": "u1", "parent_asin": "i1", "label_binary": 1, "split": "train"}])

    with pytest.raises(ValueError, match="only accepts valid/test label paths"):
        select_pool500_aligned_eval_users(
            clean_manifest_path=clean_manifest,
            output_dir=tmp_path / "out",
            label_paths=[train_labels],
            max_users=1,
            enforce_venv=False,
        )


def test_aligned_eval_selector_rejects_valid_as_train_history(tmp_path: Path) -> None:
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    valid_sequences = clean_dir / "user_sequences.valid.jsonl"
    valid = clean_dir / "canonical_interactions.valid.jsonl"
    _write_jsonl(valid_sequences, [{"user_id": "u1", "recent_positive_item_sequence": ["i1"]}])
    _write_jsonl(valid, [{"user_id": "u1", "parent_asin": "hv1", "label_binary": 1, "split": "valid"}])
    manifest_path = clean_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps({"train_user_sequences_path": str(valid_sequences), "split_paths": {"valid": str(valid)}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must not use valid/test label input"):
        select_pool500_aligned_eval_users(
            clean_manifest_path=manifest_path,
            output_dir=tmp_path / "out",
            max_users=1,
            enforce_venv=False,
        )
