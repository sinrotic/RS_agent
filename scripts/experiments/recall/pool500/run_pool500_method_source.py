from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.config import load_config
from rs_lab.experiments.recall.pool500.common.source_layout import (
    POOL500_METHOD_SOURCES,
    REQUIRED_SOURCE_OUTPUTS,
    method_output_dir,
)


DEFAULT_OUTPUT_ROOT = Path("outputs/recall/pool500_method_sources")
CONFIG_ROOT = Path("configs/recall/full_data_pool500")
DEFAULT_CLEAN_MANIFEST = Path("data/processed/amazon_2023_recall_clean_full/manifest.json")
DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST = Path("data/processed/amazon_2023_recall_views_full_lightweight/manifest.json")
DEFAULT_ELIGIBLE_USER_MANIFEST = Path("outputs/recall/pool500_main_route_direct_recall_full_promoted/eligible_user_manifest.json")
RUNNER_METHOD_SOURCES = tuple(dict.fromkeys((*POOL500_METHOD_SOURCES, "semantic")))
CONFIG_STRUCTURAL_KEYS = {"defaults", "tiers", "tier_aliases"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a pool500 diagnostic method source artifact set.")
    parser.add_argument("--source", choices=RUNNER_METHOD_SOURCES)
    parser.add_argument("--tier")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--route-ready", action="store_true")
    args = parser.parse_args()

    source = _resolve_source(args.source, args.config)
    config_path = _resolve_config_path(args.config, source)
    raw_config = _load_runner_config(config_path)
    source = args.source or raw_config.get("source") or source
    if source not in RUNNER_METHOD_SOURCES:
        raise ValueError(f"unknown pool500 method source: {source}")
    tier = _resolve_tier_alias(raw_config, args.tier or raw_config.get("tier") or raw_config.get("default_tier"))
    cli_overrides = _cli_overrides(args)
    config = _merge_runner_config(raw_config, tier, cli_overrides)
    config["source"] = source
    if tier is not None:
        config["tier"] = tier
    config["config_path"] = str(config_path)

    run_id = str(config.get("run_id") or _default_run_id(source))
    output_root = Path(str(config.get("output_root") or DEFAULT_OUTPUT_ROOT))
    output_dir = _resolve_method_output_dir(output_root, source, run_id)

    if args.dry_run:
        print(json.dumps(_contract_payload(source, tier, run_id, output_dir, config_path, config), ensure_ascii=False, indent=2))
        return

    manifest = _build_source(
        source=source,
        config=config,
        config_path=config_path,
        run_id=run_id,
        output_root=output_root,
        output_dir=output_dir,
        overwrite=args.overwrite,
        route_ready=args.route_ready,
    )
    print(json.dumps({"status": manifest["status"], "source": source, "tier": tier, "run_id": run_id, "output_dir": str(output_dir)}, ensure_ascii=False, indent=2))


def _resolve_source(cli_source: str | None, config_path: Path | None) -> str:
    if cli_source:
        return cli_source
    if config_path is not None:
        config = _load_runner_config(config_path)
        source = config.get("source")
        if source:
            return str(source)
    raise ValueError("--source is required when --config is omitted or config has no source")


def _resolve_config_path(config_path: Path | None, source: str) -> Path:
    path = config_path or CONFIG_ROOT / source / "source_config.yaml"
    return path if path.is_absolute() else ROOT / path


def _load_runner_config(config_path: Path | None) -> dict[str, Any]:
    if config_path is None:
        return {}
    path = config_path if config_path.is_absolute() else ROOT / config_path
    if not path.is_file():
        return {}
    loaded = load_config(path)
    return loaded if isinstance(loaded, dict) else {}


def _cli_overrides(args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if args.source is not None:
        overrides["source"] = args.source
    if args.run_id is not None:
        overrides["run_id"] = args.run_id
    if args.output_root is not None:
        overrides["output_root"] = str(args.output_root)
    return overrides


def _merge_runner_config(raw_config: dict[str, Any], tier: str | None, cli_overrides: dict[str, Any]) -> dict[str, Any]:
    config = {key: deepcopy(value) for key, value in raw_config.items() if key not in CONFIG_STRUCTURAL_KEYS}
    defaults = raw_config.get("defaults") if isinstance(raw_config.get("defaults"), dict) else {}
    tiers = raw_config.get("tiers") if isinstance(raw_config.get("tiers"), dict) else {}
    tier_config: dict[str, Any] = {}
    resolved_tier = _resolve_tier_alias(raw_config, tier)
    if tiers:
        if resolved_tier is None:
            raise ValueError(f"--tier is required; available tiers: {', '.join(sorted(str(key) for key in tiers))}")
        if resolved_tier not in tiers:
            raise ValueError(f"unknown tier: {tier}; available tiers: {', '.join(sorted(str(key) for key in tiers))}")
        selected = tiers[resolved_tier]
        if not isinstance(selected, dict):
            raise ValueError(f"tier config must be a mapping: {resolved_tier}")
        tier_config = selected
    return _deep_merge(config, defaults, tier_config, cli_overrides)


def _resolve_tier_alias(raw_config: dict[str, Any], tier: str | None) -> str | None:
    if tier is None:
        return None
    aliases = raw_config.get("tier_aliases")
    if not isinstance(aliases, dict):
        return str(tier)
    return str(aliases.get(str(tier), tier))


def _deep_merge(*configs: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for config in configs:
        for key, value in config.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = _deep_merge(merged[key], value)
            else:
                merged[key] = deepcopy(value)
    return merged


def _build_source(
    *,
    source: str,
    config: dict[str, Any],
    config_path: Path,
    run_id: str,
    output_root: Path,
    output_dir: Path,
    overwrite: bool,
    route_ready: bool = False,
) -> dict[str, Any]:
    if source == "category":
        from rs_lab.experiments.recall.pool500.methods.category import build_category_method_source

        return build_category_method_source(
            config=config,
            run_id=run_id,
            output_dir=output_dir,
            overwrite=overwrite,
        )

    if source == "popular":
        from rs_lab.experiments.recall.pool500.methods.popular import build_popular_method_source

        return build_popular_method_source(
            config=config,
            run_id=run_id,
            output_dir=output_dir,
            overwrite=overwrite,
        )

    if source == "itemcf_strong":
        from rs_lab.experiments.recall.pool500.methods.itemcf_strong import build_itemcf_strong_method_source

        return build_itemcf_strong_method_source(
            config=config,
            run_id=run_id,
            output_dir=output_dir,
            overwrite=overwrite,
        )

    if source == "usercf_recall":
        from rs_lab.experiments.recall.pool500.methods.usercf_recall.builder import build_usercf_recall_method_source

        return build_usercf_recall_method_source(
            clean_manifest_path=_config_path(config, DEFAULT_CLEAN_MANIFEST, "clean_manifest", "clean_manifest_path"),
            method_dataset_manifest_path=_config_optional_path(config, "method_dataset_manifest", "method_dataset_manifest_path"),
            eligible_user_quality_manifest=_config_optional_path(config, "eligible_user_quality_manifest", "eligible_user_quality_manifest_path"),
            output_root=output_root,
            run_id=run_id,
            source_config_path=config_path,
            target_user_limit=_config_optional_int(config, "target_user_limit"),
            candidate_top_k_per_user=_config_optional_int(config, "candidate_top_k_per_user"),
            generation_usercf_per_user=_config_optional_nested_int(config, "generation_config_overrides", "usercf_per_user"),
            similar_users_top_k=_config_optional_int(config, "similar_users_top_k"),
            target_batch_size=_config_optional_int(config, "target_batch_size"),
            shard_count=_config_optional_int(config, "shard_count"),
            max_items_per_user=_config_optional_int(config, "max_items_per_user"),
            max_item_user_freq=_config_optional_int(config, "max_item_user_freq"),
            max_rss_mb=_config_optional_int(config, "max_rss_mb"),
            overwrite=overwrite,
            route_ready=route_ready,
        )

    if source == "swing_recall":
        from rs_lab.experiments.recall.pool500.methods.swing_recall.enhanced_source import build_pool500_swing_recall_enhanced_source

        input_contract = config.get("input_contract") if isinstance(config.get("input_contract"), dict) else {}
        resource_guard = config.get("resource_guard") if isinstance(config.get("resource_guard"), dict) else {}
        swing_enhancement = config.get("swing_enhancement") if isinstance(config.get("swing_enhancement"), dict) else {}
        return build_pool500_swing_recall_enhanced_source(
            clean_manifest_path=_config_path(input_contract, DEFAULT_CLEAN_MANIFEST, "clean_manifest", "clean_manifest_path"),
            baseline_dir=_config_path(input_contract, DEFAULT_ELIGIBLE_USER_MANIFEST.parent, "baseline_dir", "baseline_path"),
            output_root=output_dir.parent,
            run_id=run_id,
            max_graph_users=_config_int(resource_guard, "max_graph_users", 120000),
            max_items_per_user=_config_int(resource_guard, "max_items_per_user", 80),
            max_item_user_freq=_config_int(resource_guard, "max_item_user_freq", 600),
            min_user_items=_config_int(swing_enhancement, "min_user_items", 2),
            min_pair_support=_config_int(swing_enhancement, "min_pair_support", 1),
            per_seed_top_k=_config_int(swing_enhancement, "per_seed_top_k", 120),
            seed_window=_config_int(swing_enhancement, "seed_window", 40),
            per_user=_config_int(swing_enhancement, "per_user", 120),
            swing_alpha=_config_float(swing_enhancement, "swing_alpha", 1.0),
            min_free_bytes=_config_int(resource_guard, "min_free_bytes", 10 * 1024**3),
            overwrite=overwrite,
        )

    if source == "semantic":
        from rs_lab.experiments.recall.pool500.methods.semantic import build_semantic_method_source

        return build_semantic_method_source(
            config=config,
            run_id=run_id,
            output_dir=output_dir,
            overwrite=overwrite,
        )

    if source == "semantic_title_category_expansion":
        from rs_lab.experiments.recall.pool500.methods.semantic_title_category_expansion import build_semantic_title_category_expansion_source

        input_contract = config.get("input_contract") if isinstance(config.get("input_contract"), dict) else {}
        resource_guard = config.get("resource_guard") if isinstance(config.get("resource_guard"), dict) else {}
        return build_semantic_title_category_expansion_source(
            clean_manifest_path=_config_path(input_contract, DEFAULT_CLEAN_MANIFEST, "clean_manifest", "clean_manifest_path"),
            lightweight_views_manifest_path=_config_path(input_contract, DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST, "lightweight_views_manifest", "lightweight_views_manifest_path"),
            eligible_user_manifest_path=_config_path(input_contract, DEFAULT_ELIGIBLE_USER_MANIFEST, "eligible_user_manifest", "eligible_user_manifest_path"),
            output_root=output_root,
            run_id=run_id,
            seed_window=_config_int(resource_guard, "seed_window", 20),
            per_user=_config_int(resource_guard, "per_user", 80),
            per_seed=_config_int(resource_guard, "per_seed", 40),
            per_token_item_limit=_config_int(resource_guard, "per_token_item_limit", 2000),
            max_candidate_items=_config_int(resource_guard, "max_candidate_items", 80000),
            selection_mode=str(config.get("selection_mode") or resource_guard.get("selection_mode") or "title_category_scorer"),
            overwrite=overwrite,
        )

    if source == "co_visit_fallback_repair":
        from rs_lab.experiments.recall.pool500.methods.co_visit_fallback_repair.builder import build_co_visit_fallback_repair_source

        input_contract = config.get("input_contract") if isinstance(config.get("input_contract"), dict) else {}
        method_config = config.get("method_config") if isinstance(config.get("method_config"), dict) else {}
        return build_co_visit_fallback_repair_source(
            clean_manifest_path=_config_path(input_contract, DEFAULT_CLEAN_MANIFEST, "clean_manifest", "clean_manifest_path"),
            lightweight_views_manifest_path=_config_path(input_contract, DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST, "lightweight_views_manifest", "lightweight_views_manifest_path"),
            eligible_user_manifest_path=_config_path(input_contract, DEFAULT_ELIGIBLE_USER_MANIFEST, "eligible_user_manifest", "eligible_user_manifest_path"),
            output_root=output_root,
            run_id=run_id,
            config_path=config_path,
            max_metadata_rows=_config_int(method_config, "max_metadata_rows", 250_000),
            candidate_per_user=_config_int(method_config, "candidate_per_user", 120),
            candidate_per_seed=_config_int(method_config, "candidate_per_seed", 40),
            seed_window=_config_int(method_config, "seed_window", 30),
            transition_window=_config_int(method_config, "transition_window", 5),
            transition_per_seed=_config_int(method_config, "transition_per_seed", 200),
            checkpoint_every_users=_config_int(method_config, "checkpoint_every_users", 50),
            overwrite=overwrite,
        )

    raise NotImplementedError(f"pool500 method source build is not implemented for {source}; use --dry-run to inspect the contract")


def _config_path(config: dict[str, Any], default: Path, *keys: str) -> Path:
    for key in keys:
        value = config.get(key)
        if value:
            path = Path(str(value))
            return path if path.is_absolute() else ROOT / path
    return default if default.is_absolute() else ROOT / default


def _config_int(config: dict[str, Any], key: str, default: int) -> int:
    return int(config.get(key, default))


def _config_float(config: dict[str, Any], key: str, default: float) -> float:
    return float(config.get(key, default))


def _config_optional_path(config: dict[str, Any], *keys: str) -> Path | None:
    for key in keys:
        value = config.get(key)
        if value:
            path = Path(str(value))
            return path if path.is_absolute() else ROOT / path
    return None


def _config_optional_int(config: dict[str, Any], key: str) -> int | None:
    return int(config[key]) if key in config and config[key] is not None else None


def _config_optional_nested_int(config: dict[str, Any], section: str, key: str) -> int | None:
    payload = config.get(section) if isinstance(config.get(section), dict) else {}
    return int(payload[key]) if key in payload and payload[key] is not None else None


def _resolve_method_output_dir(output_root: Path, source: str, run_id: str) -> Path:
    root = output_root if output_root.is_absolute() else ROOT / output_root
    if root.name == source:
        return root / run_id
    if source in POOL500_METHOD_SOURCES:
        return method_output_dir(root, source, run_id)
    return root / source / run_id


def _default_run_id(source: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{source}_{timestamp}"


def _contract_payload(source: str, tier: str | None, run_id: str, output_dir: Path, config_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": source,
        "tier": tier,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "required_outputs": list(REQUIRED_SOURCE_OUTPUTS),
        "config_path": str(config_path),
        "contract": _contract_summary(config),
    }


def _contract_summary(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": config.get("source"),
        "canonical_source": config.get("canonical_source"),
        "source_status": config.get("source_status"),
        "manifest_contract": config.get("manifest_contract", {}),
        "governance": config.get("governance", {}),
        "input_contract": config.get("input_contract", {}),
    }


if __name__ == "__main__":
    main()
