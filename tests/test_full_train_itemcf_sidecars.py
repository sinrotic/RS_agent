from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_lab.experiments.recall.build_full_train_itemcf_sidecars import build_full_train_itemcf_sidecar

pytestmark = pytest.mark.unit


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def make_clean_dir(tmp_path: Path) -> Path:
    clean_dir = tmp_path / "amazon_2023_recall_clean_full"
    write_jsonl(
        clean_dir / "user_sequences.train.jsonl",
        [
            {
                "user_id": "u1",
                "recent_positive_item_sequence": ["old", "a", "b", "a", "c"],
                "recent_strong_positive_item_sequence": ["a", "c"],
            },
            {
                "user_id": "u2",
                "recent_positive_item_sequence": ["hot", "b", "d"],
                "recent_strong_positive_item_sequence": ["b", "d"],
            },
            {
                "user_id": "u3",
                "recent_positive_item_sequence": ["hot", "e"],
                "recent_strong_positive_item_sequence": ["hot", "d"],
            },
            {
                "user_id": "u4",
                "recent_positive_item_sequence": ["hot", "f"],
                "recent_strong_positive_item_sequence": ["hot", "e"],
            },
        ],
    )
    write_jsonl(clean_dir / "canonical_interactions.valid.jsonl", [{"must_not_be_read": True}])
    write_jsonl(clean_dir / "canonical_interactions.test.jsonl", [{"must_not_be_read": True}])
    write_jsonl(clean_dir / "holdout.jsonl", [{"must_not_be_read": True}])
    return clean_dir


def build_for_test(clean_dir: Path, output_dir: Path, source: str, **kwargs: object) -> dict[str, object]:
    return build_full_train_itemcf_sidecar(
        clean_dir=clean_dir,
        output_dir=output_dir,
        source=source,
        max_items_per_user=kwargs.pop("max_items_per_user", 3),
        max_item_user_freq=kwargs.pop("max_item_user_freq", 2),
        top_k_per_seed=kwargs.pop("top_k_per_seed", 2),
        min_free_bytes=kwargs.pop("min_free_bytes", 0),
        enforce_venv=kwargs.pop("enforce_venv", False),
        **kwargs,
    )


def test_builds_weak_itemcf_edges_with_hot_item_cap_and_rank(tmp_path: Path) -> None:
    clean_dir = make_clean_dir(tmp_path)
    output_dir = tmp_path / "weak_sidecar"

    manifest = build_for_test(clean_dir, output_dir, "itemcf_weak")

    rows = read_jsonl(output_dir / "itemcf_weak_edges.jsonl")
    assert manifest["source"] == "itemcf_weak"
    assert manifest["label_variant"] == "recent_positive_item_sequence"
    assert manifest["hot_items"] == ["hot"]
    assert {row["source"] for row in rows} == {"itemcf_weak"}
    assert {row["label_variant"] for row in rows} == {"recent_positive_item_sequence"}
    assert all(row["src_item"] != "hot" and row["dst_item"] != "hot" for row in rows)
    assert all(1 <= row["rank"] <= 2 for row in rows)
    assert {"src_item", "dst_item", "score", "rank", "source", "label_variant", "cooc_cnt", "src_user_cnt", "dst_user_cnt"}.issubset(rows[0])


def test_builds_strong_itemcf_from_strong_positive_sequence(tmp_path: Path) -> None:
    clean_dir = make_clean_dir(tmp_path)
    output_dir = tmp_path / "strong_sidecar"

    manifest = build_for_test(clean_dir, output_dir, "itemcf_strong")

    rows = read_jsonl(output_dir / "itemcf_strong_edges.jsonl")
    assert manifest["source"] == "itemcf_strong"
    assert manifest["label_variant"] == "recent_strong_positive_item_sequence"
    assert {row["source"] for row in rows} == {"itemcf_strong"}
    assert {row["label_variant"] for row in rows} == {"recent_strong_positive_item_sequence"}
    assert ("a", "c") in {(row["src_item"], row["dst_item"]) for row in rows}
    assert ("b", "d") in {(row["src_item"], row["dst_item"]) for row in rows}


def test_user_quality_manifest_filters_weak_and_strong_policies(tmp_path: Path) -> None:
    clean_dir = make_clean_dir(tmp_path)
    quality_manifest = tmp_path / "quality" / "eligible_user_quality_manifest.json"
    quality_manifest.parent.mkdir()
    quality_manifest.write_text(
        json.dumps(
            {
                "profiles": [
                    {"user_id": "u1", "quality_bucket": "heavy_cf_eligible"},
                    {"user_id": "u2", "quality_bucket": "medium_behavior"},
                    {"user_id": "u3", "quality_bucket": "fallback_only"},
                    {"user_id": "u4", "quality_bucket": "fallback_only"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    weak_manifest = build_for_test(clean_dir, tmp_path / "weak_quality", "itemcf_weak", user_quality_manifest_path=quality_manifest)
    strong_manifest = build_for_test(clean_dir, tmp_path / "strong_quality", "itemcf_strong", user_quality_manifest_path=quality_manifest)

    weak_comparison = read_json(tmp_path / "weak_quality" / "weak_strong_comparison.json")
    strong_comparison = read_json(tmp_path / "strong_quality" / "weak_strong_comparison.json")
    assert weak_manifest["diagnostic_only"] is True
    assert strong_manifest["diagnostic_only"] is True
    assert weak_manifest["used_quality_bucket_counts"] == {"heavy_cf_eligible": 1, "medium_behavior": 1}
    assert strong_manifest["used_quality_bucket_counts"] == {"heavy_cf_eligible": 1}
    assert weak_comparison["source_policy"] == "heavy_cf_eligible_or_medium_behavior"
    assert strong_comparison["source_policy"] == "heavy_cf_eligible"
    assert weak_manifest["users_filtered_by_quality"] == 2
    assert strong_manifest["users_filtered_by_quality"] == 3



def test_target_user_limit_marks_itemcf_sidecar_as_diagnostic_only(tmp_path: Path) -> None:
    clean_dir = make_clean_dir(tmp_path)
    output_dir = tmp_path / "weak_limited_sidecar"

    manifest = build_for_test(clean_dir, output_dir, "itemcf_weak", target_user_limit=2)

    assert manifest["target_user_limit"] == 2
    assert manifest["users_with_source_items"] == 2
    readiness = read_json(output_dir / "readiness_contract.json")
    assert readiness["status"] == "DIAGNOSTIC_ONLY"
    assert readiness["diagnostic_output_status"] == "DIAGNOSTIC_OUTPUT_READY"
    assert readiness["full_output_status"] == "DIAGNOSTIC_OUTPUT_READY"
    assert read_json(output_dir / "resource_audit.json")["target_user_limit"] == 2



def test_manifests_forbid_holdout_10k_pool1000_and_ranking_replacement(tmp_path: Path) -> None:
    clean_dir = make_clean_dir(tmp_path)
    output_dir = tmp_path / "weak_sidecar"

    manifest = build_for_test(clean_dir, output_dir, "itemcf_weak")

    artifact_names = {
        "source_index_manifest.json",
        "custom_index_selection_manifest.json",
        "resource_audit.json",
        "no_holdout_audit.json",
        "readiness_contract.json",
        "per_source_candidate_manifest.json",
        "weak_strong_comparison.json",
        "manifest.json",
        "itemcf_weak_edges.jsonl",
    }
    assert {path.name for path in output_dir.iterdir()} == artifact_names

    for filename in ("manifest.json", "source_index_manifest.json", "custom_index_selection_manifest.json", "no_holdout_audit.json", "readiness_contract.json", "per_source_candidate_manifest.json", "weak_strong_comparison.json"):
        payload = read_json(output_dir / filename)
        assert payload["index_scope"] == "FULL_DERIVED_INDEX"
        assert payload["candidate_generation_allowed"] is False
        assert payload["ranking_input_replacement_allowed"] is False
        assert payload["pool1000_allowed"] is False

    readiness = read_json(output_dir / "readiness_contract.json")
    assert readiness["status"] == "READY"
    assert readiness["full_output_status"] == "FULL_OUTPUT_READY"

    no_holdout_audit = read_json(output_dir / "no_holdout_audit.json")
    assert no_holdout_audit["status"] == "PASS"
    assert no_holdout_audit["uses_holdout"] is False
    assert no_holdout_audit["read_files"] == [str((clean_dir / "user_sequences.train.jsonl").resolve())]
    read_names = [Path(path).name for path in no_holdout_audit["read_files"]]
    assert all("valid" not in name and "test" not in name and "holdout" not in name for name in read_names)
    assert any("canonical_interactions.valid.jsonl" in path for path in no_holdout_audit["forbidden_inputs"])
    assert any("canonical_interactions.test.jsonl" in path for path in no_holdout_audit["forbidden_inputs"])
    assert any("holdout.jsonl" in path for path in no_holdout_audit["forbidden_inputs"])
    assert manifest["required_artifacts"]["edges"] == str(output_dir.resolve() / "itemcf_weak_edges.jsonl")
    candidate_manifest = read_json(output_dir / "per_source_candidate_manifest.json")
    comparison = read_json(output_dir / "weak_strong_comparison.json")
    assert candidate_manifest["candidate_generation_allowed"] is False
    assert candidate_manifest["ranking_input_replacement_allowed"] is False
    assert candidate_manifest["pool1000_allowed"] is False
    assert candidate_manifest["final_pool500_ready_claimed"] is False
    assert comparison["expected_policy_by_source"]["itemcf_weak"] == "heavy_cf_eligible_or_medium_behavior"
    assert comparison["expected_policy_by_source"]["itemcf_strong"] == "heavy_cf_eligible"


def test_rejects_10k_and_pool1000_paths(tmp_path: Path) -> None:
    clean_dir = tmp_path / "amazon_2023_recall_clean_10000"
    write_jsonl(clean_dir / "user_sequences.train.jsonl", [{"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]}])

    with pytest.raises(ValueError, match="Forbidden 10k/pool1000 path"):
        build_full_train_itemcf_sidecar(
            clean_dir=clean_dir,
            output_dir=tmp_path / "out",
            source="itemcf_weak",
            min_free_bytes=0,
            enforce_venv=False,
        )

    clean_dir = make_clean_dir(tmp_path)
    with pytest.raises(ValueError, match="Forbidden 10k/pool1000 path"):
        build_full_train_itemcf_sidecar(
            clean_dir=clean_dir,
            output_dir=tmp_path / "pool1000" / "out",
            source="itemcf_weak",
            min_free_bytes=0,
            enforce_venv=False,
        )
