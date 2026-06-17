from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from rs_core.recsys.candidate_merge import load_usercf_recall_sidecar
from rs_lab.experiments.recall.build_full_train_usercf_sidecar import build_full_train_usercf_sidecar
from rs_lab.experiments.recall.pool500.methods.usercf_recall.builder import build_usercf_recall_method_source


FORBIDDEN_SWITCHES = (
    "candidate_generation_allowed",
    "ranking_input_replacement_allowed",
    "pool1000_allowed",
    "promotion_allowed",
    "final_pool500_ready_claimed",
)
REQUIRED_ARTIFACTS = {
    "method_dataset_manifest.json",
    "source_index_manifest.json",
    "candidates.jsonl",
    "coverage_audit.json",
    "undercoverage_audit.json",
    "resource_audit.json",
    "no_holdout_audit.json",
}
UNDERCOVERAGE_REASONS = {
    "insufficient_positive_items",
    "no_indexed_items_after_hot_drop",
    "no_neighbor_overlap",
    "only_seen_items_after_neighbor_merge",
    "unknown_after_train_only_diagnostics",
}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def collect_shard_rows(manifest: dict) -> list[dict]:
    rows = []
    for shard_path in manifest["outputs"]["candidate_shards"]:
        rows.extend(read_jsonl(Path(shard_path)))
    return rows


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_clean_manifest(tmp_path: Path, rows: list[dict], manifest_patch: dict | None = None) -> Path:
    clean_dir = tmp_path / "amazon_2023_recall_clean_full"
    sequence_path = clean_dir / "user_sequences.train.jsonl"
    write_jsonl(sequence_path, rows)
    write_jsonl(clean_dir / "user_sequences.valid.jsonl", [{"must_not_be_read": True}])
    write_jsonl(clean_dir / "user_sequences.test.jsonl", [{"must_not_be_read": True}])
    write_jsonl(clean_dir / "holdout.jsonl", [{"must_not_be_read": True}])
    manifest = {"train_user_sequences_path": str(sequence_path)}
    if manifest_patch:
        manifest.update(manifest_patch)
    manifest_path = clean_dir / "manifest.json"
    write_json(manifest_path, manifest)
    return manifest_path


def make_source_config(tmp_path: Path, output_root: Path) -> Path:
    path = tmp_path / "source_config.yaml"
    path.write_text(
        "\n".join(
            [
                "source: usercf_recall",
                f"output_root: {output_root.as_posix()}",
                "target_user_limit: 3",
                "candidate_top_k_per_user: 2",
                "generation_config_overrides:",
                "  usercf_per_user: 2",
                "similar_users_top_k: 2",
                "target_batch_size: 2",
                "shard_count: 2",
                "max_items_per_user: 10",
                "max_item_user_freq: 10",
                "scoring_policy: iuf_cosine",
                "item_filter_policy:",
                "  src_min_positive_user_count: 2",
                "  dst_min_positive_user_count: 3",
                "  keep_hot: true",
                "user_filter_policy:",
                "  min_src_filtered_items_per_user: 2",
                "max_rss_mb: 4096",
                "governance:",
                "  candidate_generation_allowed: false",
                "  ranking_input_replacement_allowed: false",
                "  pool1000_allowed: false",
                "  promotion_allowed: false",
                "  final_pool500_ready_claimed: false",
            ]
        ),
        encoding="utf-8",
    )
    return path


def make_dataset_policy(tmp_path: Path) -> Path:
    path = tmp_path / "dataset_policy.yaml"
    path.write_text(
        "\n".join(
            [
                "source: usercf_recall",
                "governance:",
                "  candidate_generation_allowed: false",
                "  ranking_input_replacement_allowed: false",
                "  pool1000_allowed: false",
                "  promotion_allowed: false",
                "  final_pool500_ready_claimed: false",
            ]
        ),
        encoding="utf-8",
    )
    return path


def eligible_profile(user_id: str) -> dict:
    return {
        "user_id": user_id,
        "quality_bucket": "target500_high_cost_slice",
        "eligible_for_usercf_slice": True,
        "positive_count": 3,
        "unique_item_count": 3,
    }


def make_eligible_manifest(tmp_path: Path, user_ids: list[str]) -> Path:
    path = tmp_path / "eligible_user_quality_manifest.json"
    write_json(
        path,
        {
            "schema_version": "pool500_user_quality_profile_v1",
            "status": "PASS",
            "scope": "target500_train_only_high_cost_slice_users",
            "train_only": True,
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "pool1000_allowed": False,
            "promotion_allowed": False,
            "final_pool500_ready_claimed": False,
            "profiles": [eligible_profile(user_id) for user_id in user_ids],
        },
    )
    return path


def make_method_dataset_manifest(tmp_path: Path, rows: list[dict], manifest_patch: dict | None = None, rows_dir_name: str = "method_dataset") -> Path:
    dataset_dir = tmp_path / rows_dir_name
    rows_path = dataset_dir / "method_dataset_rows.jsonl"
    write_jsonl(rows_path, rows)
    manifest = {
        "schema_version": "pool500_method_dataset_v1",
        "layer": "method_dataset",
        "source_method": "usercf_method_dataset",
        "status": "PASS",
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "row_count": len(rows),
        "user_count": len({str(row.get("user_id") or "") for row in rows if row.get("user_id")} ),
        "outputs": {"dataset_rows_path": str(rows_path), "dataset_schema": "eligible_user_sequence_v1"},
    }
    if manifest_patch:
        manifest.update(manifest_patch)
    manifest_path = dataset_dir / "method_dataset_manifest.json"
    write_json(manifest_path, manifest)
    return manifest_path


def build_method_source(tmp_path: Path, *, rows: list[dict] | None = None, eligible: Path | None = None, run_id: str = "tiny_run", target_user_limit: int | None = None) -> tuple[dict, Path]:
    rows = rows or [
        {"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]},
        {"user_id": "u2", "recent_positive_item_sequence": ["a", "c"]},
        {"user_id": "u3", "recent_positive_item_sequence": ["b", "d"]},
        {"user_id": "u4", "recent_positive_item_sequence": ["x"]},
    ]
    output_root = tmp_path / "method_sources"
    manifest = build_usercf_recall_method_source(
        clean_manifest_path=make_clean_manifest(tmp_path, rows),
        eligible_user_quality_manifest=eligible,
        output_root=output_root,
        run_id=run_id,
        source_config_path=make_source_config(tmp_path, output_root),
        dataset_policy_path=make_dataset_policy(tmp_path),
        target_user_limit=target_user_limit,
        candidate_top_k_per_user=2,
        generation_usercf_per_user=2,
        similar_users_top_k=2,
        target_batch_size=2,
        shard_count=2,
        max_items_per_user=10,
        max_item_user_freq=10,
        src_min_positive_user_count=1,
        dst_min_positive_user_count=1,
        min_src_filtered_items_per_user=1,
        keep_hot=False,
        min_free_bytes=0,
        max_rss_mb=4096,
        overwrite=True,
        enforce_venv=False,
    )
    return manifest, output_root / "usercf_recall" / run_id


def assert_governance(payload: dict) -> None:
    assert payload["source"] == "usercf_recall"
    assert payload["canonical_source"] == "usercf_recall"
    assert payload["source_status"] == "DIAGNOSTIC_ONLY"
    assert payload["diagnostic_only"] is True
    assert payload["index_scope"] == "FULL_DERIVED_INDEX"
    assert payload["train_only"] is True
    for key in FORBIDDEN_SWITCHES:
        assert payload[key] is False
    assert "FULL_POOL500_READY" not in json.dumps(payload, ensure_ascii=False)


def assert_recall_only_supplemental_governance(payload: dict) -> None:
    assert payload["source"] == "usercf_recall"
    assert payload["canonical_source"] == "usercf_recall"
    assert payload["source_status"] == "POOL500_RECALL_ONLY_SUPPLEMENTAL_READY"
    assert payload["diagnostic_only"] is False
    assert payload["index_scope"] == "FULL_DERIVED_INDEX"
    assert payload["train_only"] is True
    for key in FORBIDDEN_SWITCHES:
        assert payload[key] is False
    assert "FULL_POOL500_READY" not in json.dumps(payload, ensure_ascii=False)


def test_usercf_method_source_writes_required_artifacts_and_loader_uses_shards(tmp_path: Path) -> None:
    manifest, output_dir = build_method_source(tmp_path)

    assert output_dir.is_dir()
    assert {path.name for path in output_dir.iterdir() if path.is_file()}.issuperset(REQUIRED_ARTIFACTS)
    assert manifest["required_outputs_present"] == {name: True for name in REQUIRED_ARTIFACTS}
    assert_governance(manifest)
    assert output_dir.parent.name == "usercf_recall"
    assert output_dir.name == "tiny_run"
    assert "usercf_recall/usercf_recall/tiny_run" not in output_dir.as_posix()

    persisted_manifest = read_json(output_dir / "source_index_manifest.json")
    assert_governance(persisted_manifest)
    assert persisted_manifest["outputs"]["candidate_shards"]
    assert persisted_manifest["outputs"]["candidates"] == str(output_dir / "candidates.jsonl")

    usercf = load_usercf_recall_sidecar(output_dir / "source_index_manifest.json")
    assert set(usercf) == {"u1", "u2", "u3"}
    assert [candidate.item_id for candidate in usercf["u1"]] == ["c", "d"]

    flat_rows = read_jsonl(output_dir / "candidates.jsonl")
    shard_rows = []
    for shard_path in persisted_manifest["outputs"]["candidate_shards"]:
        shard_rows.extend(read_jsonl(Path(shard_path)))
    assert flat_rows
    assert len(flat_rows) == sum(len(row["candidates"]) for row in shard_rows)
    assert set(flat_rows[0]) == {"user_id", "item_id", "score", "rank", "source", "canonical_source"}
    assert all(row["source"] == "usercf_recall" and row["canonical_source"] == "usercf_recall" for row in flat_rows)


def test_usercf_method_source_generates_internal_eligible_manifest_and_audits(tmp_path: Path) -> None:
    _, output_dir = build_method_source(tmp_path, run_id="internal")

    method_dataset = read_json(output_dir / "method_dataset_manifest.json")
    coverage = read_json(output_dir / "coverage_audit.json")
    undercoverage = read_json(output_dir / "undercoverage_audit.json")
    copied_eligible = read_json(output_dir / "eligible_user_quality_manifest.json")
    no_holdout = read_json(output_dir / "no_holdout_audit.json")

    assert method_dataset["eligible_user_quality_manifest_input"] is None
    assert method_dataset["selection_policy"] == "train_only_overlap_potential"
    assert Path(method_dataset["eligible_user_quality_manifest_effective"]).is_file()
    assert copied_eligible["profile_count"] == method_dataset["selected_target_user_count"]
    assert copied_eligible["profiles"]
    assert_governance(method_dataset)
    assert_governance(coverage)
    assert_governance(undercoverage)

    for key in ("target_user_count", "candidate_row_count", "user_coverage_count", "candidate_count_stats", "behavior_count_distribution", "neighbor_count_distribution", "overlap_count_distribution", "dropped_hot_item_count", "old_promoted_baseline", "new_vs_old_delta"):
        assert key in coverage
    assert set(coverage["candidate_count_stats"]) == {"min", "p50", "p90", "max"}
    assert undercoverage["undercovered_user_count"] == len(undercoverage["users"])
    assert set(undercoverage["reason_counts"]).issubset(UNDERCOVERAGE_REASONS)
    assert {row["reason"] for row in undercoverage["users"]}.issubset(UNDERCOVERAGE_REASONS)
    assert all("candidate_cap_exhausted" in row for row in undercoverage["users"])
    assert no_holdout["uses_valid"] is False
    assert no_holdout["uses_test"] is False
    assert no_holdout["uses_holdout"] is False
    assert no_holdout["uses_pool1000"] is False


def test_usercf_method_source_caps_external_eligible_manifest_by_target_limit(tmp_path: Path) -> None:
    rows = [
        {"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]},
        {"user_id": "u2", "recent_positive_item_sequence": ["a", "c"]},
        {"user_id": "u3", "recent_positive_item_sequence": ["b", "d"]},
        {"user_id": "u4", "recent_positive_item_sequence": ["c", "e"]},
    ]
    eligible = make_eligible_manifest(tmp_path, ["u1", "u2", "u3", "u4"])

    manifest, output_dir = build_method_source(tmp_path, rows=rows, eligible=eligible, run_id="external", target_user_limit=2)

    method_dataset = read_json(output_dir / "method_dataset_manifest.json")
    internal_eligible = read_json(output_dir / "eligible_user_quality_manifest.json")
    assert method_dataset["selection_policy"] == "external_manifest_capped"
    assert method_dataset["eligible_profile_count_raw"] == 4
    assert method_dataset["selected_target_user_count"] == 2
    assert method_dataset["target_user_ids"] == ["u1", "u2"]
    assert internal_eligible["profile_count"] == 2
    assert [profile["user_id"] for profile in internal_eligible["profiles"]] == ["u1", "u2"]
    assert manifest["target_user_limit"] == 2
    assert manifest["target_user_count"] == 2


def test_usercf_method_source_accepts_diagnostic_limited_train_user_manifest(tmp_path: Path) -> None:
    rows = [
        {"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]},
        {"user_id": "u2", "recent_positive_item_sequence": ["a", "c"]},
        {"user_id": "u3", "recent_positive_item_sequence": ["b", "d"]},
    ]
    eligible = tmp_path / "diagnostic_eligible_user_quality_manifest.json"
    write_json(
        eligible,
        {
            "schema_version": "pool500_user_quality_profile_v1",
            "status": "PASS",
            "scope": "diagnostic_limited_train_users",
            "train_only": True,
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "pool1000_allowed": False,
            "promotion_allowed": False,
            "final_pool500_ready_claimed": False,
            "profiles": [
                {"user_id": "u1", "quality_bucket": "fallback_only", "eligible_for_usercf": False, "shared_item_neighbor_count": 0},
                {"user_id": "u2", "quality_bucket": "medium_behavior", "eligible_for_usercf": False, "shared_item_neighbor_count": 1},
                {"user_id": "u3", "quality_bucket": "heavy_cf_eligible", "eligible_for_usercf": True, "shared_item_neighbor_count": 3},
            ],
        },
    )

    manifest, output_dir = build_method_source(tmp_path, rows=rows, eligible=eligible, run_id="diagnostic", target_user_limit=3)

    method_dataset = read_json(output_dir / "method_dataset_manifest.json")
    internal_eligible = read_json(output_dir / "eligible_user_quality_manifest.json")
    assert method_dataset["selection_policy"] == "external_manifest_capped"
    assert method_dataset["eligible_profile_count_raw"] == 3
    assert method_dataset["target_user_ids"] == ["u2", "u3"]
    assert [profile["user_id"] for profile in internal_eligible["profiles"]] == ["u2", "u3"]
    assert all(profile["eligible_for_usercf_slice"] is True for profile in internal_eligible["profiles"])
    assert manifest["target_user_count"] == 2


@pytest.mark.parametrize(
    ("manifest_patch", "match"),
    [
        ({"status": "BLOCKED"}, "status"),
        ({"train_only": False}, "train_only"),
        ({"schema_version": "unexpected_schema"}, "schema_version"),
        ({"source_method": "itemcf_weak"}, "source_method"),
        ({"outputs": {"dataset_rows_path": "method_dataset_rows.jsonl", "dataset_schema": "itemcf_edge_features_v1"}}, "dataset_schema"),
        ({"candidate_generation_allowed": True}, "candidate_generation_allowed"),
    ],
)
def test_usercf_method_dataset_input_rejects_invalid_manifest_contract(tmp_path: Path, manifest_patch: dict, match: str) -> None:
    method_dataset = make_method_dataset_manifest(
        tmp_path,
        [{"user_id": "u1", "eligible_item_sequence": ["a", "b"], "positive_item_count": 2}],
        manifest_patch=manifest_patch,
    )

    with pytest.raises(ValueError, match=match):
        build_usercf_recall_method_source(
            clean_manifest_path=make_clean_manifest(tmp_path / "clean", []),
            method_dataset_manifest_path=method_dataset,
            output_root=tmp_path / "method_sources",
            run_id="bad_contract",
            source_config_path=make_source_config(tmp_path, tmp_path / "method_sources"),
            dataset_policy_path=make_dataset_policy(tmp_path),
            min_free_bytes=0,
            overwrite=True,
            enforce_venv=False,
        )


def test_usercf_sidecar_method_dataset_adapter_counts_dropped_rows_and_preserves_first_unique_items(tmp_path: Path) -> None:
    method_dataset = make_method_dataset_manifest(
        tmp_path,
        [
            {"user_id": "u1", "eligible_item_sequence": ["a", "", "b", "a", None, "c"], "positive_item_count": 6},
            {"user_id": "u2", "eligible_item_sequence": [], "positive_item_count": 0},
            {"user_id": "", "eligible_item_sequence": ["x"], "positive_item_count": 1},
            {"user_id": "u3", "eligible_item_sequence": "bad", "positive_item_count": 1},
            {"user_id": "u4", "eligible_item_sequence": ["a", "d"], "positive_item_count": 2},
        ],
    )

    manifest = build_full_train_usercf_sidecar(
        clean_manifest=make_clean_manifest(tmp_path / "clean", []),
        method_dataset_manifest=method_dataset,
        eligible_user_quality_manifest=None,
        output_dir=tmp_path / "sidecar",
        max_items_per_user=3,
        max_item_user_freq=10,
        similar_users_top_k=2,
        candidate_top_k_per_user=3,
        shard_count=2,
        target_batch_size=2,
        min_free_bytes=0,
        max_rss_mb=4096,
        enforce_venv=False,
    )

    resource = read_json(tmp_path / "sidecar" / "resource_audit.json")
    rows_by_user = {row["user_id"]: row for row in collect_shard_rows(manifest)}
    assert resource["input_mode"] == "method_dataset"
    assert resource["train_rows_scanned"] == 5
    assert resource["rows_with_eligible_sequence"] == 3
    assert resource["target_user_count"] == 3
    assert resource["indexed_user_count"] == 2
    assert resource["empty_history_count"] == 1
    assert resource["dropped_reason_counts"] == {
        "duplicate_item_id": 1,
        "empty_eligible_item_sequence": 1,
        "empty_or_invalid_item_id": 2,
        "missing_or_invalid_eligible_item_sequence": 1,
        "missing_user_id": 1,
    }
    assert rows_by_user["u1"]["candidates"] == [{"item_id": "d", "score": 0.408248, "rank": 1, "source": "usercf_recall"}]
    assert [candidate["item_id"] for candidate in rows_by_user["u4"]["candidates"]] == ["b", "c"]


def test_usercf_method_source_method_dataset_input_writes_non_promoted_loadable_shards(tmp_path: Path) -> None:
    output_root = tmp_path / "method_sources"
    method_dataset = make_method_dataset_manifest(
        tmp_path,
        [
            {"user_id": "u1", "eligible_item_sequence": ["a", "b"], "positive_item_count": 2},
            {"user_id": "u2", "eligible_item_sequence": ["a", "c"], "positive_item_count": 2},
            {"user_id": "u3", "eligible_item_sequence": ["b", "d"], "positive_item_count": 2},
        ],
    )

    manifest = build_usercf_recall_method_source(
        clean_manifest_path=make_clean_manifest(tmp_path / "clean", []),
        method_dataset_manifest_path=method_dataset,
        output_root=output_root,
        run_id="method_dataset_run",
        source_config_path=make_source_config(tmp_path, output_root),
        dataset_policy_path=make_dataset_policy(tmp_path),
        target_user_limit=3,
        candidate_top_k_per_user=2,
        generation_usercf_per_user=2,
        similar_users_top_k=2,
        target_batch_size=2,
        shard_count=2,
        max_items_per_user=10,
        max_item_user_freq=10,
        src_min_positive_user_count=1,
        dst_min_positive_user_count=1,
        min_src_filtered_items_per_user=1,
        keep_hot=False,
        min_free_bytes=0,
        max_rss_mb=4096,
        overwrite=True,
        enforce_venv=False,
    )

    output_dir = output_root / "usercf_recall" / "method_dataset_run"
    method_dataset_output = read_json(output_dir / "method_dataset_manifest.json")
    readiness = read_json(output_dir / "readiness_contract.json")
    resource = read_json(output_dir / "resource_audit.json")
    usercf = load_usercf_recall_sidecar(output_dir / "source_index_manifest.json")
    serialized_contracts = json.dumps([manifest, method_dataset_output, readiness, resource], ensure_ascii=False)
    assert manifest["target_user_count"] == 3
    assert manifest["candidate_user_count"] == 3
    assert method_dataset_output["input_mode"] == "method_dataset"
    assert method_dataset_output["selection_policy"] == "method_dataset_target_users"
    assert method_dataset_output["target_user_ids"] == ["u1", "u2", "u3"]
    assert resource["input_mode"] == "method_dataset"
    assert set(usercf) == {"u1", "u2", "u3"}
    assert [candidate.item_id for candidate in usercf["u1"]] == ["c", "d"]
    assert all(manifest[key] is False for key in FORBIDDEN_SWITCHES)
    assert all(method_dataset_output[key] is False for key in FORBIDDEN_SWITCHES)
    assert all(readiness[key] is False for key in FORBIDDEN_SWITCHES)
    assert "FULL_POOL500_READY" not in serialized_contracts
    assert all(Path(path).is_file() for path in manifest["outputs"]["candidate_shards"])


def test_usercf_method_source_route_ready_method_dataset_is_loadable_without_ranking_promotion(tmp_path: Path) -> None:
    output_root = tmp_path / "method_sources"
    method_dataset = make_method_dataset_manifest(
        tmp_path,
        [
            {"user_id": "u1", "eligible_item_sequence": ["a", "b"], "positive_item_count": 2},
            {"user_id": "u2", "eligible_item_sequence": ["a", "c"], "positive_item_count": 2},
            {"user_id": "u3", "eligible_item_sequence": ["b", "d"], "positive_item_count": 2},
        ],
    )

    manifest = build_usercf_recall_method_source(
        clean_manifest_path=make_clean_manifest(tmp_path / "clean", []),
        method_dataset_manifest_path=method_dataset,
        output_root=output_root,
        run_id="route_ready",
        source_config_path=make_source_config(tmp_path, output_root),
        dataset_policy_path=make_dataset_policy(tmp_path),
        target_user_limit=3,
        candidate_top_k_per_user=2,
        generation_usercf_per_user=2,
        similar_users_top_k=2,
        target_batch_size=2,
        shard_count=2,
        max_items_per_user=10,
        max_item_user_freq=10,
        src_min_positive_user_count=1,
        dst_min_positive_user_count=1,
        min_src_filtered_items_per_user=1,
        keep_hot=False,
        min_free_bytes=0,
        max_rss_mb=4096,
        overwrite=True,
        route_ready=True,
        enforce_venv=False,
    )

    output_dir = output_root / "usercf_recall" / "route_ready"
    readiness = read_json(output_dir / "readiness_contract.json")
    usercf = load_usercf_recall_sidecar(output_dir / "source_index_manifest.json")

    assert_recall_only_supplemental_governance(manifest)
    assert readiness["status"] == "POOL500_RECALL_ONLY_SUPPLEMENTAL_READY"
    assert readiness["source_status"] == "POOL500_RECALL_ONLY_SUPPLEMENTAL_READY"
    assert readiness["full_output_status"] == "FULL_OUTPUT_READY"
    assert_recall_only_supplemental_governance(readiness)
    assert set(usercf) == {"u1", "u2", "u3"}

    unsafe_manifest = dict(manifest)
    unsafe_manifest["ranking_input_replacement_allowed"] = True
    unsafe_path = output_dir / "unsafe_source_index_manifest.json"
    write_json(unsafe_path, unsafe_manifest)
    with pytest.raises(ValueError, match="ranking input replacement"):
        load_usercf_recall_sidecar(unsafe_path)


def test_usercf_method_dataset_input_rejects_forbidden_scope_paths(tmp_path: Path) -> None:
    method_dataset = make_method_dataset_manifest(
        tmp_path,
        [{"user_id": "u1", "eligible_item_sequence": ["a", "b"], "positive_item_count": 2}],
        rows_dir_name="pool1000",
    )

    with pytest.raises(ValueError, match="Forbidden holdout/10k/pool1000 path"):
        build_usercf_recall_method_source(
            clean_manifest_path=make_clean_manifest(tmp_path / "clean", []),
            method_dataset_manifest_path=method_dataset,
            output_root=tmp_path / "method_sources",
            run_id="forbidden_scope",
            source_config_path=make_source_config(tmp_path, tmp_path / "method_sources"),
            dataset_policy_path=make_dataset_policy(tmp_path),
            min_free_bytes=0,
            overwrite=True,
            enforce_venv=False,
        )


def test_usercf_method_source_rejects_forbidden_paths_before_build(tmp_path: Path) -> None:
    clean_dir = tmp_path / "amazon_2023_recall_clean_full"
    bad_train_path = clean_dir / "user_sequences.valid.jsonl"
    write_jsonl(bad_train_path, [{"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]}])
    bad_manifest = clean_dir / "manifest.json"
    write_json(bad_manifest, {"train_user_sequences_path": str(bad_train_path)})

    output_root = tmp_path / "method_sources"
    with pytest.raises(ValueError, match="Forbidden non-train input"):
        build_usercf_recall_method_source(
            clean_manifest_path=bad_manifest,
            output_root=output_root,
            run_id="bad_valid",
            source_config_path=make_source_config(tmp_path, output_root),
            dataset_policy_path=make_dataset_policy(tmp_path),
            min_free_bytes=0,
            overwrite=True,
            enforce_venv=False,
        )

    clean_10k = tmp_path / "amazon_2023_recall_clean_10000"
    sequence_path = clean_10k / "user_sequences.train.jsonl"
    write_jsonl(sequence_path, [{"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]}])
    manifest_10k = clean_10k / "manifest.json"
    write_json(manifest_10k, {"train_user_sequences_path": str(sequence_path)})
    with pytest.raises(ValueError, match="Forbidden holdout/10k/pool1000 path"):
        build_usercf_recall_method_source(
            clean_manifest_path=manifest_10k,
            output_root=output_root,
            run_id="bad_10k",
            source_config_path=make_source_config(tmp_path, output_root),
            dataset_policy_path=make_dataset_policy(tmp_path),
            min_free_bytes=0,
            overwrite=True,
            enforce_venv=False,
        )


def test_usercf_method_source_readiness_signature_matches_final_manifest(tmp_path: Path) -> None:
    _, output_dir = build_method_source(tmp_path, run_id="readiness")

    readiness_path = output_dir / "readiness_contract.json"
    readiness = read_json(readiness_path)
    source_manifest_path = output_dir / "source_index_manifest.json"
    source_manifest = read_json(source_manifest_path)
    method_dataset_manifest = read_json(output_dir / "method_dataset_manifest.json")

    assert_governance(readiness)
    assert readiness["index_manifest_path"] == str(source_manifest_path)
    assert readiness["index_manifest_sha256"] == sha256_file(source_manifest_path)
    assert readiness["index_manifest_signature"]["sha256"] == sha256_file(source_manifest_path)
    assert method_dataset_manifest["source_index_manifest_sha256"] == sha256_file(source_manifest_path)
    assert readiness["candidate_row_count"] == source_manifest["candidate_row_count"]
    assert readiness["candidate_total_count"] == source_manifest["candidate_total_count"]
    assert readiness["candidate_user_count"] == source_manifest["candidate_user_count"]
