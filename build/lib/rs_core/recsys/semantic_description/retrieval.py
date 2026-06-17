from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from rs_core.recsys.semantic_description.scoring import (
    DEFAULT_DOCUMENT_COUNT,
    PreparedFixture,
    PreparedRecord,
    fixture_query_terms,
    prepare_fixture,
    prepare_record,
    query_token_weights,
    score_prepared_record_with_token_weights,
    tokens,
)


@dataclass(frozen=True)
class RankedSemanticDescriptionRow:
    score: float
    item_id: str
    record: dict[str, Any]
    details: dict[str, Any]


@dataclass(frozen=True)
class SemanticDescriptionQueryResult:
    fixture: dict[str, Any]
    query_tokens: list[str]
    candidate_ids: list[str]
    rows: list[RankedSemanticDescriptionRow]


def load_query_buckets(
    inverted_index_path: Path,
    query_tokens: set[str],
    *,
    per_token_limit: int,
) -> tuple[dict[str, list[str]], dict[str, int]]:
    buckets: dict[str, list[str]] = {}
    doc_freq: dict[str, int] = {}
    with inverted_index_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            token = str(row.get("token") or "").lower()
            if token not in query_tokens:
                continue
            item_ids = row.get("parent_asins") or row.get("item_ids") or []
            if not isinstance(item_ids, list):
                continue
            doc_freq[token] = len(item_ids)
            buckets[token] = [str(item_id) for item_id in item_ids[:per_token_limit]]
    return buckets, doc_freq


def ordered_unique(values: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= limit:
            break
    return result


def collect_ordered_unique_candidates(token_order: Iterable[str], buckets: dict[str, list[str]], limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for token in token_order:
        for item_id in buckets.get(token, []):
            if item_id in seen:
                continue
            seen.add(item_id)
            result.append(item_id)
            if len(result) >= limit:
                return result
    return result


def load_records(semantic_inputs_path: Path, item_ids: set[str]) -> dict[str, dict[str, Any]]:
    remaining = set(item_ids)
    records: dict[str, dict[str, Any]] = {}
    if not remaining:
        return records
    with semantic_inputs_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            item_id = str(row.get("parent_asin") or row.get("item_id") or "")
            if item_id not in remaining:
                continue
            records[item_id] = row
            remaining.remove(item_id)
            if not remaining:
                break
    return records


def prioritized_fixture_terms(fixture: dict[str, Any], query_terms: set[str]) -> list[str]:
    prioritized_terms = [*tokens(" ".join(str(item) for item in fixture.get("core_terms") or []))]
    prioritized_terms.extend(sorted(query_terms - set(prioritized_terms)))
    return prioritized_terms


def candidate_ids_for_fixture(
    fixture: dict[str, Any],
    query_terms: set[str],
    buckets: dict[str, list[str]],
    *,
    candidate_limit: int,
) -> list[str]:
    return collect_ordered_unique_candidates(
        prioritized_fixture_terms(fixture, query_terms),
        buckets,
        candidate_limit,
    )


def rank_fixture_candidates(
    fixture: dict[str, Any] | PreparedFixture,
    candidate_ids: list[str],
    records: dict[str, dict[str, Any]],
    doc_freq: dict[str, int],
    *,
    document_count: int = DEFAULT_DOCUMENT_COUNT,
    prepared_records: dict[str, PreparedRecord] | None = None,
) -> list[RankedSemanticDescriptionRow]:
    prepared_fixture = fixture if isinstance(fixture, PreparedFixture) else prepare_fixture(fixture)
    prepared_records = prepared_records if prepared_records is not None else {}
    token_weights = query_token_weights(prepared_fixture, doc_freq, document_count=document_count)
    rows: list[RankedSemanticDescriptionRow] = []
    for item_id in candidate_ids:
        record = records.get(item_id)
        if not record:
            continue
        prepared_record = prepared_records.get(item_id)
        if prepared_record is None:
            prepared_record = prepare_record(record)
            prepared_records[item_id] = prepared_record
        score, details = score_prepared_record_with_token_weights(prepared_fixture, prepared_record, token_weights)
        if score <= 0:
            continue
        rows.append(RankedSemanticDescriptionRow(score=score, item_id=item_id, record=record, details=details))
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows


def retrieve_fixture_results(
    *,
    fixtures: list[dict[str, Any]],
    semantic_inputs_path: Path,
    inverted_index_path: Path,
    per_token_limit: int = 10_000,
    candidate_limit: int = 80_000,
    document_count: int = DEFAULT_DOCUMENT_COUNT,
    store: Any | None = None,
) -> tuple[list[SemanticDescriptionQueryResult], dict[str, int]]:
    prepared_fixtures = {str(fixture["id"]): prepare_fixture(fixture) for fixture in fixtures}
    terms_by_id = {fixture_id: prepared.query_terms for fixture_id, prepared in prepared_fixtures.items()}
    all_terms = set().union(*terms_by_id.values()) if terms_by_id else set()
    if store is None:
        buckets, doc_freq = load_query_buckets(inverted_index_path, all_terms, per_token_limit=per_token_limit)
    else:
        buckets, doc_freq = store.load_query_buckets(all_terms, per_token_limit=per_token_limit)

    candidate_ids_by_id: dict[str, list[str]] = {}
    all_candidates: set[str] = set()
    for fixture in fixtures:
        fixture_id = str(fixture["id"])
        candidates = candidate_ids_for_fixture(fixture, terms_by_id[fixture_id], buckets, candidate_limit=candidate_limit)
        candidate_ids_by_id[fixture_id] = candidates
        all_candidates.update(candidates)

    prepared_records = store.load_prepared_records(all_candidates) if store is not None and hasattr(store, "load_prepared_records") else {}
    if prepared_records:
        records = {item_id: prepared.raw for item_id, prepared in prepared_records.items()}
    else:
        records = load_records(semantic_inputs_path, all_candidates) if store is None else store.load_records(all_candidates)
        prepared_records = {item_id: prepare_record(record) for item_id, record in records.items()}
    results: list[SemanticDescriptionQueryResult] = []
    for fixture in fixtures:
        fixture_id = str(fixture["id"])
        rows = rank_fixture_candidates(
            prepared_fixtures[fixture_id],
            candidate_ids_by_id[fixture_id],
            records,
            doc_freq,
            document_count=document_count,
            prepared_records=prepared_records,
        )
        results.append(
            SemanticDescriptionQueryResult(
                fixture=fixture,
                query_tokens=sorted(terms_by_id[fixture_id]),
                candidate_ids=candidate_ids_by_id[fixture_id],
                rows=rows,
            )
        )
    return results, doc_freq


__all__ = [
    "RankedSemanticDescriptionRow",
    "SemanticDescriptionQueryResult",
    "candidate_ids_for_fixture",
    "collect_ordered_unique_candidates",
    "fixture_query_terms",
    "load_query_buckets",
    "load_records",
    "ordered_unique",
    "prioritized_fixture_terms",
    "rank_fixture_candidates",
    "retrieve_fixture_results",
]
