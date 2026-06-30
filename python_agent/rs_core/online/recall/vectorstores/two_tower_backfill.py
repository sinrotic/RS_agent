from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from rs_core.online.recall.vector_index import normalize_vector


TRAINED_VECTOR_ORIGIN = "trained_two_tower"
CATEGORY_CENTROID_ORIGIN = "category_centroid"
GLOBAL_CENTROID_ORIGIN = "global_centroid"


@dataclass(frozen=True)
class BackfillResult:
    rows: list[dict[str, Any]]
    report: dict[str, Any]


def backfill_two_tower_item_vectors(
    *,
    existing_rows: Iterable[dict[str, Any]],
    catalog_rows: Iterable[dict[str, Any]],
) -> BackfillResult:
    trained_by_item: dict[str, dict[str, Any]] = {}
    trained_order: list[str] = []
    vectors_by_category: dict[str, list[list[float]]] = {}
    all_vectors: list[list[float]] = []
    skipped_existing_rows = 0

    for row in existing_rows:
        item_id = item_id_for_row(row)
        vector = vector_for_row(row)
        if not item_id or not vector:
            skipped_existing_rows += 1
            continue
        normalized = normalize_vector(vector)
        if not normalized:
            skipped_existing_rows += 1
            continue
        payload = dict(row)
        payload["parent_asin"] = item_id
        payload["item_id"] = item_id
        payload["embedding"] = normalized
        payload.setdefault("vector_origin", TRAINED_VECTOR_ORIGIN)
        payload.setdefault("vector_backfill_method", "none")
        if item_id not in trained_by_item:
            trained_order.append(item_id)
        trained_by_item[item_id] = payload
        all_vectors.append(normalized)
        category = category_key_for_row(row)
        if category:
            vectors_by_category.setdefault(category, []).append(normalized)

    if not all_vectors:
        raise ValueError("cannot backfill two-tower vectors without at least one trained item vector")

    category_centroids = {category: centroid(vectors) for category, vectors in vectors_by_category.items()}
    global_centroid = centroid(all_vectors)

    catalog_by_item: dict[str, dict[str, Any]] = {}
    catalog_order: list[str] = []
    skipped_catalog_rows = 0
    for row in catalog_rows:
        item_id = item_id_for_row(row)
        if not item_id:
            skipped_catalog_rows += 1
            continue
        if item_id not in catalog_by_item:
            catalog_order.append(item_id)
        catalog_by_item[item_id] = dict(row)

    output: list[dict[str, Any]] = [trained_by_item[item_id] for item_id in trained_order]
    backfilled_by_origin = {CATEGORY_CENTROID_ORIGIN: 0, GLOBAL_CENTROID_ORIGIN: 0}

    for item_id in catalog_order:
        if item_id in trained_by_item:
            continue
        catalog_row = catalog_by_item[item_id]
        category = category_key_for_row(catalog_row)
        if category and category in category_centroids:
            vector = category_centroids[category]
            origin = CATEGORY_CENTROID_ORIGIN
            source_count = len(vectors_by_category[category])
        else:
            vector = global_centroid
            origin = GLOBAL_CENTROID_ORIGIN
            source_count = len(all_vectors)
        payload = {key: value for key, value in catalog_row.items() if key != "embedding"}
        payload.update(
            {
                "parent_asin": item_id,
                "item_id": item_id,
                "embedding": vector,
                "vector_origin": origin,
                "vector_backfill_method": origin,
                "vector_backfill_category_key": category,
                "vector_backfill_source_count": source_count,
            }
        )
        output.append(payload)
        backfilled_by_origin[origin] += 1

    report = {
        "trained_item_count": len(trained_by_item),
        "catalog_item_count": len(catalog_by_item),
        "output_item_count": len(output),
        "backfilled_item_count": sum(backfilled_by_origin.values()),
        "backfilled_by_origin": backfilled_by_origin,
        "category_centroid_count": len(category_centroids),
        "vector_size": len(global_centroid),
        "skipped_existing_rows": skipped_existing_rows,
        "skipped_catalog_rows": skipped_catalog_rows,
    }
    return BackfillResult(rows=output, report=report)


def item_id_for_row(row: dict[str, Any]) -> str:
    return str(row.get("parent_asin") or row.get("item_id") or row.get("asin") or "").strip()


def vector_for_row(row: dict[str, Any]) -> list[float]:
    value = row.get("embedding") or row.get("vector")
    if not isinstance(value, list):
        return []
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return []


def category_key_for_row(row: dict[str, Any]) -> str:
    for key in ("main_category", "category", "category_path"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    categories = row.get("categories_flat") or row.get("categories")
    if isinstance(categories, list):
        values = [str(item).strip() for item in categories if str(item).strip()]
        if values:
            return " > ".join(values)
    return ""


def centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    sums = [0.0] * dim
    count = 0
    for vector in vectors:
        if len(vector) != dim:
            continue
        for index, value in enumerate(vector):
            sums[index] += float(value)
        count += 1
    if count == 0:
        return []
    return normalize_vector([value / count for value in sums])
