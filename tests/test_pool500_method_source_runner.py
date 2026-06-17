from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

from rs_lab.experiments.recall.pool500.common.source_layout import FORBIDDEN_EVIDENCE_SCOPES, POOL500_METHOD_SOURCES, REQUIRED_SOURCE_OUTPUTS
from rs_lab.experiments.recall.pool500.methods.co_visit_fallback_repair.builder import _is_forbidden_path as co_visit_forbidden_path
from rs_lab.experiments.recall.pool500.methods.semantic.builder import _is_forbidden_path as semantic_forbidden_path
from rs_lab.experiments.recall.pool500.methods.semantic_title_category_expansion.builder import _is_forbidden_input_path as semantic_title_forbidden_path
from scripts.experiments.recall.pool500 import run_pool500_method_source as runner

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "experiments" / "recall" / "pool500" / "run_pool500_method_source.py"
TARGET_SOURCES = ("semantic", "semantic_title_category_expansion", "co_visit_fallback_repair")


def test_runner_default_config_path_uses_full_data_pool500_configs() -> None:
    for source in TARGET_SOURCES:
        path = runner._resolve_config_path(None, source)

        assert path == ROOT / "configs" / "recall" / "full_data_pool500" / source / "source_config.yaml"
        assert "rs_lab/experiments/recall/pool500/methods" not in path.as_posix()


def test_runner_dry_run_emits_contract_and_writes_no_outputs(tmp_path: Path) -> None:
    output_root = tmp_path / "dry_run_outputs"
    command = [
        sys.executable,
        str(RUNNER),
        "--source",
        "semantic",
        "--tier",
        "smoke",
        "--run-id",
        "dry_run_unit",
        "--output-root",
        str(output_root),
        "--dry-run",
    ]

    completed = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    payload = json.loads(completed.stdout)

    assert payload["source"] == "semantic"
    assert payload["tier"] == "smoke"
    assert payload["run_id"] == "dry_run_unit"
    assert payload["required_outputs"] == list(REQUIRED_SOURCE_OUTPUTS)
    assert payload["contract"]["canonical_source"] == "semantic"
    assert payload["contract"]["source_status"] == "READY_CANDIDATE"
    assert payload["contract"]["method_config"]["limit_users"] == 200
    assert payload["contract"]["resource_guard"]["checkpoint_enabled"] is True
    assert Path(payload["config_path"]) == ROOT / "configs" / "recall" / "full_data_pool500" / "semantic" / "source_config.yaml"
    assert not output_root.exists()


def test_semantic_title_and_co_visit_dry_run_exposes_method_and_checkpoint_contract() -> None:
    semantic_title_config = runner._merge_runner_config(
        runner._load_runner_config(ROOT / "configs" / "recall" / "full_data_pool500" / "semantic_title_category_expansion" / "source_config.yaml"),
        "smoke",
        {},
    )
    co_visit_config = runner._merge_runner_config(
        runner._load_runner_config(ROOT / "configs" / "recall" / "full_data_pool500" / "co_visit_fallback_repair" / "source_config_newdata_formal_shard50k.yaml"),
        "formal_shard50k",
        {},
    )

    semantic_title_contract = runner._contract_summary(semantic_title_config)
    co_visit_contract = runner._contract_summary(co_visit_config)

    assert semantic_title_contract["method_config"]["limit_users"] == 200
    assert semantic_title_contract["resource_guard"]["checkpoint_enabled"] is True
    assert semantic_title_contract["current_artifacts"]["formal_partial_checkpoint"].endswith("checkpoint.json")
    assert co_visit_contract["method_config"]["target_user_offset"] == 0
    assert co_visit_contract["method_config"]["target_user_limit"] == 50000
    assert co_visit_contract["method_config"]["checkpoint_every_users"] == 1000
    assert co_visit_contract["resource_guard"]["checkpoint_enabled"] is True
    assert co_visit_contract["resource_guard"]["execution_preference"] == "server"


def test_runner_merge_precedence_is_cli_then_tier_then_defaults() -> None:
    raw_config = {
        "source": "semantic",
        "defaults": {
            "run_id": "default_run",
            "output_root": "default_outputs",
            "method_config": {"limit_users": 500, "seed_window": 20},
        },
        "tiers": {
            "smoke": {
                "run_id": "tier_run",
                "method_config": {"limit_users": 20},
            }
        },
    }

    merged = runner._merge_runner_config(
        raw_config,
        "smoke",
        {"run_id": "cli_run", "method_config": {"seed_window": 7}},
    )

    assert merged["run_id"] == "cli_run"
    assert merged["output_root"] == "default_outputs"
    assert merged["method_config"]["limit_users"] == 20
    assert merged["method_config"]["seed_window"] == 7


def test_runner_writes_resolved_tier_and_preserves_requested_alias() -> None:
    raw_config = {
        "tier_aliases": {"route_formal": "all_eligible"},
        "tiers": {"all_eligible": {"method_config": {"limit_users": "all"}}},
    }
    requested_tier = "route_formal"
    resolved_tier = runner._resolve_tier_alias(raw_config, requested_tier)
    config = runner._merge_runner_config(raw_config, resolved_tier, {})
    config["requested_tier"] = requested_tier
    config["tier"] = resolved_tier

    assert config["tier"] == "all_eligible"
    assert config["requested_tier"] == "route_formal"


def test_runner_argparse_none_defaults_do_not_override_tier_or_defaults() -> None:
    args = argparse.Namespace(source="semantic", run_id=None, output_root=None)
    raw_config = {
        "defaults": {"run_id": "default_run", "output_root": "default_outputs"},
        "tiers": {"smoke": {"run_id": "tier_run"}},
    }

    merged = runner._merge_runner_config(raw_config, "smoke", runner._cli_overrides(args))

    assert merged["run_id"] == "tier_run"
    assert merged["output_root"] == "default_outputs"


def test_popular_runner_uses_recent2y_builder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_build_popular_recent2y(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"status": "PASS", "source": "popular"}

    monkeypatch.setattr("rs_lab.experiments.recall.build_pool500_popular_recent2y.build_popular_recent2y", fake_build_popular_recent2y)

    manifest = runner._build_source(
        source="popular",
        config={"recent_2y_governance": {"governance_manifest": "data/processed/amazon_2023_recall_recent_2y_1m_3m/train_only_governance/manifest.json"}},
        config_path=ROOT / "configs" / "recall" / "full_data_pool500" / "popular" / "source_config.yaml",
        tier="formal",
        run_id="unit",
        output_root=tmp_path / "sources",
        output_dir=tmp_path / "sources" / "popular" / "unit",
        overwrite=True,
    )

    assert manifest["status"] == "PASS"
    assert captured["scale_tier"] == "formal"
    assert str(captured["source_output_root"]).endswith("sources")
    assert captured["run_id"] == "unit"


def test_runner_unknown_tier_raises_readable_error() -> None:
    raw_config = {"tiers": {"smoke": {}}}

    with pytest.raises(ValueError, match="unknown tier: missing; available tiers: smoke"):
        runner._merge_runner_config(raw_config, "missing", {})


def test_runner_resolves_tier_aliases_before_merge() -> None:
    raw_config = {
        "tier_aliases": {"dam": "diagnostic"},
        "tiers": {"diagnostic": {"method_config": {"seed_window": 50}}},
    }

    merged = runner._merge_runner_config(raw_config, "dam", {})

    assert merged["method_config"]["seed_window"] == 50


def test_semantic_is_canonical_source_not_semantic_title_alias() -> None:
    assert "semantic" in POOL500_METHOD_SOURCES
    assert "semantic_title_category_expansion" in POOL500_METHOD_SOURCES

    payload = runner._contract_payload(
        "semantic",
        "smoke",
        "unit",
        ROOT / "outputs" / "unit",
        ROOT / "configs" / "recall" / "full_data_pool500" / "semantic" / "source_config.yaml",
        runner._merge_runner_config(runner._load_runner_config(ROOT / "configs" / "recall" / "full_data_pool500" / "semantic" / "source_config.yaml"), "smoke", {}),
    )

    assert payload["contract"]["source"] == "semantic"
    assert payload["contract"]["canonical_source"] == "semantic"
    assert payload["contract"]["canonical_source"] != "semantic_title_category_expansion"
    assert payload["contract"]["canonical_source"] != "semantic_title"


def test_co_visit_config_declares_seven_outputs_and_v2_transition_gates() -> None:
    config = runner._load_runner_config(ROOT / "configs" / "recall" / "full_data_pool500" / "co_visit_fallback_repair" / "source_config.yaml")

    assert set(config["manifest_contract"].values()) == set(REQUIRED_SOURCE_OUTPUTS)
    assert config["algorithm_scope"] == "train_transition_metadata_repair_v2"
    assert config["complete_co_visit_graph_claimed"] is False
    assert config["defaults"]["transition_gates"] == {
        "pair_support_gate": "min_pair_support",
        "distinct_user_support_gate": "min_distinct_user_support",
        "popularity_normalization": "transition_popularity_norm_alpha",
    }


def test_runner_dry_run_exposes_semantic_title_shard_contract() -> None:
    config = runner._load_runner_config(ROOT / "configs" / "recall" / "full_data_pool500" / "semantic_title_category_expansion" / "source_config.yaml")
    payload = runner._contract_payload(
        "semantic_title_category_expansion",
        "recent2y_formal",
        "unit",
        ROOT / "outputs" / "unit",
        ROOT / "configs" / "recall" / "full_data_pool500" / "semantic_title_category_expansion" / "source_config.yaml",
        runner._merge_runner_config(config, "recent2y_formal", {}),
    )

    method_config = payload["contract"]["method_config"]
    assert method_config["checkpoint_every_users"] == 500
    assert method_config["target_user_offset"] == 0
    assert method_config["target_user_limit"] == 50000
    assert method_config["shard_id"] is None
    assert method_config["shard_count"] is None
    assert payload["contract"]["governance"]["candidate_generation_allowed"] is False
    assert payload["contract"]["governance"]["promotion_allowed"] is False


def test_runner_dry_run_exposes_co_visit_shard_contract() -> None:
    config = runner._load_runner_config(ROOT / "configs" / "recall" / "full_data_pool500" / "co_visit_fallback_repair" / "source_config.yaml")
    payload = runner._contract_payload(
        "co_visit_fallback_repair",
        "最终数据集(local_formal)",
        "unit",
        ROOT / "outputs" / "unit",
        ROOT / "configs" / "recall" / "full_data_pool500" / "co_visit_fallback_repair" / "source_config.yaml",
        runner._merge_runner_config(config, "最终数据集(local_formal)", {}),
    )

    method_config = payload["contract"]["method_config"]
    assert method_config["checkpoint_every_users"] == 50
    assert method_config["target_user_offset"] == 0
    assert method_config["target_user_limit"] == 50000
    assert method_config["shard_id"] is None
    assert method_config["shard_count"] is None
    assert payload["contract"]["governance"]["candidate_generation_allowed"] is False
    assert payload["contract"]["governance"]["promotion_allowed"] is False


@pytest.mark.parametrize(
    ("source", "tier"),
    [
        ("semantic", "recent2y_smoke"),
        ("semantic_title_category_expansion", "recent2y_smoke"),
        ("co_visit_fallback_repair", "smoke"),
    ],
)
def test_diagnostic_runner_contract_keeps_candidate_generation_disabled(source: str, tier: str) -> None:
    config_path = ROOT / "configs" / "recall" / "full_data_pool500" / source / "source_config.yaml"
    config = runner._load_runner_config(config_path)
    payload = runner._contract_payload(
        source,
        tier,
        "unit",
        ROOT / "outputs" / "unit",
        config_path,
        runner._merge_runner_config(config, runner._resolve_tier_alias(config, tier), {}),
    )

    governance = payload["contract"]["governance"]
    assert governance["candidate_generation_allowed"] is False
    assert governance["ranking_input_replacement_allowed"] is False
    assert governance["pool1000_allowed"] is False
    assert governance["promotion_allowed"] is False


def test_usercf_source_config_keeps_candidate_generation_disabled() -> None:
    config = runner._load_runner_config(ROOT / "configs" / "recall" / "full_data_pool500" / "usercf_recall" / "source_config.yaml")

    governance = config["governance"]
    assert governance["source_status"] == "DIAGNOSTIC_ONLY"
    assert governance["candidate_generation_allowed"] is False
    assert governance["ranking_input_replacement_allowed"] is False
    assert governance["pool1000_allowed"] is False
    assert governance["promotion_allowed"] is False


def test_swing_config_declares_tiers_and_train_only_boundaries() -> None:
    config = runner._load_runner_config(ROOT / "configs" / "recall" / "full_data_pool500" / "swing_recall" / "source_config.yaml")
    formal = runner._merge_runner_config(config, "formal", {})

    assert set(config["manifest_contract"].values()) == {
        "source_index_manifest.json",
        "swing_recall_edges.jsonl",
        "custom_index_selection_manifest.json",
        "dropped_hot_items.json",
        "resource_audit.json",
        "no_holdout_audit.json",
    }
    assert config["algorithm_scope"] == "train_item_item_swing_graph_v1"
    assert config["complete_swing_graph_claimed"] is False
    assert formal["input_contract"]["train_only"] is True
    assert formal["resource_guard"]["max_graph_users"] == 0
    assert formal["resource_guard"]["max_item_user_freq"] == 1000
    assert formal["swing_enhancement"]["score_mode"] == "datawhale_standard"
    assert formal["swing_enhancement"]["min_user_items"] == 2
    assert formal["swing_enhancement"]["min_pair_support"] == 2
    assert formal["swing_enhancement"]["min_src_item_positive_user_count"] == 2
    assert formal["swing_enhancement"]["min_dst_item_positive_user_count"] == 2
    assert formal["swing_enhancement"]["pre_filter_users_before_item_count"] is True
    assert formal["swing_enhancement"]["disable_post_item_user_filter"] is True
    assert formal["governance"]["ranking_input_replacement_allowed"] is False
    assert formal["governance"]["pool1000_allowed"] is False
    assert formal["governance"]["promotion_allowed"] is False


def test_forbidden_audit_code_covers_oracle_eval_label_youtube_dnn_and_pool1000() -> None:
    assert {"youtube_dnn", "pool1000", "oracle", "eval_label"} <= {token.lower() for token in FORBIDDEN_EVIDENCE_SCOPES}

    forbidden_paths = [
        Path("data/processed/youtube_dnn/train.jsonl"),
        Path("outputs/recall/pool1000/candidates.jsonl"),
        Path("outputs/oracle/manifest.json"),
        Path("outputs/eval_label/eligible_user_manifest.json"),
    ]
    for path in forbidden_paths:
        assert semantic_forbidden_path(path)
        assert semantic_title_forbidden_path(path)
        assert co_visit_forbidden_path(path)


def test_method_docs_pin_runner_config_tiers_and_boundaries() -> None:
    for source in TARGET_SOURCES:
        text = (ROOT / "dic" / "recall_methods" / source / "METHOD.md").read_text(encoding="utf-8")

        assert f"configs/recall/full_data_pool500/{source}/source_config.yaml" in text
        assert "scripts/experiments/recall/pool500/run_pool500_method_source.py" in text
        assert "--tier smoke --dry-run" in text
        assert "dam(diagnostic)" in text
        assert "最终数据集(local_formal)" in text
        assert "不替换 ranking input" in text
        assert "不进入 pool1000" in text
        assert "不得宣称 final READY" in text or "不得宣称 READY" in text
        assert "pool1000_allowed=false" in text
        assert "ranking_input_replacement_allowed=false" in text
        assert "-m rs_lab.experiments.recall.run_full_data_pool500_recall_only" not in text

    co_visit_text = (ROOT / "dic" / "recall_methods" / "co_visit_fallback_repair" / "METHOD.md").read_text(encoding="utf-8")
    assert "algorithm_scope=train_transition_metadata_repair_v2" in co_visit_text
    assert "complete_co_visit_graph_claimed=false" in co_visit_text
    assert "pair_support" in co_visit_text
    assert "distinct_user_support" in co_visit_text
    assert "support gate" in co_visit_text
