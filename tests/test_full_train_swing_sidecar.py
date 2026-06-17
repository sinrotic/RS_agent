from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_core.recsys.candidate_merge import load_swing_recall_sidecar
from rs_lab.experiments.recall import build_full_train_swing_sidecar as swing_sidecar

pytestmark = pytest.mark.unit


def test_full_train_swing_sidecar_writes_edges_and_manifests(tmp_path: Path) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["seed", "item_b", "item_c"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["seed", "item_b"]},
            {"user_id": "u3", "recent_positive_item_sequence": ["seed", "item_c"]},
        ],
    )
    output_dir = tmp_path / "out"

    manifest = swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=output_dir,
        max_item_user_freq=10,
        max_user_items=10,
        min_pair_support=2,
        per_seed_top_k=1,
        min_score=0.0,
        min_free_bytes=0,
        enforce_venv=False,
    )

    edges = _read_jsonl(output_dir / "swing_recall_edges.jsonl")
    seed_edges = [edge for edge in edges if edge["src_item"] == "seed"]
    assert len(seed_edges) == 1
    assert seed_edges[0] == {
        "src_item": "seed",
        "dst_item": "item_b",
        "score": 1.090909,
        "rank": 1,
        "source": "swing_recall",
    }
    assert all(set(edge) == {"src_item", "dst_item", "score", "rank", "source"} for edge in edges)

    source_manifest = json.loads((output_dir / "source_index_manifest.json").read_text(encoding="utf-8"))
    selection_manifest = json.loads((output_dir / "custom_index_selection_manifest.json").read_text(encoding="utf-8"))
    no_holdout_audit = json.loads((output_dir / "no_holdout_audit.json").read_text(encoding="utf-8"))
    resource_audit = json.loads((output_dir / "resource_audit.json").read_text(encoding="utf-8"))

    assert manifest == source_manifest
    for payload in [source_manifest, selection_manifest, no_holdout_audit]:
        assert payload["index_scope"] == "FULL_DERIVED_INDEX"
        assert payload["train_only"] is True
        assert payload["candidate_generation_allowed"] is False
        assert payload["ranking_input_replacement_allowed"] is False
        assert payload["pool1000_allowed"] is False
    assert selection_manifest["ranking_input_replacement"] is False
    assert selection_manifest["declared_inputs"] == [str((tmp_path / "clean" / "user_sequences.train.jsonl").resolve())]
    assert no_holdout_audit["read_files"] == [str((tmp_path / "clean" / "user_sequences.train.jsonl").resolve())]
    assert no_holdout_audit["valid_test_holdout_usage"] == "not_read"
    assert no_holdout_audit["uses_all_window"] is False
    assert no_holdout_audit["uses_label"] is False
    assert no_holdout_audit["uses_canonical_interactions"] is False
    assert source_manifest["input_contract"]["allowed_inputs"] == ["clean_manifest.train_user_sequences_path"]
    assert source_manifest["lifecycle_stage"] == "builder_complete"
    assert source_manifest["provenance"]["train_user_sequences_signature"]["sha256"]
    assert source_manifest["parameters"]["min_pair_support"] == 2
    assert source_manifest["partial_invalidation_keys"] == [
        "provenance.clean_manifest_signature.sha256",
        "provenance.train_user_sequences_signature.sha256",
        "parameters",
    ]
    assert resource_audit["edge_count"] == len(edges)
    assert resource_audit["shard_audit"]["strategy"] == "src_item_prefix_2_audit_only"


def test_full_train_swing_sidecar_datawhale_standard_formula(tmp_path: Path) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["seed", "item_b", "x"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["seed", "item_b", "y"]},
            {"user_id": "u3", "recent_positive_item_sequence": ["seed", "item_c"]},
        ],
    )
    output_dir = tmp_path / "out"

    swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=output_dir,
        max_item_user_freq=10,
        max_user_items=10,
        min_pair_support=2,
        per_seed_top_k=10,
        min_score=0.0,
        score_mode=swing_sidecar.SCORE_MODE_DATAWHALE_STANDARD,
        alpha=1.0,
        min_free_bytes=0,
        enforce_venv=False,
    )

    edges = _read_jsonl(output_dir / "swing_recall_edges.jsonl")
    seed_edges = {edge["dst_item"]: edge for edge in edges if edge["src_item"] == "seed"}
    assert seed_edges["item_b"]["score"] == 0.111111
    assert "item_c" not in seed_edges

    source_manifest = json.loads((output_dir / "source_index_manifest.json").read_text(encoding="utf-8"))
    resource_audit = json.loads((output_dir / "resource_audit.json").read_text(encoding="utf-8"))
    assert source_manifest["parameters"]["score_mode"] == swing_sidecar.SCORE_MODE_DATAWHALE_STANDARD
    assert source_manifest["parameters"]["alpha"] == 1.0
    assert source_manifest["parameters"]["min_user_items"] == 2
    assert resource_audit["build_audit"]["user_weight_mode"] == swing_sidecar.USER_WEIGHT_MODE
    assert resource_audit["build_audit"]["common_user_pair_mode"] == swing_sidecar.COMMON_USER_PAIR_MODE
    assert resource_audit["build_audit"]["formula_reference"] == "datawhale_swing"
    assert resource_audit["build_audit"]["standard_user_pair_contribution_count"] > 0


def test_full_train_swing_sidecar_min_user_items_audit(tmp_path: Path) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "too_cold", "recent_positive_item_sequence": ["a", "b"]},
            {"user_id": "dedup_cold", "recent_positive_item_sequence": ["seed", "item_b", "seed"]},
            {"user_id": "u1", "recent_positive_item_sequence": ["seed", "item_b", "x"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["seed", "item_b", "y"]},
        ],
    )
    output_dir = tmp_path / "out"

    manifest = swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=output_dir,
        max_item_user_freq=10,
        max_user_items=10,
        min_pair_support=2,
        per_seed_top_k=10,
        min_score=0.0,
        score_mode=swing_sidecar.SCORE_MODE_DATAWHALE_STANDARD,
        alpha=1.0,
        min_user_items=3,
        min_free_bytes=0,
        enforce_venv=False,
    )

    resource_audit = json.loads((output_dir / "resource_audit.json").read_text(encoding="utf-8"))
    load_audit = resource_audit["load_audit"]
    assert manifest["parameters"]["min_user_items"] == 3
    assert manifest["parameters"]["score_mode"] == swing_sidecar.SCORE_MODE_DATAWHALE_STANDARD
    assert load_audit["raw_user_count_seen"] == 4
    assert load_audit["raw_user_count_with_min_positive_items"] == 3
    assert load_audit["raw_user_count_with_two_positive_items"] == 4
    assert load_audit["user_filter_stage"] == "after_item_filter"
    assert load_audit["retained_user_count_before_item_filter"] == 4
    assert load_audit["retained_user_count"] == 2
    assert load_audit["skipped_user_count_below_min_raw_items"] == 1
    assert load_audit["skipped_user_count_below_min_retained_unique_items"] == 2
    assert load_audit["skipped_user_count_below_min_after_item_filter"] == 2


def test_full_train_swing_sidecar_filters_dst_by_train_positive_user_count(tmp_path: Path) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["seed", "stable_dst", "rare_dst"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["seed", "stable_dst"]},
        ],
    )
    output_dir = tmp_path / "out"

    manifest = swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=output_dir,
        max_item_user_freq=10,
        max_user_items=10,
        min_pair_support=1,
        per_seed_top_k=10,
        min_score=0.0,
        min_dst_item_positive_user_count=2,
        min_free_bytes=0,
        enforce_venv=False,
    )

    edges = _read_jsonl(output_dir / "swing_recall_edges.jsonl")
    seed_dsts = {edge["dst_item"] for edge in edges if edge["src_item"] == "seed"}
    assert seed_dsts == {"stable_dst"}
    assert "rare_dst" not in {edge["dst_item"] for edge in edges}
    resource_audit = json.loads((output_dir / "resource_audit.json").read_text(encoding="utf-8"))
    assert manifest["parameters"]["min_dst_item_positive_user_count"] == 2
    assert resource_audit["item_filter_audit"]["dst_eligible_item_count"] == 2
    assert resource_audit["item_filter_audit"]["dropped_dst_item_count_below_min"] == 1
    assert "dst_eligible_items" not in resource_audit["item_filter_audit"]



def test_full_train_swing_sidecar_keeps_src_dst_filter_directional(tmp_path: Path) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["seed", "common_dst"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["seed", "common_dst"]},
            {"user_id": "u3", "recent_positive_item_sequence": ["common_dst", "helper"]},
        ],
    )
    output_dir = tmp_path / "out"

    swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=output_dir,
        max_item_user_freq=10,
        max_user_items=10,
        min_pair_support=1,
        per_seed_top_k=10,
        min_score=0.0,
        min_src_item_positive_user_count=3,
        min_dst_item_positive_user_count=2,
        min_free_bytes=0,
        enforce_venv=False,
    )

    edges = _read_jsonl(output_dir / "swing_recall_edges.jsonl")
    assert any(edge["src_item"] == "common_dst" and edge["dst_item"] == "seed" for edge in edges)
    assert not any(edge["src_item"] == "seed" for edge in edges)
    resource_audit = json.loads((output_dir / "resource_audit.json").read_text(encoding="utf-8"))
    assert resource_audit["build_audit"]["src_item_filter_applied_before_edge_write"] is True
    assert resource_audit["build_audit"]["dst_item_filter_applied_before_edge_write"] is True
    assert resource_audit["item_filter_audit"]["src_eligible_item_count"] == 1
    assert resource_audit["item_filter_audit"]["dst_eligible_item_count"] == 2



def test_full_train_swing_sidecar_user_filter_after_item_filter_audit(tmp_path: Path) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["seed", "stable", "rare"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["seed", "stable"]},
            {"user_id": "u3", "recent_positive_item_sequence": ["seed", "stable"]},
        ],
    )
    output_dir = tmp_path / "out"

    swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=output_dir,
        max_item_user_freq=10,
        max_user_items=10,
        min_pair_support=1,
        per_seed_top_k=10,
        min_score=0.0,
        min_src_item_positive_user_count=2,
        min_dst_item_positive_user_count=2,
        min_user_items=3,
        min_free_bytes=0,
        enforce_venv=False,
    )

    resource_audit = json.loads((output_dir / "resource_audit.json").read_text(encoding="utf-8"))
    load_audit = resource_audit["load_audit"]
    assert load_audit["user_filter_stage"] == "after_item_filter"
    assert load_audit["retained_user_count_before_item_filter"] == 3
    assert load_audit["retained_user_count"] == 0
    assert load_audit["skipped_user_count_below_min_after_item_filter"] == 3
    assert load_audit["retained_item_count_bucket_distribution_after_item_filter"] == {"2": 3}
    assert resource_audit["user_count_before_item_filter"] == 3
    assert resource_audit["user_count"] == 0


def test_full_train_swing_sidecar_pre_filters_users_before_item_count(tmp_path: Path) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "single_seed", "recent_positive_item_sequence": ["seed"]},
            {"user_id": "u1", "recent_positive_item_sequence": ["seed", "dst"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["dst", "helper"]},
        ],
    )

    no_pre_dir = tmp_path / "no_pre"
    swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=no_pre_dir,
        max_item_user_freq=10,
        max_user_items=10,
        min_pair_support=1,
        per_seed_top_k=10,
        min_score=0.0,
        min_src_item_positive_user_count=2,
        min_dst_item_positive_user_count=2,
        min_free_bytes=0,
        enforce_venv=False,
    )

    pre_dir = tmp_path / "pre"
    swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=pre_dir,
        max_item_user_freq=10,
        max_user_items=10,
        min_pair_support=1,
        per_seed_top_k=10,
        min_score=0.0,
        min_src_item_positive_user_count=2,
        min_dst_item_positive_user_count=2,
        pre_filter_users_before_item_count=True,
        min_free_bytes=0,
        enforce_venv=False,
    )

    no_pre_edges = _read_jsonl(no_pre_dir / "swing_recall_edges.jsonl")
    pre_edges = _read_jsonl(pre_dir / "swing_recall_edges.jsonl")
    assert any(edge["src_item"] == "seed" and edge["dst_item"] == "dst" for edge in no_pre_edges)
    assert not any(edge["src_item"] == "seed" for edge in pre_edges)
    pre_audit = json.loads((pre_dir / "resource_audit.json").read_text(encoding="utf-8"))
    assert pre_audit["load_audit"]["pre_user_filter_applied_before_item_count"] is True
    assert pre_audit["load_audit"]["skipped_user_count_by_pre_item_count_filter"] == 1
    assert pre_audit["user_count_raw_loaded"] == 3
    assert pre_audit["user_count_before_item_filter"] == 2



def test_full_train_swing_sidecar_can_disable_hard_post_item_user_filter(tmp_path: Path) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["seed", "rare"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["seed", "stable"]},
            {"user_id": "u3", "recent_positive_item_sequence": ["stable", "helper"]},
        ],
    )
    output_dir = tmp_path / "out"

    swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=output_dir,
        max_item_user_freq=10,
        max_user_items=10,
        min_pair_support=1,
        per_seed_top_k=10,
        min_score=0.0,
        min_src_item_positive_user_count=2,
        min_dst_item_positive_user_count=2,
        disable_post_item_user_filter=True,
        min_free_bytes=0,
        enforce_venv=False,
    )

    resource_audit = json.loads((output_dir / "resource_audit.json").read_text(encoding="utf-8"))
    load_audit = resource_audit["load_audit"]
    item_filter_audit = resource_audit["item_filter_audit"]
    assert load_audit["post_item_user_filter_enabled"] is False
    assert load_audit["retained_user_count"] == 3
    assert load_audit["skipped_user_count_below_min_after_item_filter"] == 2
    assert item_filter_audit["apply_post_item_user_filter"] is False


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"min_src_item_positive_user_count": 0}, "min_src_item_positive_user_count"),
        ({"min_dst_item_positive_user_count": 0}, "min_dst_item_positive_user_count"),
    ],
)
def test_full_train_swing_sidecar_rejects_non_positive_item_count_filters(
    tmp_path: Path, kwargs: dict[str, int], message: str
) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]},
        ],
    )

    with pytest.raises(ValueError, match=message):
        swing_sidecar.build_full_train_swing_sidecar(
            clean_manifest_path=clean_manifest,
            output_dir=tmp_path / "out",
            min_free_bytes=0,
            enforce_venv=False,
            **kwargs,
        )



def test_full_train_swing_sidecar_datawhale_standard_drops_single_common_user_pairs(tmp_path: Path) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["seed", "item_b"]},
        ],
    )
    output_dir = tmp_path / "out"

    swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=output_dir,
        max_item_user_freq=10,
        max_user_items=10,
        min_pair_support=1,
        per_seed_top_k=10,
        min_score=0.0,
        score_mode=swing_sidecar.SCORE_MODE_DATAWHALE_STANDARD,
        alpha=1.0,
        min_free_bytes=0,
        enforce_venv=False,
    )

    assert _read_jsonl(output_dir / "swing_recall_edges.jsonl") == []
    resource_audit = json.loads((output_dir / "resource_audit.json").read_text(encoding="utf-8"))
    assert resource_audit["build_audit"]["supported_pair_count"] == 0
    assert resource_audit["build_audit"]["standard_user_pair_contribution_count"] == 0


def test_full_train_swing_sidecar_rejects_min_user_items_above_max_user_items(tmp_path: Path) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["a", "b", "c"]},
        ],
    )

    with pytest.raises(ValueError, match="min_user_items"):
        swing_sidecar.build_full_train_swing_sidecar(
            clean_manifest_path=clean_manifest,
            output_dir=tmp_path / "out",
            max_user_items=2,
            min_user_items=3,
            min_free_bytes=0,
            enforce_venv=False,
        )


def test_full_train_swing_sidecar_drops_hot_items(tmp_path: Path) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["hot", "item_a"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["hot", "item_a"]},
            {"user_id": "u3", "recent_positive_item_sequence": ["hot", "item_b"]},
        ],
    )
    output_dir = tmp_path / "out"

    swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=output_dir,
        max_item_user_freq=2,
        max_user_items=10,
        min_pair_support=1,
        per_seed_top_k=10,
        min_score=0.0,
        min_free_bytes=0,
        enforce_venv=False,
    )

    edges = _read_jsonl(output_dir / "swing_recall_edges.jsonl")
    dropped = json.loads((output_dir / "dropped_hot_items.json").read_text(encoding="utf-8"))
    assert dropped["items"] == [{"item_id": "hot", "train_user_freq": 3}]
    assert all(edge["src_item"] != "hot" and edge["dst_item"] != "hot" for edge in edges)


def test_full_train_swing_sidecar_resolves_clean_manifest_path_from_repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    data_dir = repo_root / "data" / "processed" / "amazon_2023_recall_clean_full"
    data_dir.mkdir(parents=True)
    train_path = data_dir / "user_sequences.train.jsonl"
    _write_jsonl(train_path, [{"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]}])
    manifest_dir = data_dir / "manifests"
    manifest_dir.mkdir()
    clean_manifest = manifest_dir / "manifest.json"
    clean_manifest.write_text(
        json.dumps({"train_user_sequences_path": "data/processed/amazon_2023_recall_clean_full/user_sequences.train.jsonl"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(swing_sidecar, "ROOT", repo_root)

    manifest = swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=tmp_path / "out",
        min_pair_support=1,
        min_free_bytes=0,
        enforce_venv=False,
    )

    assert manifest["train_user_sequences_path"] == str(train_path.resolve())


def test_full_train_swing_sidecar_stable_manifest_content_across_output_dirs(tmp_path: Path) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["seed", "item_b", "item_c"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["seed", "item_b"]},
        ],
    )

    first = swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=tmp_path / "out_first",
        min_pair_support=1,
        min_free_bytes=0,
        enforce_venv=False,
    )
    second = swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=tmp_path / "out_second",
        min_pair_support=1,
        min_free_bytes=0,
        enforce_venv=False,
    )

    assert first == second
    first_resource = json.loads((tmp_path / "out_first" / "resource_audit.json").read_text(encoding="utf-8"))
    second_resource = json.loads((tmp_path / "out_second" / "resource_audit.json").read_text(encoding="utf-8"))
    assert first_resource == second_resource
    assert first["generated_at"] == "excluded_from_canonical_sha"
    assert first["output_dir"] == "excluded_from_canonical_sha"
    assert first["runtime_seconds"] == "excluded_from_canonical_sha"
    assert first_resource["disk_free_bytes_start"] == "excluded_from_canonical_sha"
    assert first_resource["disk_free_bytes_end"] == "excluded_from_canonical_sha"


def test_full_train_swing_sidecar_allows_forbidden_metadata_but_reads_train_only(tmp_path: Path) -> None:
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    train_path = clean_dir / "user_sequences.train.jsonl"
    _write_jsonl(train_path, [{"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]}])
    clean_manifest = clean_dir / "manifest.json"
    clean_manifest.write_text(
        json.dumps(
            {
                "status": "PASS",
                "train_user_sequences_path": str(train_path),
                "user_sequences_path": str(clean_dir / "user_sequences.jsonl"),
                "outputs": {"canonical_interactions_path": str(clean_dir / "canonical_interactions.jsonl")},
            }
        ),
        encoding="utf-8",
    )

    swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=tmp_path / "out",
        min_free_bytes=0,
        enforce_venv=False,
    )

    no_holdout_audit = json.loads((tmp_path / "out" / "no_holdout_audit.json").read_text(encoding="utf-8"))
    assert no_holdout_audit["read_files"] == [str(train_path.resolve())]
    assert no_holdout_audit["uses_valid"] is False
    assert no_holdout_audit["uses_test"] is False
    assert no_holdout_audit["uses_holdout"] is False
    assert no_holdout_audit["uses_label"] is False


def test_full_train_swing_sidecar_ignores_outputs_train_sequence_fallback(tmp_path: Path) -> None:
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    train_path = clean_dir / "user_sequences.train.jsonl"
    _write_jsonl(train_path, [{"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]}])
    clean_manifest = clean_dir / "manifest.json"
    clean_manifest.write_text(json.dumps({"status": "PASS", "outputs": {"train_user_sequences_path": str(train_path)}}), encoding="utf-8")

    with pytest.raises(ValueError, match="train_user_sequences_path"):
        swing_sidecar.build_full_train_swing_sidecar(
            clean_manifest_path=clean_manifest,
            output_dir=tmp_path / "out",
            min_free_bytes=0,
            enforce_venv=False,
        )


def test_full_train_swing_sidecar_manifest_requires_train_sequence_path(tmp_path: Path) -> None:
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    clean_manifest = clean_dir / "manifest.json"
    clean_manifest.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

    with pytest.raises(ValueError, match="train_user_sequences_path"):
        swing_sidecar.build_full_train_swing_sidecar(
            clean_manifest_path=clean_manifest,
            output_dir=tmp_path / "out",
            min_free_bytes=0,
            enforce_venv=False,
        )


def test_full_train_swing_sidecar_rejects_holdout_path(tmp_path: Path) -> None:
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    train_path = clean_dir / "user_sequences.valid.jsonl"
    _write_jsonl(train_path, [{"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]}])
    clean_manifest = clean_dir / "manifest.json"
    clean_manifest.write_text(json.dumps({"train_user_sequences_path": str(train_path)}), encoding="utf-8")

    with pytest.raises(ValueError, match="user_sequences.train.jsonl|Forbidden"):
        swing_sidecar.build_full_train_swing_sidecar(
            clean_manifest_path=clean_manifest,
            output_dir=tmp_path / "out",
            min_free_bytes=0,
            enforce_venv=False,
        )


@pytest.mark.parametrize("forbidden_part", ["valid", "test", "holdout", "label", "all_window"])
def test_full_train_swing_sidecar_rejects_forbidden_train_sequence_directories(tmp_path: Path, forbidden_part: str) -> None:
    clean_dir = tmp_path / forbidden_part / "clean"
    clean_dir.mkdir(parents=True)
    train_path = clean_dir / "user_sequences.train.jsonl"
    _write_jsonl(train_path, [{"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]}])
    clean_manifest = clean_dir / "manifest.json"
    clean_manifest.write_text(json.dumps({"train_user_sequences_path": str(train_path)}), encoding="utf-8")

    with pytest.raises(ValueError, match="Forbidden input/output path"):
        swing_sidecar.build_full_train_swing_sidecar(
            clean_manifest_path=clean_manifest,
            output_dir=tmp_path / "out",
            min_free_bytes=0,
            enforce_venv=False,
        )


@pytest.mark.parametrize(
    ("manifest_key", "path_name"),
    [
        ("user_sequences_path", "user_sequences.jsonl"),
        ("all_window_user_sequences_path", "all_window/user_sequences.train.jsonl"),
        ("valid_user_sequences_path", "user_sequences.valid.jsonl"),
        ("test_user_sequences_path", "user_sequences.test.jsonl"),
        ("holdout_user_sequences_path", "holdout/user_sequences.train.jsonl"),
        ("label_path", "labels.jsonl"),
    ],
)
def test_full_train_swing_sidecar_allows_forbidden_manifest_metadata_without_reading_it(
    tmp_path: Path, manifest_key: str, path_name: str
) -> None:
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    train_path = clean_dir / "user_sequences.train.jsonl"
    _write_jsonl(train_path, [{"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]}])
    clean_manifest = clean_dir / "manifest.json"
    clean_manifest.write_text(
        json.dumps({"status": "PASS", "train_user_sequences_path": str(train_path), manifest_key: str(clean_dir / path_name)}),
        encoding="utf-8",
    )

    swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=tmp_path / "out",
        min_free_bytes=0,
        enforce_venv=False,
    )

    no_holdout_audit = json.loads((tmp_path / "out" / "no_holdout_audit.json").read_text(encoding="utf-8"))
    assert no_holdout_audit["read_files"] == [str(train_path.resolve())]
    assert no_holdout_audit["valid_test_holdout_usage"] == "not_read"


def test_full_train_swing_sidecar_manifest_exposes_lifecycle_provenance_and_status(tmp_path: Path) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["seed", "item_b"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["seed", "item_c"]},
        ],
    )

    manifest = swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=tmp_path / "out",
        min_pair_support=1,
        min_free_bytes=0,
        enforce_venv=False,
    )

    assert manifest["status"] == "PASS"
    assert manifest["lifecycle_stage"] == "builder_complete"
    assert manifest["provenance"]["clean_manifest_signature"]["sha256"]
    assert manifest["provenance"]["train_user_sequences_signature"]["sha256"]
    assert manifest["input_contract"]["allowed_inputs"] == ["clean_manifest.train_user_sequences_path"]
    assert manifest["input_contract"]["declared_inputs"] == [manifest["train_user_sequences_path"]]


def test_load_swing_recall_sidecar_accepts_formal_source_index(tmp_path: Path) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["seed", "item_b"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["seed", "item_b"]},
        ],
    )
    output_dir = tmp_path / "out"
    swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=output_dir,
        min_pair_support=1,
        min_free_bytes=0,
        enforce_venv=False,
    )

    loaded = load_swing_recall_sidecar(output_dir / "source_index_manifest.json")

    assert loaded["seed"][0].item_id == "item_b"
    assert loaded["seed"][0].source == "swing_recall"


def test_load_swing_recall_sidecar_rejects_target_slice_diagnostic_manifest(tmp_path: Path) -> None:
    manifest_path = _write_loader_manifest_fixture(tmp_path, source_status="TARGET_SLICE_DIAGNOSTIC")

    with pytest.raises(ValueError, match="TARGET_SLICE_DIAGNOSTIC"):
        load_swing_recall_sidecar(manifest_path)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"partial_invalidation_keys": ["provenance.clean_manifest_signature.sha256"]}, "partial invalidation"),
        ({"input_contract": {"allowed_inputs": ["clean_manifest.user_sequences_path"], "train_user_sequences_path": "user_sequences.train.jsonl", "declared_inputs": ["user_sequences.train.jsonl"]}}, "train_user_sequences_path only"),
        ({"train_user_sequences_path": "user_sequences.valid.jsonl"}, "forbidden swing_recall manifest value"),
        ({"input_contract": {"allowed_inputs": ["clean_manifest.train_user_sequences_path"], "train_user_sequences_path": "user_sequences.test.jsonl", "declared_inputs": ["user_sequences.test.jsonl"]}}, "forbidden swing_recall manifest value"),
    ],
)
def test_load_swing_recall_sidecar_rejects_invalid_source_index_contract(tmp_path: Path, override: dict[str, object], message: str) -> None:
    manifest_path = _write_loader_manifest_fixture(tmp_path, **override)

    with pytest.raises(ValueError, match=message):
        load_swing_recall_sidecar(manifest_path)


@pytest.mark.parametrize(
    ("omit_key", "message"),
    [
        ("schema_version", "schema_version"),
        ("provenance", "provenance signatures"),
        ("lifecycle_stage", "lifecycle_stage"),
    ],
)
def test_load_swing_recall_sidecar_rejects_omitted_strict_contract_fields(tmp_path: Path, omit_key: str, message: str) -> None:
    manifest_path = _write_loader_manifest_fixture(tmp_path, omit_keys=(omit_key,))

    with pytest.raises(ValueError, match=message):
        load_swing_recall_sidecar(manifest_path)


@pytest.mark.parametrize(
    "edges_path",
    [
        "../swing_recall_edges.jsonl",
        "valid/swing_recall_edges.jsonl",
        "swing_recall_edges.valid.jsonl",
    ],
)
def test_load_swing_recall_sidecar_rejects_forbidden_or_traversal_edges_artifact_path(tmp_path: Path, edges_path: str) -> None:
    manifest_path = _write_loader_manifest_fixture(tmp_path, required_artifacts={"swing_recall_edges": edges_path})

    with pytest.raises(ValueError, match="edges artifact path|forbidden"):
        load_swing_recall_sidecar(manifest_path)


def test_load_swing_recall_sidecar_allows_serving_allowed_false(tmp_path: Path) -> None:
    manifest_path = _write_loader_manifest_fixture(tmp_path, serving_allowed=False)

    loaded = load_swing_recall_sidecar(manifest_path)

    assert loaded["seed"][0].item_id == "item_b"


def test_load_swing_recall_sidecar_rejects_serving_allowed_true(tmp_path: Path) -> None:
    manifest_path = _write_loader_manifest_fixture(tmp_path, serving_allowed=True)

    with pytest.raises(ValueError, match="serving_allowed"):
        load_swing_recall_sidecar(manifest_path)


def _write_loader_manifest_fixture(root: Path, omit_keys: tuple[str, ...] = (), **overrides: object) -> Path:
    edges_path = root / "swing_recall_edges.jsonl"
    _write_jsonl(edges_path, [{"src_item": "seed", "dst_item": "item_b", "score": 1.0, "rank": 1, "source": "swing_recall"}])
    manifest: dict[str, object] = {
        "schema_version": "full_train_swing_sidecar_v1",
        "status": "PASS",
        "source": "swing_recall",
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "train_user_sequences_path": "user_sequences.train.jsonl",
        "input_contract": {
            "allowed_inputs": ["clean_manifest.train_user_sequences_path"],
            "train_user_sequences_path": "user_sequences.train.jsonl",
            "declared_inputs": ["user_sequences.train.jsonl"],
        },
        "lifecycle_stage": "builder_complete",
        "provenance": {
            "clean_manifest_signature": {"sha256": "clean-sha"},
            "train_user_sequences_signature": {"sha256": "train-sha"},
        },
        "partial_invalidation_keys": [
            "provenance.clean_manifest_signature.sha256",
            "provenance.train_user_sequences_signature.sha256",
            "parameters",
        ],
        "required_artifacts": {"swing_recall_edges": edges_path.name},
    }
    manifest.update(overrides)
    for key in omit_keys:
        manifest.pop(key, None)
    manifest_path = root / "source_index_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _write_clean_fixture(root: Path, rows: list[dict[str, object]]) -> Path:
    clean_dir = root / "clean"
    clean_dir.mkdir()
    sequence_path = clean_dir / "user_sequences.train.jsonl"
    _write_jsonl(sequence_path, rows)
    manifest_path = clean_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"status": "PASS", "train_user_sequences_path": str(sequence_path)}), encoding="utf-8")
    return manifest_path


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
