from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def output_exists(path_str: str) -> bool:
    if not path_str:
        return False
    path = Path(path_str)
    return path.exists() and path.stat().st_size > 0


def run_recall_output_checks(
    clean_stats: dict[str, Any],
    view_stats: dict[str, Any],
    require_strong_itemcf: bool,
) -> tuple[bool, list[str]]:
    lines: list[str] = []
    failures: list[str] = []

    train_readiness = clean_stats.get("train_readiness", {})
    view_pop = view_stats.get("popular_recall", {})
    view_itemcf = view_stats.get("itemcf_recall", {})
    weak_itemcf = view_itemcf.get("weak", {})
    strong_itemcf = view_itemcf.get("strong", {})
    view_category = view_stats.get("category_recall", {})

    checks = [
        (
            "train_positive_rows",
            train_readiness.get("positive_train_interaction_count", 0) > 0,
            f"positive_train_interaction_count={train_readiness.get('positive_train_interaction_count', 0)}",
            True,
        ),
        (
            "train_ge2_positive_users",
            train_readiness.get("users_with_ge2_positive_train_items", 0) > 0,
            f"users_with_ge2_positive_train_items={train_readiness.get('users_with_ge2_positive_train_items', 0)}",
            True,
        ),
        (
            "popular_recall",
            view_pop.get("rows_written", 0) > 0 and output_exists(view_pop.get("output_path", "")),
            f"rows_written={view_pop.get('rows_written', 0)}",
            True,
        ),
        (
            "weak_itemcf",
            weak_itemcf.get("rows_written", 0) > 0
            and weak_itemcf.get("unique_pair_count", 0) > 0
            and output_exists(weak_itemcf.get("output_path", "")),
            f"rows_written={weak_itemcf.get('rows_written', 0)}, unique_pair_count={weak_itemcf.get('unique_pair_count', 0)}",
            True,
        ),
        (
            "category_recall",
            view_category.get("category_rows_written", 0) > 0
            and output_exists(view_category.get("category_items_path", "")),
            f"category_rows_written={view_category.get('category_rows_written', 0)}",
            True,
        ),
        (
            "strong_itemcf",
            strong_itemcf.get("rows_written", 0) > 0
            and strong_itemcf.get("unique_pair_count", 0) > 0
            and output_exists(strong_itemcf.get("output_path", "")),
            f"rows_written={strong_itemcf.get('rows_written', 0)}, unique_pair_count={strong_itemcf.get('unique_pair_count', 0)}",
            require_strong_itemcf,
        ),
    ]

    for name, ok, detail, required in checks:
        status = "PASS" if ok else ("FAIL" if required else "WARN")
        lines.append(f"[{status}] {name}: {detail}")
        if required and not ok:
            failures.append(name)

    return not failures, lines
