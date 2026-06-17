from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.recsys.semantic_description import (  # noqa: E402
    SQLiteSemanticDescriptionStore,
    retrieve_fixture_results,
    tokens,
)

DEFAULT_SEMANTIC_INPUTS = Path(
    "data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/semantic_recall_inputs.jsonl"
)
DEFAULT_INVERTED_INDEX = Path(
    "data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/semantic_inverted_index.jsonl"
)
DEFAULT_OUTPUT_PATH = Path("outputs/diagnostics/semantic_live_query_20260608/result.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one live semantic description retrieval query.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--semantic-inputs", type=Path, default=DEFAULT_SEMANTIC_INPUTS)
    parser.add_argument("--inverted-index", type=Path, default=DEFAULT_INVERTED_INDEX)
    parser.add_argument("--sqlite-index", type=Path, default=None)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--core-terms", default="")
    parser.add_argument("--must-terms", default="")
    parser.add_argument("--category-any", default="")
    parser.add_argument("--negative-phrases", default="")
    parser.add_argument("--intent-phrases", default="")
    parser.add_argument("--per-token-limit", type=int, default=2_000)
    parser.add_argument("--candidate-limit", type=int, default=1_000)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    core_terms = _csv(args.core_terms) or _default_core_terms(args.query)
    fixture: dict[str, Any] = {
        "id": "live_query",
        "description": args.query,
        "core_terms": core_terms,
        "must_terms": _csv(args.must_terms),
        "must_any_groups": [core_terms] if core_terms else [],
        "intent_phrases": _csv(args.intent_phrases) or ([" ".join(core_terms)] if core_terms else []),
        "category_any": _csv(args.category_any),
        "negative_phrases": _csv(args.negative_phrases),
    }
    store = SQLiteSemanticDescriptionStore(args.sqlite_index) if args.sqlite_index else None
    started_at = perf_counter()
    results, _ = retrieve_fixture_results(
        fixtures=[fixture],
        semantic_inputs_path=args.semantic_inputs,
        inverted_index_path=args.inverted_index,
        per_token_limit=args.per_token_limit,
        candidate_limit=args.candidate_limit,
        store=store,
    )
    latency_ms = round((perf_counter() - started_at) * 1000, 3)
    query_result = results[0]
    top_rows = query_result.rows[: args.top_k]
    payload = {
        "schema_version": "semantic_live_description_query_v1",
        "eval_scope": "live_train_metadata_semantic_retrieval",
        "label_inputs_role": "not_used",
        "oracle_label_injection": False,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "query": args.query,
        "fixture": fixture,
        "candidate_pool_size": len(query_result.candidate_ids),
        "scored_count": len(query_result.rows),
        "latency_ms": latency_ms,
        "top_k": [
            {
                "rank": rank,
                "item_id": row.item_id,
                "score": round(row.score, 6),
                "title": row.record.get("title_clean"),
                "main_category": row.record.get("main_category"),
                "details": row.details,
            }
            for rank, row in enumerate(top_rows, start=1)
        ],
    }
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output_path": str(args.output_path),
                "candidate_pool_size": payload["candidate_pool_size"],
                "scored_count": payload["scored_count"],
                "latency_ms": latency_ms,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _default_core_terms(query: str) -> list[str]:
    values = []
    for token in tokens(query):
        if token not in values:
            values.append(token)
        if len(values) >= 2:
            break
    return values


if __name__ == "__main__":
    main()
