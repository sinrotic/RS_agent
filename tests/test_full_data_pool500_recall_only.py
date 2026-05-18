from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_core.common.io import read_json
from rs_lab.experiments.recall.run_full_data_pool500_recall_only import _load_batch_semantic_index, run_full_data_pool500_recall_only

pytestmark = pytest.mark.unit


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_load_batch_semantic_index_keeps_seed_and_matching_candidates(tmp_path: Path) -> None:
    semantic_path = tmp_path / "semantic.jsonl"
    _write_jsonl(
        semantic_path,
        [
            {"parent_asin": "candidate_before_seed", "title_clean": "wireless gaming mouse", "main_category": "Electronics"},
            {"parent_asin": "unrelated", "title_clean": "ceramic bowl", "main_category": "Home"},
            {"parent_asin": "seed", "title_clean": "gaming keyboard", "main_category": "Electronics"},
            {"parent_asin": "candidate_after_seed", "title_clean": "keyboard wrist rest", "main_category": "Office"},
        ],
    )
    sequences = [{"user_id": "u1", "recent_positive_item_sequence": ["seed"]}]

    index = _load_batch_semantic_index(semantic_path, sequences, max_rows=10)

    assert set(index) == {"seed", "candidate_before_seed", "candidate_after_seed"}
    assert "semantic_tokens" in index["seed"]


def test_load_batch_semantic_index_respects_candidate_limit(tmp_path: Path) -> None:
    semantic_path = tmp_path / "semantic.jsonl"
    _write_jsonl(
        semantic_path,
        [
            {"parent_asin": "seed", "title_clean": "camera lens", "main_category": "Electronics"},
            {"parent_asin": "candidate_1", "title_clean": "camera tripod", "main_category": "Electronics"},
            {"parent_asin": "candidate_2", "title_clean": "camera bag", "main_category": "Electronics"},
        ],
    )
    sequences = [{"user_id": "u1", "recent_positive_item_sequence": ["seed"]}]

    index = _load_batch_semantic_index(semantic_path, sequences, max_rows=1)

    assert set(index) == {"seed", "candidate_1"}


def test_recall_only_runner_loads_source_artifacts_and_writes_contracts(tmp_path: Path) -> None:
    clean_manifest = _write_clean_manifest(tmp_path)
    views_manifest = _write_views_manifest(tmp_path)
    source_manifests = _write_source_artifacts(tmp_path)
    output_dir = tmp_path / "out"

    manifest = run_full_data_pool500_recall_only(
        clean_manifest_path=clean_manifest,
        lightweight_views_manifest_path=views_manifest,
        output_dir=output_dir,
        usercf_sidecar_manifest_path=source_manifests["usercf_recall"],
        source_manifest_paths=source_manifests,
        limit_users=1,
        enable_semantic=True,
        semantic_max_rows=20,
        overwrite=True,
        enforce_venv=False,
    )

    rows = [json.loads(line) for line in (output_dir / "pool500_candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {row["source"] for row in rows} >= {"itemcf_weak", "itemcf_strong", "swing_recall", "two_tower", "usercf_recall", "semantic_title_category_expansion"}
    readiness = read_json(output_dir / "per_source_readiness_contracts.json")
    index_manifests = read_json(output_dir / "full_derived_index_manifests.json")
    stoploss_audit = read_json(output_dir / "ready_source_stoploss_audit.json")
    diagnostic_contribution = read_json(output_dir / "diagnostic_source_contribution.json")
    assert readiness["swing_recall"]["source_index_manifest_path"] == str(source_manifests["swing_recall"])
    assert readiness["two_tower"]["canonical_source"] == "two_tower"
    assert index_manifests["itemcf_weak"]["index_scope"] == "FULL_DERIVED_INDEX"
    assert index_manifests["two_tower"]["source"] == "two_tower"
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["pool1000_allowed"] is False
    assert manifest["required_artifacts"]["ready_source_stoploss_audit"] == str(output_dir / "ready_source_stoploss_audit.json")
    assert manifest["required_artifacts"]["diagnostic_source_contribution"] == str(output_dir / "diagnostic_source_contribution.json")
    assert manifest["ready_source_stoploss_audit"]["audit_path"] == str(output_dir / "ready_source_stoploss_audit.json")
    assert manifest["diagnostic_source_contribution"]["audit_path"] == str(output_dir / "diagnostic_source_contribution.json")
    assert set(stoploss_audit["ready_sources"]) == {"category", "popular", "swing_recall"}
    assert set(stoploss_audit["sources"]) == {"category", "popular", "swing_recall"}
    assert "semantic_title_category_expansion" not in stoploss_audit["ready_sources"]
    assert "two_tower" not in stoploss_audit["ready_sources"]
    assert stoploss_audit["diagnostic_only_promotion_allowed"] is False
    assert stoploss_audit["ranking_input_replacement_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert stoploss_audit["pool1000_allowed"] is False
    assert diagnostic_contribution["status"] == "DIAGNOSTIC_ONLY_AUDIT"
    assert set(diagnostic_contribution["diagnostic_sources"]) == {"usercf_recall", "itemcf_weak", "itemcf_strong"}
    assert diagnostic_contribution["promotion_allowed"] is False
    assert diagnostic_contribution["ranking_input_replacement_allowed"] is False
    assert diagnostic_contribution["pool1000_allowed"] is False
    assert diagnostic_contribution["diagnostic_row_total"] > 0
    assert diagnostic_contribution["sources"]["usercf_recall"]["row_count"] > 0
    assert diagnostic_contribution["sources"]["usercf_recall"]["readiness_status"] == "DIAGNOSTIC_ONLY"
    assert diagnostic_contribution["sources"]["itemcf_weak"]["marginal_candidate_share"] > 0
    assert diagnostic_contribution["sources"]["itemcf_strong"]["marginal_candidate_share"] > 0
    assert stoploss_audit["candidate_row_count"] < 1000
    assert stoploss_audit["sources"]["category"]["underfilled_user_coverage_count"] >= 0
    assert stoploss_audit["sources"]["popular"]["unique_item_count"] >= 0
    assert stoploss_audit["sources"]["swing_recall"]["marginal_candidate_share"] > 0


def _write_clean_manifest(tmp_path: Path) -> Path:
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    sequences = clean_dir / "user_sequences.train.jsonl"
    _write_jsonl(
        sequences,
        [{"user_id": "u1", "recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"], "recent_strong_positive_item_sequence": ["strong_seed"]}],
    )
    train = clean_dir / "canonical_interactions.train.jsonl"
    _write_jsonl(train, [{"user_id": "u1", "parent_asin": "seed"}])
    items = clean_dir / "canonical_items.jsonl"
    _write_jsonl(items, [{"parent_asin": "seed", "main_category": "Electronics"}])
    manifest = clean_dir / "manifest.json"
    manifest.write_text(
        json.dumps({"schema_version": "test", "train_user_sequences_path": str(sequences), "canonical_items_path": str(items), "split_paths": {"train": str(train)}}),
        encoding="utf-8",
    )
    return manifest


def _write_views_manifest(tmp_path: Path) -> Path:
    views = tmp_path / "views"
    views.mkdir()
    popular = views / "popular_recall.jsonl"
    _write_jsonl(popular, [{"parent_asin": "popular_1", "pop_score": 1.0, "category": "Popular"}])
    category_items = views / "category_recall_items.jsonl"
    _write_jsonl(category_items, [{"parent_asin": "seed", "main_category": "Electronics"}, {"parent_asin": "strong_seed", "main_category": "Electronics"}])
    category_top = views / "category_top_items.jsonl"
    _write_jsonl(category_top, [{"bucket": "main::Electronics", "top_items": [{"parent_asin": "category_1", "score": 1.0}]}])
    semantic = views / "semantic_recall_inputs.jsonl"
    _write_jsonl(semantic, [{"parent_asin": "seed", "title_clean": "gaming mouse", "main_category": "Electronics"}, {"parent_asin": "semantic_1", "title_clean": "gaming keyboard", "main_category": "Electronics"}])
    manifest = views / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "source_clean_dir": str(tmp_path / "clean"),
                "outputs": {
                    "popular_recall": str(popular),
                    "category_recall_items": str(category_items),
                    "category_top_items": str(category_top),
                    "semantic_recall_inputs": str(semantic),
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _write_source_artifacts(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "sources"
    root.mkdir()
    paths = {}
    _write_pair_source(root / "itemcf_weak", "itemcf_weak", "seed", "weak_1")
    _write_pair_source(root / "itemcf_strong", "itemcf_strong", "strong_seed", "strong_1")
    _write_pair_source(root / "swing_recall", "swing_recall", "seed", "swing_1", edge_key="swing_recall_edges")
    paths["itemcf_weak"] = root / "itemcf_weak" / "source_index_manifest.json"
    paths["itemcf_strong"] = root / "itemcf_strong" / "source_index_manifest.json"
    paths["swing_recall"] = root / "swing_recall" / "source_index_manifest.json"
    paths["semantic_title_category_expansion"] = _write_semantic_source(root / "semantic_title_category_expansion")
    paths["usercf_recall"] = _write_usercf_source(root / "usercf_recall")
    paths["two_tower"] = _write_two_tower_source(root / "two_tower")
    return paths


def _write_pair_source(path: Path, source: str, src_item: str, dst_item: str, edge_key: str = "edges") -> None:
    path.mkdir()
    edges = path / f"{source}_edges.jsonl"
    _write_jsonl(edges, [{"src_item": src_item, "dst_item": dst_item, "score": 5.0, "source": source}])
    manifest = {"status": "PASS", "source": source, "index_scope": "FULL_DERIVED_INDEX", "train_only": True, "edges_path": str(edges), "required_artifacts": {edge_key: str(edges)}}
    (path / "source_index_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _write_semantic_source(path: Path) -> Path:
    path.mkdir()
    semantic = path / "semantic_recall_inputs.jsonl"
    _write_jsonl(semantic, [{"parent_asin": "seed", "title_clean": "gaming mouse", "main_category": "Electronics"}, {"parent_asin": "semantic_manifest_1", "title_clean": "gaming mat", "main_category": "Electronics"}])
    manifest = {"status": "PASS", "source": "semantic_title_category_expansion", "index_scope": "FULL_DERIVED_INDEX", "semantic_recall_inputs_path": str(semantic)}
    manifest_path = path / "source_index_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _write_usercf_source(path: Path) -> Path:
    path.mkdir()
    shard = path / "shard.jsonl"
    _write_jsonl(shard, [{"user_id": "u1", "candidates": [{"item_id": "usercf_1", "score": 4.0, "rank": 1, "source": "usercf_recall"}]}])
    readiness = {"index_status": "INDEX_READY", "full_output_status": "FULL_OUTPUT_READY", "output_manifest_sha256": "usercf-output", "index_manifest_sha256": "usercf-index", "manifest_path": str(path / "readiness_contract.json")}
    (path / "readiness_contract.json").write_text(json.dumps(readiness), encoding="utf-8")
    manifest = {"status": "PASS", "source": "usercf_recall", "index_scope": "FULL_DERIVED_INDEX", "train_only": True, "outputs": {"candidate_shards": [str(shard)], "readiness_contract": str(path / "readiness_contract.json")}}
    manifest_path = path / "source_index_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _write_two_tower_source(path: Path) -> Path:
    path.mkdir()
    index = path / "recall_index.jsonl"
    _write_jsonl(index, [{"parent_asin": "seed", "embedding": [1.0, 0.0]}, {"parent_asin": "two_tower_1", "embedding": [1.0, 0.0]}])
    manifest = {
        "status": "PASS",
        "source": "two_tower",
        "source_name": "two_tower",
        "canonical_source": "two_tower",
        "index_scope": "FULL_DERIVED_INDEX",
        "recall_index_path": str(index),
        "clean_manifest_sha256": "clean",
        "train_sequence_sha256": "train",
        "item_universe_sha256": "items",
        "model_config_sha256": "model",
        "item_embedding_row_count": 2,
        "recall_index_row_count": 2,
        "user_embedding_row_count_note": "not_required_for_item_seed_average",
    }
    manifest_path = path / "source_index_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path
