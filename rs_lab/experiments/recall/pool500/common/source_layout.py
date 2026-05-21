from __future__ import annotations

from pathlib import Path

POOL500_METHOD_SOURCES = (
    "category",
    "popular",
    "swing_recall",
    "usercf_recall",
    "itemcf_weak",
    "itemcf_strong",
    "two_tower",
    "semantic_title_category_expansion",
    "co_visit_fallback_repair",
)

REQUIRED_SOURCE_OUTPUTS = (
    "method_dataset_manifest.json",
    "source_index_manifest.json",
    "candidates.jsonl",
    "coverage_audit.json",
    "undercoverage_audit.json",
    "resource_audit.json",
    "no_holdout_audit.json",
)

FORBIDDEN_EVIDENCE_SCOPES = (
    "holdout",
    "valid",
    "test",
    "LOPO",
    "clean_10000",
)

def method_output_dir(output_root: Path, source: str, run_id: str) -> Path:
    if source not in POOL500_METHOD_SOURCES:
        raise ValueError(f"unknown pool500 method source: {source}")
    return output_root / source / run_id
