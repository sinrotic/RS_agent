from __future__ import annotations

from .base import DEFERRED, DIAGNOSTIC_ONLY, READY, READY_CANDIDATE, RecallSourceSpec

_RECALL_SOURCE_SPECS: tuple[RecallSourceSpec, ...] = (
    RecallSourceSpec(
        name='category',
        readiness=READY,
        role='train_only_category_index_fallback',
        eligible_user_policy='fallback_only_medium_behavior_sequence_sufficient_collaborative_rich_recent2y_category_index',
        method_doc='dic/recall_methods/category/METHOD.md',
        latest_artifact='outputs/recall/pool500_method_sources/recent_2y/category/category_recent2y_all_eligible_index_v1/source_index_manifest.json',
        latest_row_count=1558964,
        candidate_generating=False,
    ),
    RecallSourceSpec(
        name='popular',
        readiness=READY,
        role='pool500_main_route_budgeted_popular_fallback_source',
        eligible_user_policy='all_users_main_route_fallback_budgeted',
        method_doc='dic/recall_methods/popular/METHOD.md',
        latest_artifact='outputs/recall/pool500_method_sources/recent_2y/popular/formal/popular_recent2y_formal_v1/source_index_manifest.json',
        latest_row_count=762622,
        candidate_generating=True,
    ),
    RecallSourceSpec(
        name='swing_recall',
        readiness=READY,
        role='behavioral_item_expansion',
        eligible_user_policy='pre_user_first_min_user_items_2_src2_dst2_no_post_user_hard_filter',
        method_doc='dic/recall_methods/swing_recall/METHOD.md',
        latest_artifact='outputs/recall/pool500_method_sources/recent_2y/swing_recall/formal/run_20260606_datawhale_f1_main_route_v1/source_index_manifest.json',
        latest_row_count=457372,
    ),
    RecallSourceSpec(
        name='usercf_recall',
        readiness=DIAGNOSTIC_ONLY,
        role='heavy_user_neighbor_recall_diagnostic',
        eligible_user_policy='item_first_src2_dst3_user3_keep_hot_iuf_cosine_clean_train_diagnostic',
        method_doc='dic/recall_methods/usercf_recall/METHOD.md',
        latest_artifact='outputs/recall/pool500_method_sources/recent_2y/usercf_recall/usercf_itemfirst_src2_dst3_user3_keep_hot_full_diagnostic_v1/source_index_manifest.json',
        latest_row_count=651046,
    ),
    RecallSourceSpec(
        name='itemcf_weak',
        readiness='READY_GUARDED_SOURCE_ADAPTER_READY',
        role='broad_item_neighbor_recall_src3_dst3_user2_keep_hot_cosine_source',
        eligible_user_policy='user_after_item_filter_min_items_2',
        method_doc='dic/recall_methods/itemcf_weak/METHOD.md',
        latest_artifact='outputs/recall/pool500_method_sources/recent_2y/itemcf_weak/src3_dst3_user2_keep_hot_cosine_v1/source_index_manifest.json',
        latest_row_count=16454229,
    ),
    RecallSourceSpec(
        name='itemcf_strong',
        readiness=READY_CANDIDATE,
        role='high_confidence_item_neighbor_supplemental_source',
        eligible_user_policy='sequence_sufficient_or_collaborative_rich_for_relaxed_strong_itemcf',
        method_doc='dic/recall_methods/itemcf_strong/METHOD.md',
        latest_artifact='outputs/recall/pool500_method_sources_newdata/itemcf_strong_relaxed_supplemental_v1/itemcf_strong/formal_relaxed_from_recent2y/source_index_manifest.json',
        latest_row_count=514216,
        candidate_generating=True,
    ),
    RecallSourceSpec(
        name='semantic',
        readiness=READY_CANDIDATE,
        role='semantic_description_guarded_candidate_recall',
        eligible_user_policy='metadata_rich_or_behavior_sparse_recent2y_target_slice',
        method_doc='dic/recall_methods/semantic/METHOD.md',
        latest_artifact='outputs/recall/pool500_method_sources_newdata/semantic/semantic_recent2y_formal_target10k_v1/source_index_manifest.json',
        latest_row_count=800000,
        candidate_generating=True,
    ),
    RecallSourceSpec(
        name='semantic_title_category_expansion',
        readiness=DEFERRED,
        role='merged_into_semantic_live_not_independent_online_source',
        eligible_user_policy='retired_independent_source_covered_by_semantic_live_description_recall',
        method_doc='dic/recall_methods/semantic_title_category_expansion/METHOD.md',
        latest_artifact='outputs/recall/pool500_method_sources_newdata/semantic_title_category_expansion/semantic_title_category_recent2y_smoke_v1/source_index_manifest.json',
        latest_row_count=15526,
    ),
    RecallSourceSpec(
        name='co_visit_fallback_repair',
        readiness=DEFERRED,
        role='fallback_underfill_repair_guarded_task_source',
        eligible_user_policy='non_cold_start_train_sequence_users_requiring_repair',
        method_doc='dic/recall_methods/co_visit_fallback_repair/METHOD.md',
        latest_artifact='outputs/recall/pool500_method_sources_newdata/co_visit_fallback_repair/co_visit_recent2y_smoke_dataset_20260602/source_index_manifest.json',
        latest_row_count=398326,
    ),
    RecallSourceSpec(
        name='two_tower',
        readiness=DIAGNOSTIC_ONLY,
        role='embedding_ann_recall',
        eligible_user_policy='two_tower_train_eligible_or_above_with_hot_item_universe',
        method_doc='dic/recall_methods/two_tower/METHOD.md',
        latest_artifact='outputs/recall/pool500_method_sources/recent_2y/two_tower/sparse_aware_formal_epoch5_selected/source_index_manifest.json',
        latest_row_count=448282,
    ),
)

_RECALL_SOURCE_SPECS_BY_NAME = {spec.name: spec for spec in _RECALL_SOURCE_SPECS}


def list_recall_source_specs() -> tuple[RecallSourceSpec, ...]:
    return _RECALL_SOURCE_SPECS


def get_recall_source_spec(name: str) -> RecallSourceSpec:
    return _RECALL_SOURCE_SPECS_BY_NAME[name]


def list_candidate_generating_sources() -> tuple[RecallSourceSpec, ...]:
    return tuple(spec for spec in _RECALL_SOURCE_SPECS if spec.candidate_generating)
