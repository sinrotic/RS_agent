from __future__ import annotations

from typing import Any, Iterable


def eq_expr(field_name: str, value: Any) -> str:
    return f"{field_name} == {_literal(value)}"


def ne_expr(field_name: str, value: Any) -> str:
    return f"{field_name} != {_literal(value)}"


def in_expr(field_name: str, values: Iterable[Any]) -> str:
    literals = ", ".join(_literal(value) for value in values)
    return f"{field_name} in [{literals}]"


def and_expr(*parts: str | None) -> str:
    clean = [f"({part})" for part in parts if part]
    return " and ".join(clean)


def not_in_expr(field_name: str, values: Iterable[Any]) -> str:
    literals = ", ".join(_literal(value) for value in values)
    return f"{field_name} not in [{literals}]"


def item_id_match_any_expr(item_ids: Iterable[str], *, extra_must: list[str] | None = None) -> str:
    parts = list(extra_must or [])
    values = [str(item_id) for item_id in item_ids if str(item_id)]
    if values:
        parts.append(in_expr("item_id", values))
    return and_expr(*parts)


def schema_version_expr(schema_version: str) -> str:
    return eq_expr("schema_version", str(schema_version))


def source_name_expr(source_name: str) -> str:
    return eq_expr("source_name", str(source_name))


def corpus_scope_expr(corpus_scope: str) -> str:
    return eq_expr("corpus_scope", str(corpus_scope))


def index_build_id_expr(index_build_id: str) -> str:
    return eq_expr("index_build_id", str(index_build_id))


def no_holdout_expr() -> str:
    return eq_expr("no_holdout", True)


def train_only_expr() -> str:
    return eq_expr("train_only", True)


def candidate_generation_allowed_expr() -> str:
    return eq_expr("candidate_generation_allowed", True)


def exclude_item_ids_expr(item_ids: Iterable[str], *, must: list[str] | None = None) -> str:
    parts = list(must or [])
    values = [str(item_id) for item_id in item_ids if str(item_id)]
    if values:
        parts.append(not_in_expr("item_id", values))
    return and_expr(*parts)


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return "\"" + str(value).replace("\\", "\\\\").replace("\"", "\\\"") + "\""
