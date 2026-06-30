from __future__ import annotations

import json
from pathlib import Path

from rs_core.common.io import write_json, write_jsonl
from rs_lab.experiments.recall.build_sciomc_twotower_recent2y_preprocess import build_sciomc_twotower_recent2y_preprocess


def test_sciomc_twotower_recent2y_preprocess_builds_smoke_and_formal(tmp_path: Path) -> None:
    data_dir = tmp_path / "recent2y"
    data_dir.mkdir()
    train = data_dir / "canonical_interactions.train.jsonl"
    valid = data_dir / "canonical_interactions.valid.jsonl"
    test = data_dir / "canonical_interactions.test.jsonl"
    items = data_dir / "canonical_items.jsonl"
    sequences = data_dir / "user_sequences.train.jsonl"
    manifest_path = data_dir / "manifest.json"

    train_rows = [
        {"user_id": "u1", "parent_asin": "i1", "timestamp": 10, "label_binary": True, "label_strong": True},
        {"user_id": "u1", "parent_asin": "i2", "timestamp": 20, "label_binary": True, "label_strong": True},
        {"user_id": "u1", "parent_asin": "i3", "timestamp": 30, "label_binary": True, "label_strong": True},
        {"user_id": "u2", "parent_asin": "i2", "timestamp": 11, "label_binary": True, "label_strong": True},
        {"user_id": "u2", "parent_asin": "i3", "timestamp": 21, "label_binary": True, "label_strong": True},
        {"user_id": "u2", "parent_asin": "i4", "timestamp": 31, "label_binary": True, "label_strong": True},
    ]
    write_jsonl(train, train_rows)
    write_jsonl(valid, [{"user_id": "u3", "parent_asin": "i1", "timestamp": 40, "label_binary": True}])
    write_jsonl(test, [{"user_id": "u4", "parent_asin": "i5", "timestamp": 50, "label_binary": True}])
    write_jsonl(
        items,
        [
            {"parent_asin": item_id, "item_id": item_id, "title_clean": f"Title {item_id}"}
            for item_id in ["i1", "i2", "i3", "i4"]
        ],
    )
    write_jsonl(
        sequences,
        [
            {
                "user_id": "u1",
                "recent_item_sequence": ["i1", "i2", "i3"],
                "recent_timestamp_sequence": [10, 20, 30],
                "recent_positive_item_sequence": ["i1", "i2", "i3"],
                "recent_positive_timestamp_sequence": [10, 20, 30],
                "recent_strong_positive_item_sequence": ["i1", "i2", "i3"],
                "recent_strong_positive_timestamp_sequence": [10, 20, 30],
            },
            {
                "user_id": "u2",
                "recent_item_sequence": ["i2", "i3", "i4"],
                "recent_timestamp_sequence": [11, 21, 31],
                "recent_positive_item_sequence": ["i2", "i3", "i4"],
                "recent_positive_timestamp_sequence": [11, 21, 31],
                "recent_strong_positive_item_sequence": ["i2", "i3", "i4"],
                "recent_strong_positive_timestamp_sequence": [11, 21, 31],
            },
        ],
    )
    write_json(
        manifest_path,
        {
            "schema_version": "recent_window_2y_1m_3m_v1",
            "split_paths": {"train": str(train), "valid": str(valid), "test": str(test)},
            "train_user_sequences_path": str(sequences),
            "canonical_items_path": str(items),
        },
    )
    formal_vocab = tmp_path / "formal_vocab.jsonl"
    formal_vocab_manifest = tmp_path / "formal_vocab_manifest.json"
    write_jsonl(formal_vocab, [{"parent_asin": item_id} for item_id in ["i1", "i2", "i3", "i4"]])
    write_json(formal_vocab_manifest, {"schema_version": "two_tower_item_vocab_v1", "item_vocab_path": str(formal_vocab), "item_count": 4})

    outputs = build_sciomc_twotower_recent2y_preprocess(
        recent_window_manifest_path=manifest_path,
        formal_item_vocab_manifest_path=formal_vocab_manifest,
        output_dir=tmp_path / "out",
        smoke_users=1,
        overwrite=True,
        enforce_venv=False,
    )

    top = json.loads(Path(outputs["manifest_path"]).read_text(encoding="utf-8"))
    smoke = json.loads(Path(outputs["smoke_manifest_path"]).read_text(encoding="utf-8"))
    formal = json.loads(Path(outputs["formal_manifest_path"]).read_text(encoding="utf-8"))

    assert top["policy"]["methodology"] == "sciomc_time_split_best_practice"
    assert top["policy"]["old_dataset_count_limits_used"] is False
    assert smoke["dataset_tier"] == "smoke"
    assert smoke["policy"]["role"] == "smoke_only_not_formal"
    assert smoke["policy"]["sample_count_caps"] == {"smoke_users": 1}
    assert smoke["counts"]["selected_user_count"] == 1
    assert smoke["counts"]["item_vocab_count"] == 3
    assert Path(smoke["paths"]["item_vocab_manifest"]).name == "two_tower_item_vocab_minfreq1_manifest.json"

    assert formal["dataset_tier"] == "formal"
    assert formal["policy"]["role"] == "formal_training_input"
    assert formal["policy"]["sample_count_caps"] == "none"
    assert formal["policy"]["old_dataset_count_limits_used"] is False
    assert formal["paths"]["canonical_interactions_train"] == str(train)
    assert formal["paths"]["canonical_interactions_valid"] == str(valid)
    assert formal["paths"]["canonical_interactions_test"] == str(test)
    assert formal["paths"]["item_vocab_manifest"] == str(formal_vocab_manifest)
