from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rs_core.recsys.semantic_description.retrieval import retrieve_fixture_results
from rs_core.recsys.semantic_description.scoring import DEFAULT_DOCUMENT_COUNT, STRICT_QUERY_FIXTURES
from rs_core.recsys.semantic_description.store import SQLiteSemanticDescriptionStore


@dataclass(frozen=True)
class SemanticDescriptionRetrieverConfig:
    semantic_inputs_path: Path
    inverted_index_path: Path
    document_count: int = DEFAULT_DOCUMENT_COUNT
    per_token_limit: int = 10_000
    candidate_limit: int = 80_000
    top_k: int = 10


class SemanticDescriptionRecallEngine:
    def __init__(self, config: SemanticDescriptionRetrieverConfig, *, store: Any | None = None) -> None:
        self.config = config
        self.store = store

    @classmethod
    def from_paths(
        cls,
        *,
        semantic_inputs_path: str | Path,
        inverted_index_path: str | Path,
        document_count: int = DEFAULT_DOCUMENT_COUNT,
        per_token_limit: int = 10_000,
        candidate_limit: int = 80_000,
        top_k: int = 10,
        sqlite_index_path: str | Path | None = None,
    ) -> "SemanticDescriptionRecallEngine":
        store = SQLiteSemanticDescriptionStore(sqlite_index_path) if sqlite_index_path else None
        return cls(
            SemanticDescriptionRetrieverConfig(
                semantic_inputs_path=Path(semantic_inputs_path),
                inverted_index_path=Path(inverted_index_path),
                document_count=document_count,
                per_token_limit=per_token_limit,
                candidate_limit=candidate_limit,
                top_k=top_k,
            ),
            store=store,
        )

    def diagnose(self, *, output_dir: Path, fixtures: list[dict[str, Any]] = STRICT_QUERY_FIXTURES) -> dict[str, Any]:
        return diagnose(
            semantic_inputs_path=self.config.semantic_inputs_path,
            inverted_index_path=self.config.inverted_index_path,
            output_dir=output_dir,
            fixtures=fixtures,
            per_token_limit=self.config.per_token_limit,
            candidate_limit=self.config.candidate_limit,
            top_k=self.config.top_k,
            document_count=self.config.document_count,
            store=self.store,
        )


def diagnose(
    *,
    semantic_inputs_path: Path,
    inverted_index_path: Path,
    output_dir: Path,
    fixtures: list[dict[str, Any]] = STRICT_QUERY_FIXTURES,
    per_token_limit: int = 10_000,
    candidate_limit: int = 80_000,
    top_k: int = 10,
    document_count: int = DEFAULT_DOCUMENT_COUNT,
    store: Any | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    fixture_results, _doc_freq = retrieve_fixture_results(
        fixtures=fixtures,
        semantic_inputs_path=semantic_inputs_path,
        inverted_index_path=inverted_index_path,
        per_token_limit=per_token_limit,
        candidate_limit=candidate_limit,
        document_count=document_count,
        store=store,
    )

    query_reports = []
    for fixture_result in fixture_results:
        fixture = fixture_result.fixture
        top_rows = []
        for rank, row in enumerate(fixture_result.rows[:top_k], start=1):
            top_rows.append(
                {
                    "rank": rank,
                    "item_id": row.item_id,
                    "score": row.score,
                    "title": row.record.get("title_clean"),
                    "main_category": row.record.get("main_category"),
                    "categories_flat": row.record.get("categories_flat"),
                    **row.details,
                }
            )

        strict_hits = [row for row in top_rows if row["strict_intent_pass"]]
        required_hits = [row for row in top_rows if row["required_pass"]]
        bad_hits = [row for row in top_rows if row["negative_hits"]]
        best_strict_rank = strict_hits[0]["rank"] if strict_hits else None
        query_reports.append(
            {
                "query_id": str(fixture["id"]),
                "description": fixture["description"],
                "core_terms": fixture.get("core_terms") or [],
                "must_terms": fixture.get("must_terms") or [],
                "must_any_groups": fixture.get("must_any_groups") or [],
                "intent_phrases": fixture.get("intent_phrases") or [],
                "category_any": fixture.get("category_any") or [],
                "negative_phrases": fixture.get("negative_phrases") or [],
                "query_tokens": fixture_result.query_tokens,
                "candidate_pool_size": len(fixture_result.candidate_ids),
                "scored_count": len(fixture_result.rows),
                "strict_precision_at_5": round(sum(1 for row in top_rows[:5] if row["strict_intent_pass"]) / 5, 3) if top_rows else 0.0,
                "strict_precision_at_10": round(len(strict_hits) / top_k, 3) if top_rows else 0.0,
                "required_precision_at_10": round(len(required_hits) / top_k, 3) if top_rows else 0.0,
                "bad_intent_rate_at_10": round(len(bad_hits) / top_k, 3) if top_rows else 0.0,
                "best_strict_rank": best_strict_rank,
                "top10": top_rows,
            }
        )

    summary = {
        "schema_version": "semantic_description_recall_strict_v1",
        "created_at": datetime.now(UTC).isoformat(),
        "eval_scope": "train_metadata_description_diagnostic_only",
        "label_inputs_role": "not_used",
        "oracle_label_injection": False,
        "query_count": len(query_reports),
        "avg_strict_precision_at_5": round(sum(row["strict_precision_at_5"] for row in query_reports) / len(query_reports), 3),
        "avg_strict_precision_at_10": round(sum(row["strict_precision_at_10"] for row in query_reports) / len(query_reports), 3),
        "avg_required_precision_at_10": round(sum(row["required_precision_at_10"] for row in query_reports) / len(query_reports), 3),
        "avg_bad_intent_rate_at_10": round(sum(row["bad_intent_rate_at_10"] for row in query_reports) / len(query_reports), 3),
        "queries_with_strict_hit_top5": sum(
            1 for row in query_reports if row["best_strict_rank"] is not None and int(row["best_strict_rank"]) <= 5
        ),
        "queries_strict_p10_ge_0_5": sum(1 for row in query_reports if row["strict_precision_at_10"] >= 0.5),
    }

    payload = {"summary": summary, "queries": query_reports}
    report_path = output_dir / "semantic_description_recall_strict_report.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# Semantic description recall strict diagnostic", "", json.dumps(summary, ensure_ascii=False)]
    for query in query_reports:
        lines.extend(
            [
                "",
                f"## {query['query_id']}: {query['description']}",
                (
                    f"candidate_pool={query['candidate_pool_size']} scored={query['scored_count']} "
                    f"strict_p@5={query['strict_precision_at_5']} strict_p@10={query['strict_precision_at_10']} "
                    f"required_p@10={query['required_precision_at_10']} bad@10={query['bad_intent_rate_at_10']} "
                    f"best_strict_rank={query['best_strict_rank']}"
                ),
            ]
        )
        for row in query["top10"][:5]:
            lines.append(
                f"- #{row['rank']} score={row['score']} `{row['item_id']}` {row['title']} | {row['main_category']} | "
                f"strict={row['strict_intent_pass']} required={row['required_pass']} "
                f"core={row['core_hits']} category={row['category_hits']} negative={row['negative_hits']}"
            )
    readme_path = output_dir / "README.md"
    readme_path.write_text("\n".join(lines), encoding="utf-8")

    return {"summary": summary, "report": str(report_path), "readme": str(readme_path)}


__all__ = ["SemanticDescriptionRecallEngine", "SemanticDescriptionRetrieverConfig", "diagnose"]
