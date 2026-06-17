from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.recsys.semantic_description import build_sqlite_semantic_description_index  # noqa: E402

DEFAULT_SEMANTIC_INPUTS = Path(
    "data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/semantic_recall_inputs.jsonl"
)
DEFAULT_INVERTED_INDEX = Path(
    "data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/semantic_inverted_index.jsonl"
)
DEFAULT_INDEX_PATH = Path("outputs/diagnostics/semantic_description_index_20260608/semantic_description_index.sqlite")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an equivalent SQLite index for semantic description retrieval.")
    parser.add_argument("--semantic-inputs", type=Path, default=DEFAULT_SEMANTIC_INPUTS)
    parser.add_argument("--inverted-index", type=Path, default=DEFAULT_INVERTED_INDEX)
    parser.add_argument("--index-path", type=Path, default=DEFAULT_INDEX_PATH)
    parser.add_argument("--manifest-path", type=Path, default=None)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    manifest = build_sqlite_semantic_description_index(
        semantic_inputs_path=args.semantic_inputs,
        inverted_index_path=args.inverted_index,
        index_path=args.index_path,
        manifest_path=args.manifest_path,
        overwrite=args.overwrite,
        batch_size=args.batch_size,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
