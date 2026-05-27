from __future__ import annotations

from .base import DEFERRED, DIAGNOSTIC_ONLY, READY, RecallSourceSpec

_RECALL_SOURCE_SPECS: tuple[RecallSourceSpec, ...] = (
    RecallSourceSpec(
        name="category",
        readiness=READY,
        role="stable_category_coverage",
        eligible_user_policy="medium_behavior_or_fallback",
        method_doc="dic/recall_methods/category/METHOD.md",
        latest_artifact="outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/sources/category/manifest.json",
        latest_row_count=30193,
    ),
    RecallSourceSpec(
        name="popular",
        readiness=READY,
        role="coverage_backfill",
        eligible_user_policy="fallback_only",
        method_doc="dic/recall_methods/popular/METHOD.md",
        latest_artifact="outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/sources/popular/manifest.json",
        latest_row_count=81289,
    ),
    RecallSourceSpec(
        name="swing_recall",
        readiness=READY,
        role="behavioral_item_expansion",
        eligible_user_policy="heavy_cf_eligible_or_medium_behavior",
        method_doc="dic/recall_methods/swing_recall/METHOD.md",
        latest_artifact="outputs/recall/pool500_sidecar_fix/swing_recall_v2/source_index_manifest.json",
        latest_row_count=3668,
    ),
    RecallSourceSpec(
        name="usercf_recall",
        readiness=READY,
        role="heavy_user_neighbor_recall",
        eligible_user_policy="heavy_cf_eligible",
        method_doc="dic/recall_methods/usercf_recall/METHOD.md",
        latest_artifact="outputs/recall/pool500_usercf_method_train/usercf_recall/usercf_v1_formal_route_ready/source_index_manifest.json",
        latest_row_count=17509,
    ),
    RecallSourceSpec(
        name="itemcf_weak",
        readiness=DIAGNOSTIC_ONLY,
        role="broad_item_neighbor_recall",
        eligible_user_policy="heavy_cf_eligible_or_medium_behavior",
        method_doc="dic/recall_methods/itemcf_weak/METHOD.md",
        latest_artifact="outputs/recall/pool500_sidecar_fix/itemcf_weak_target500_guarded/source_index_manifest.json",
        latest_row_count=345,
    ),
    RecallSourceSpec(
        name="itemcf_strong",
        readiness=DIAGNOSTIC_ONLY,
        role="high_confidence_item_neighbor_recall",
        eligible_user_policy="sequence_sufficient_or_collaborative_rich_for_relaxed_strong_itemcf",
        method_doc="dic/recall_methods/itemcf_strong/METHOD.md",
        latest_artifact="outputs/recall/pool500_method_sources/itemcf_strong_relaxed_seedsrc_v3_from_method_dataset/itemcf_strong/formal_sharded/source_index_manifest.json",
        latest_row_count=1536320,
    ),
    RecallSourceSpec(
        name="semantic",
        readiness=DEFERRED,
        role="semantic_metadata_recall",
        eligible_user_policy="metadata_rich_or_behavior_sparse",
        method_doc="dic/recall_methods/semantic/METHOD.md",
        latest_artifact="outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/sources/semantic/manifest.json",
        latest_row_count=0,
    ),
    RecallSourceSpec(
        name="semantic_title_category_expansion",
        readiness=DEFERRED,
        role="semantic_category_expansion",
        eligible_user_policy="metadata_rich_or_behavior_sparse",
        method_doc="dic/recall_methods/semantic_title_category_expansion/METHOD.md",
        latest_artifact="outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/sources/semantic_title_category_expansion/manifest.json",
        latest_row_count=0,
    ),
    RecallSourceSpec(
        name="co_visit_fallback_repair",
        readiness=DEFERRED,
        role="fallback_repair",
        eligible_user_policy="cf_weak_connection_repair",
        method_doc="dic/recall_methods/co_visit_fallback_repair/METHOD.md",
        latest_artifact="outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/sources/co_visit_fallback_repair/manifest.json",
        latest_row_count=0,
    ),
    RecallSourceSpec(
        name="two_tower",
        readiness=DEFERRED,
        role="embedding_ann_recall",
        eligible_user_policy="future_embedding_recall",
        method_doc="dic/recall_methods/two_tower/METHOD.md",
        latest_artifact="outputs/recall/pool500_sidecar_fix/recall_only_target500_with_sidecars/sources/two_tower/manifest.json",
        latest_row_count=0,
    ),
)

_RECALL_SOURCE_SPECS_BY_NAME = {spec.name: spec for spec in _RECALL_SOURCE_SPECS}


def list_recall_source_specs() -> tuple[RecallSourceSpec, ...]:
    return _RECALL_SOURCE_SPECS


def get_recall_source_spec(name: str) -> RecallSourceSpec:
    return _RECALL_SOURCE_SPECS_BY_NAME[name]


def list_candidate_generating_sources() -> tuple[RecallSourceSpec, ...]:
    return tuple(spec for spec in _RECALL_SOURCE_SPECS if spec.candidate_generating)
