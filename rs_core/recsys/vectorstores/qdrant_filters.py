from __future__ import annotations

from typing import Any, Iterable

from rs_core.recsys.vectorstores.qdrant_client import qdrant_models


def item_id_match_any_filter(item_ids: Iterable[str], *, extra_must: list[Any] | None = None) -> Any:
    models = qdrant_models()
    values = [str(item_id) for item_id in item_ids if str(item_id)]
    must = list(extra_must or [])
    if values:
        must.append(models.FieldCondition(key="item_id", match=models.MatchAny(any=values)))
    return models.Filter(must=must)


def schema_version_condition(schema_version: str) -> Any:
    models = qdrant_models()
    return models.FieldCondition(key="schema_version", match=models.MatchValue(value=str(schema_version)))


def source_name_condition(source_name: str) -> Any:
    models = qdrant_models()
    return models.FieldCondition(key="source_name", match=models.MatchValue(value=str(source_name)))


def corpus_scope_condition(corpus_scope: str) -> Any:
    models = qdrant_models()
    return models.FieldCondition(key="corpus_scope", match=models.MatchValue(value=str(corpus_scope)))


def index_build_id_condition(index_build_id: str) -> Any:
    models = qdrant_models()
    return models.FieldCondition(key="index_build_id", match=models.MatchValue(value=str(index_build_id)))


def no_holdout_condition() -> Any:
    models = qdrant_models()
    return models.FieldCondition(key="no_holdout", match=models.MatchValue(value=True))


def train_only_condition() -> Any:
    models = qdrant_models()
    return models.FieldCondition(key="train_only", match=models.MatchValue(value=True))


def candidate_generation_allowed_condition() -> Any:
    models = qdrant_models()
    return models.FieldCondition(key="candidate_generation_allowed", match=models.MatchValue(value=True))


def exclude_item_ids_filter(item_ids: Iterable[str], *, must: list[Any] | None = None, must_not: list[Any] | None = None) -> Any:
    models = qdrant_models()
    values = [str(item_id) for item_id in item_ids if str(item_id)]
    excluded = list(must_not or [])
    if values:
        excluded.append(models.FieldCondition(key="item_id", match=models.MatchAny(any=values)))
    return models.Filter(must=list(must or []), must_not=excluded)
