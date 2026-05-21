from __future__ import annotations

import argparse
import json
import sys
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a pool500 diagnostic method source artifact set.")
    parser.add_argument("--source", choices=POOL500_METHOD_SOURCES)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = _load_runner_config(args.config)
    source = args.source or config.get("source")
    if source not in POOL500_METHOD_SOURCES:
        raise ValueError(f"unknown pool500 method source: {source}")
    run_id = args.run_id or config.get("run_id") or _default_run_id(source)
    output_root = args.output_root or Path(str(config.get("output_root") or DEFAULT_OUTPUT_ROOT))
    output_dir = _resolve_method_output_dir(output_root, source, run_id)

    if args.dry_run:
        print(json.dumps(_contract_payload(source, run_id, output_dir), ensure_ascii=False, indent=2))
        return

    if source == "category":
        from rs_lab.experiments.recall.pool500.methods.category import build_category_method_source

        manifest = build_category_method_source(
            config=config,
            run_id=run_id,
            output_dir=output_dir,
            overwrite=args.overwrite,
        )
        print(json.dumps({"status": manifest["status"], "source": source, "run_id": run_id, "output_dir": str(output_dir)}, ensure_ascii=False, indent=2))
        return

    if source == "popular":
        from rs_lab.experiments.recall.pool500.methods.popular import build_popular_method_source

        manifest = build_popular_method_source(
            config=config,
            run_id=run_id,
            output_dir=output_dir,
            overwrite=args.overwrite,
        )
        print(json.dumps({"status": manifest["status"], "source": source, "run_id": run_id, "output_dir": str(output_dir)}, ensure_ascii=False, indent=2))
        return

    if source == "itemcf_strong":
        from rs_lab.experiments.recall.pool500.methods.itemcf_strong import build_itemcf_strong_method_source

        manifest = build_itemcf_strong_method_source(
            config=config,
            run_id=run_id,
            output_dir=output_dir,
            overwrite=args.overwrite,
        )
        print(json.dumps({"status": manifest["status"], "source": source, "run_id": run_id, "output_dir": str(output_dir)}, ensure_ascii=False, indent=2))
        return

    if source == "co_visit_fallback_repair":
        from rs_lab.experiments.recall.pool500.methods.co_visit_fallback_repair.builder import build_co_visit_fallback_repair_source

        manifest = build_co_visit_fallback_repair_source(
            clean_manifest_path=Path("data/processed/amazon_2023_recall_clean_full/manifest.json"),
            lightweight_views_manifest_path=Path("data/processed/amazon_2023_recall_views_full_lightweight/manifest.json"),
            eligible_user_manifest_path=Path("outputs/recall/pool500_main_route_direct_recall_full_promoted/eligible_user_manifest.json"),
            output_root=output_root,
            run_id=run_id,
            config_path=args.config,
            overwrite=args.overwrite,
        )
        print(json.dumps({"status": manifest["status"], "source": source, "run_id": run_id, "output_dir": str(output_dir)}, ensure_ascii=False, indent=2))
        return

    raise NotImplementedError(f"pool500 method source build is not implemented for {source}; use --dry-run to inspect the contract")


def _load_runner_config(config_path: Path | None) -> dict[str, Any]:
    if config_path is None:
        return {}
    path = config_path if config_path.is_absolute() else ROOT / config_path
    return load_config(path)


def _resolve_method_output_dir(output_root: Path, source: str, run_id: str) -> Path:
    root = output_root if output_root.is_absolute() else ROOT / output_root
    if root.name == source:
        return root / run_id
    return method_output_dir(root, source, run_id)


def _default_run_id(source: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{source}_{timestamp}"


def _contract_payload(source: str, run_id: str, output_dir: Path) -> dict[str, Any]:
    return {
        "source": source,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "required_outputs": list(REQUIRED_SOURCE_OUTPUTS),
    }


if __name__ == "__main__":
    main()
