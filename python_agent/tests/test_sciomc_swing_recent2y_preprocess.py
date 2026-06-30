from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_lab.experiments.recall.build_sciomc_swing_recent2y_preprocess import (
    FORBIDDEN_BUILDER_KEYS,
    build_sciomc_swing_recent2y_preprocess,
)

pytestmark = pytest.mark.unit


def test_sciomc_swing_preprocess_positive_dedup_chronological_and_in_universe(tmp_path: Path) -> None:
    recent_manifest = _write_recent_window_fixture(
        tmp_path,
        train_rows=[
            _row("u1", "i2", 20, True),
            _row("u1", "i1", 10, True),
            _row("u1", "i2", 30, True),
            _row("u1", "neg", 40, False),
            _row("u2", "i2", 5, True),
        ],
        valid_rows=[
            _row("u1", "i2", 50, True),
            _row("u1", "new_item", 51, True),
            _row("u3", "i1", 52, False),
            _row("u3", "i1", 53, True),
            _row("u3", "i1", 54, True),
        ],
        test_rows=[
            _row("u4", "i2", 70, True),
            _row("u4", "new_item", 71, True),
        ],
    )

    outputs = build_sciomc_swing_recent2y_preprocess(
        recent_window_manifest_path=recent_manifest,
        output_dir=tmp_path / "out",
        smoke_train_users=1,
        smoke_eval_users=1,
        enforce_venv=False,
    )

    formal_dir = tmp_path / "out" / "formal"
    train_rows = _read_jsonl(formal_dir / "user_sequences.train.jsonl")
    valid_rows = _read_jsonl(formal_dir / "swing_valid_in_universe.jsonl")
    test_rows = _read_jsonl(formal_dir / "swing_test_in_universe.jsonl")
    builder_manifest = json.loads((formal_dir / "swing_builder_train_manifest.json").read_text(encoding="utf-8"))

    assert train_rows == [
        {
            "user_id": "u1",
            "sequence_len": 2,
            "positive_sequence_len": 2,
            "recent_positive_item_sequence": ["i1", "i2"],
            "recent_positive_timestamp_sequence": [10, 20],
        },
        {
            "user_id": "u2",
            "sequence_len": 1,
            "positive_sequence_len": 1,
            "recent_positive_item_sequence": ["i2"],
            "recent_positive_timestamp_sequence": [5],
        },
    ]
    assert valid_rows == [
        {"user_id": "u1", "item_id": "i2", "timestamp": 50, "label": 1},
        {"user_id": "u3", "item_id": "i1", "timestamp": 53, "label": 1},
    ]
    assert test_rows == [{"user_id": "u4", "item_id": "i2", "timestamp": 70, "label": 1}]
    assert outputs["variants"]["formal"]["manifest"]["primary_outputs"] == {
        "train": str(formal_dir / "user_sequences.train.jsonl"),
        "valid": str(formal_dir / "swing_valid_in_universe.jsonl"),
        "test": str(formal_dir / "swing_test_in_universe.jsonl"),
    }
    assert outputs["variants"]["formal"]["stats"]["policy"]["sample_count_caps"] == "none_for_formal; smoke_debug_subset_only"
    assert outputs["variants"]["formal"]["stats"]["support"]["valid"]["filtered_out_of_universe_count"] == 1
    assert outputs["variants"]["formal"]["stats"]["support"]["valid"]["skipped_non_positive_count"] == 1
    assert outputs["variants"]["formal"]["stats"]["support"]["test"]["filtered_out_of_universe_count"] == 1
    assert builder_manifest["train_user_sequences_path"] == str(formal_dir / "user_sequences.train.jsonl")
    assert set(builder_manifest).isdisjoint(FORBIDDEN_BUILDER_KEYS)
    assert builder_manifest["metadata"]["sample_count_caps"] == "none"


def test_sciomc_swing_preprocess_writes_deterministic_smoke_and_formal_variants(tmp_path: Path) -> None:
    recent_manifest = _write_recent_window_fixture(
        tmp_path,
        train_rows=[
            _row("u3", "c", 30, True),
            _row("u1", "a", 10, True),
            _row("u1", "b", 20, True),
            _row("u2", "b", 10, True),
            _row("u2", "c", 20, True),
        ],
        valid_rows=[
            _row("v2", "c", 40, True),
            _row("v1", "a", 30, True),
            _row("v1", "z", 31, True),
        ],
        test_rows=[
            _row("t2", "c", 60, True),
            _row("t1", "b", 50, True),
        ],
    )

    outputs = build_sciomc_swing_recent2y_preprocess(
        recent_window_manifest_path=recent_manifest,
        output_dir=tmp_path / "out",
        smoke_train_users=2,
        smoke_eval_users=1,
        enforce_venv=False,
    )

    smoke_dir = tmp_path / "out" / "smoke"
    formal_dir = tmp_path / "out" / "formal"
    assert outputs["manifest"]["variants"] == {
        "smoke": str(smoke_dir / "manifest.json"),
        "formal": str(formal_dir / "manifest.json"),
    }
    assert _read_jsonl(smoke_dir / "user_sequences.train.jsonl") == [
        {
            "user_id": "u1",
            "sequence_len": 2,
            "positive_sequence_len": 2,
            "recent_positive_item_sequence": ["a", "b"],
            "recent_positive_timestamp_sequence": [10, 20],
        },
        {
            "user_id": "u2",
            "sequence_len": 2,
            "positive_sequence_len": 2,
            "recent_positive_item_sequence": ["b", "c"],
            "recent_positive_timestamp_sequence": [10, 20],
        },
    ]
    assert _read_jsonl(smoke_dir / "swing_valid_in_universe.jsonl") == [
        {"user_id": "v1", "item_id": "a", "timestamp": 30, "label": 1},
    ]
    assert _read_jsonl(smoke_dir / "swing_test_in_universe.jsonl") == [
        {"user_id": "t1", "item_id": "b", "timestamp": 50, "label": 1},
    ]
    assert len(_read_jsonl(formal_dir / "user_sequences.train.jsonl")) == 3
    assert json.loads((smoke_dir / "manifest.json").read_text(encoding="utf-8"))["sampling_policy"]["type"] == "smoke"
    assert json.loads((formal_dir / "manifest.json").read_text(encoding="utf-8"))["sampling_policy"]["type"] == "formal"


def test_sciomc_swing_builder_manifests_do_not_expose_forbidden_keys(tmp_path: Path) -> None:
    recent_manifest = _write_recent_window_fixture(
        tmp_path,
        train_rows=[_row("u1", "i1", 10, True), _row("u1", "i2", 20, True)],
        valid_rows=[_row("u2", "i1", 30, True)],
        test_rows=[_row("u3", "i2", 40, True)],
    )

    build_sciomc_swing_recent2y_preprocess(
        recent_window_manifest_path=recent_manifest,
        output_dir=tmp_path / "out",
        enforce_venv=False,
    )

    for variant in ("smoke", "formal"):
        builder_manifest = json.loads((tmp_path / "out" / variant / "swing_builder_train_manifest.json").read_text(encoding="utf-8"))
        flattened = json.dumps(builder_manifest, ensure_ascii=False)
        for forbidden_key in FORBIDDEN_BUILDER_KEYS:
            assert f'"{forbidden_key}"' not in flattened
        assert Path(builder_manifest["train_user_sequences_path"]).name == "user_sequences.train.jsonl"
        assert variant in Path(builder_manifest["train_user_sequences_path"]).parts


def _write_recent_window_fixture(
    root: Path,
    *,
    train_rows: list[dict[str, object]],
    valid_rows: list[dict[str, object]],
    test_rows: list[dict[str, object]],
) -> Path:
    data_dir = root / "recent"
    data_dir.mkdir()
    train_path = data_dir / "canonical_interactions.train.jsonl"
    valid_path = data_dir / "canonical_interactions.valid.jsonl"
    test_path = data_dir / "canonical_interactions.test.jsonl"
    _write_jsonl(train_path, train_rows)
    _write_jsonl(valid_path, valid_rows)
    _write_jsonl(test_path, test_rows)
    manifest_path = data_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "recent_window_2y_1m_3m_v1",
                "split_paths": {
                    "train": str(train_path),
                    "valid": str(valid_path),
                    "test": str(test_path),
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def _row(user_id: str, item_id: str, timestamp: int, label_binary: bool) -> dict[str, object]:
    return {
        "user_id": user_id,
        "parent_asin": item_id,
        "timestamp": timestamp,
        "label_binary": label_binary,
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
