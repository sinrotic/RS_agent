from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.agent.rag.semantic_description import (  # noqa: E402
    DEFAULT_DOCUMENT_COUNT,
    FIELD_WEIGHTS,
    GENERIC_TOKENS,
    STRICT_QUERY_FIXTURES,
    diagnose,
    evaluate_intent,
    SQLiteSemanticDescriptionStore,
    fixture_query_terms,
    load_query_buckets,
    load_records,
    normalized_text,
    ordered_unique,
    phrase_present,
    record_text,
    score_record,
    tokens,
)

DEFAULT_OUTPUT_DIR = Path("outputs/diagnostics/semantic_description_recall_strict_20260608")
DEFAULT_SEMANTIC_INPUTS = Path(
    "data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/semantic_recall_inputs.jsonl"
)
DEFAULT_INVERTED_INDEX = Path(
    "data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/semantic_inverted_index.jsonl"
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose description-driven semantic recall quality with strict intent rules.")
    parser.add_argument("--semantic-inputs", type=Path, default=DEFAULT_SEMANTIC_INPUTS)
    parser.add_argument("--inverted-index", type=Path, default=DEFAULT_INVERTED_INDEX)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--per-token-limit", type=int, default=10_000)
    parser.add_argument("--candidate-limit", type=int, default=80_000)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--sqlite-index", type=Path, default=None)
    args = parser.parse_args()
    if args.top_k != 10:
        raise ValueError("this diagnostic fixes --top-k at 10 so @10 metric names stay unambiguous")

    store = SQLiteSemanticDescriptionStore(args.sqlite_index) if args.sqlite_index else None
    result = diagnose(
        semantic_inputs_path=args.semantic_inputs,
        inverted_index_path=args.inverted_index,
        output_dir=args.output_dir,
        per_token_limit=args.per_token_limit,
        candidate_limit=args.candidate_limit,
        top_k=args.top_k,
        store=store,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


__all__ = [
    "DEFAULT_DOCUMENT_COUNT",
    "DEFAULT_INVERTED_INDEX",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_SEMANTIC_INPUTS",
    "FIELD_WEIGHTS",
    "GENERIC_TOKENS",
    "STRICT_QUERY_FIXTURES",
    "diagnose",
    "evaluate_intent",
    "fixture_query_terms",
    "load_query_buckets",
    "load_records",
    "main",
    "normalized_text",
    "ordered_unique",
    "phrase_present",
    "record_text",
    "score_record",
    "tokens",
]


if __name__ == "__main__":
    main()
