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
    assert payload["contract"]["source_status"] == "TARGET_SLICE_DIAGNOSTIC"
    assert Path(payload["config_path"]) == ROOT / "configs" / "recall" / "full_data_pool500" / "semantic" / "source_config.yaml"
    assert not output_root.exists()


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


def test_runner_argparse_none_defaults_do_not_override_tier_or_defaults() -> None:
    args = argparse.Namespace(source="semantic", run_id=None, output_root=None)
    raw_config = {
        "defaults": {"run_id": "default_run", "output_root": "default_outputs"},
        "tiers": {"smoke": {"run_id": "tier_run"}},
    }

    merged = runner._merge_runner_config(raw_config, "smoke", runner._cli_overrides(args))

    assert merged["run_id"] == "tier_run"
    assert merged["output_root"] == "default_outputs"


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


def test_co_visit_config_declares_seven_outputs_and_v0_scope() -> None:
    config = runner._load_runner_config(ROOT / "configs" / "recall" / "full_data_pool500" / "co_visit_fallback_repair" / "source_config.yaml")

    assert set(config["manifest_contract"].values()) == set(REQUIRED_SOURCE_OUTPUTS)
    assert config["algorithm_scope"] == "train_transition_metadata_repair_v0"
    assert config["complete_co_visit_graph_claimed"] is False
    assert config["defaults"]["follow_up_metrics"] == {
        "pair_support": "follow_up_only_not_gate",
        "distinct_user_support": "follow_up_only_not_gate",
    }


def test_swing_config_declares_tiers_and_train_only_boundaries() -> None:
    config = runner._load_runner_config(ROOT / "configs" / "recall" / "full_data_pool500" / "swing_recall" / "source_config.yaml")
    local_formal = runner._merge_runner_config(config, "最终数据集(local_formal)", {})

    assert set(config["manifest_contract"].values()) == set(REQUIRED_SOURCE_OUTPUTS)
    assert config["algorithm_scope"] == "train_item_item_swing_graph_v1"
    assert config["complete_swing_graph_claimed"] is False
    assert local_formal["input_contract"]["train_only"] is True
    assert local_formal["resource_guard"]["max_graph_users"] == 120000
    assert local_formal["resource_guard"]["max_item_user_freq"] == 600
    assert local_formal["swing_enhancement"]["min_user_items"] == 2
    assert local_formal["swing_enhancement"]["min_pair_support"] == 2
    assert local_formal["governance"]["ranking_input_replacement_allowed"] is False
    assert local_formal["governance"]["pool1000_allowed"] is False
    assert local_formal["governance"]["promotion_allowed"] is False


def test_forbidden_audit_code_covers_youtube_dnn_and_pool1000() -> None:
    assert {"youtube_dnn", "pool1000"} <= {token.lower() for token in FORBIDDEN_EVIDENCE_SCOPES}

    forbidden_paths = [
        Path("data/processed/youtube_dnn/train.jsonl"),
        Path("outputs/recall/pool1000/candidates.jsonl"),
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
        assert "不得宣称 READY" in text
        assert "pool1000_allowed=false" in text
        assert "ranking_input_replacement_allowed=false" in text
        assert "-m rs_lab.experiments.recall.run_full_data_pool500_recall_only" not in text

    co_visit_text = (ROOT / "dic" / "recall_methods" / "co_visit_fallback_repair" / "METHOD.md").read_text(encoding="utf-8")
    assert "algorithm_scope=train_transition_metadata_repair_v0" in co_visit_text
    assert "complete_co_visit_graph_claimed=false" in co_visit_text
    assert "pair_support" in co_visit_text
    assert "distinct_user_support" in co_visit_text
    assert "不是 gate" in co_visit_text
