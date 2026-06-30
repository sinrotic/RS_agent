from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rs_core.common.config import load_config
from rs_core.online.recall.candidate_merge import load_semantic_index
from rs_core.online.recall.online_retrieval import CandidateRetrievalOrchestrator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "configs/serving/online_service.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test online retrieval providers without training or full import.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--user-id", action="append", default=[])
    parser.add_argument("--item", action="append", default=[])
    parser.add_argument("--candidate-pool-size", type=int, default=20)
    parser.add_argument("--limit-users", type=int, default=1)
    args = parser.parse_args()

    config_path = _resolve(args.config)
    config = load_config(config_path)
    semantic_index = _load_semantic_index(config)
    orchestrator = CandidateRetrievalOrchestrator.from_config(config, config_path=str(config_path), semantic_index=semantic_index)
    user_ids = (args.user_id or ["smoke-user"])[: max(1, int(args.limit_users))]
    sequence_items = [str(item) for item in args.item if str(item or "").strip()]
    reports = []
    for user_id in user_ids:
        result = orchestrator.retrieve(
            {"user_id": str(user_id), "recent_item_sequence": sequence_items, "recent_positive_item_sequence": sequence_items},
            config=config,
            candidate_pool_size=args.candidate_pool_size,
        )
        reports.append({
            "user_id": str(user_id),
            "candidate_count": len(result.candidates),
            "fallback_used": result.fallback_used,
            "provider_coverage": result.diagnostics.get("provider_coverage", {}),
        })
    print(json.dumps({"readiness": orchestrator.readiness(), "reports": reports}, ensure_ascii=False, indent=2))


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def _load_semantic_index(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not config.get("semantic_enabled"):
        return {}
    views_dir = _resolve(Path(str(config.get("views_dir") or "")))
    semantic_path = views_dir / "semantic_recall_inputs.jsonl"
    if not semantic_path.exists():
        return {}
    return load_semantic_index(semantic_path, config.get("semantic_text_fields"))


if __name__ == "__main__":
    main()
