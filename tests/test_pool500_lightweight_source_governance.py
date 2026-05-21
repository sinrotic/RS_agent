from __future__ import annotations

from pathlib import Path

from rs_core.common.io import read_json, write_json, write_jsonl
from rs_lab.experiments.recall.pool500.common.lightweight_source_builder import build_lightweight_governance_source


def test_category_lightweight_governance_outputs_required_audits(tmp_path: Path) -> None:
    promoted = _write_promoted_fixture(tmp_path, "category", rows_per_user=3)
    output_dir = tmp_path / "out" / "category" / "run"

    manifest = build_lightweight_governance_source(
        source="category",
        config={"promoted_dir": str(promoted), "category_bucket_cap_per_user": 2, "long_tail_rank_threshold": 3},
        run_id="run",
        output_dir=output_dir,
        overwrite=False,
    )

    assert manifest["candidate_generation_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["pool1000_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["candidate_row_count"] == 4
    assert manifest["user_coverage_count"] == 2
    assert (output_dir / "method_dataset_manifest.json").exists()
    assert (output_dir / "source_index_manifest.json").exists()
    assert (output_dir / "candidates.jsonl").exists()
    coverage = read_json(output_dir / "coverage_audit.json")
    assert coverage["category_diversity"]["per_user_distinct_category_count"]["min"] == 1
    assert coverage["long_tail_pool"]["row_count"] == 0
    assert coverage["diversity_cap_audit"]["dropped_by_cap"] == 2


def test_popular_lightweight_governance_caps_per_user(tmp_path: Path) -> None:
    promoted = _write_promoted_fixture(tmp_path, "popular", rows_per_user=4)
    output_dir = tmp_path / "out" / "popular" / "run"

    manifest = build_lightweight_governance_source(
        source="popular",
        config={"promoted_dir": str(promoted), "popular_per_user_cap": 2, "popular_max_category_share_per_user": 0.8},
        run_id="run",
        output_dir=output_dir,
        overwrite=False,
    )

    assert manifest["candidate_row_count"] == 4
    assert manifest["per_user_candidate_count"] == {"min": 2, "p50": 2.0, "p90": 2, "max": 2}
    coverage = read_json(output_dir / "coverage_audit.json")
    assert coverage["popular_cap_audit"]["dropped_by_cap"] == 4
    assert coverage["popular_cap_audit"]["max_observed_per_user_after_cap"] == 2
    assert coverage["time_window_audit"]["status"] == "NO_TIMESTAMP_METADATA"
    assert coverage["category_constraint_audit"]["violating_user_count"] == 2
    assert read_json(output_dir / "no_holdout_audit.json")["status"] == "PASS"


def _write_promoted_fixture(tmp_path: Path, source: str, rows_per_user: int) -> Path:
    promoted = tmp_path / "promoted"
    source_dir = promoted / "sources" / source
    source_dir.mkdir(parents=True)
    users = ["u1", "u2"]
    rows = []
    for user in users:
        for rank in range(1, rows_per_user + 1):
            rows.append(
                {
                    "user_id": user,
                    "item_id": f"{user}_{rank}",
                    "source": source,
                    "sources": [source],
                    "score": float(100 - rank),
                    "rank": rank,
                    "metadata": {"category": "Electronics", "source_scores": {source: float(100 - rank)}},
                }
            )
    write_jsonl(source_dir / "candidates.jsonl", rows)
    write_json(source_dir / "manifest.json", {"source": source, "status": "READY", "row_count": len(rows)})
    write_json(promoted / "eligible_user_manifest.json", {"eligible_user_ids": users})
    write_json(
        promoted / "source_contribution_audit.json",
        {"sources": {source: {"row_count": len(rows), "user_coverage_count": len(users), "marginal_candidate_share": 0.4}}},
    )
    write_json(promoted / "source_overlap_audit.json", {"pairwise_user_item_overlap_count": {source: {}}})
    return promoted
