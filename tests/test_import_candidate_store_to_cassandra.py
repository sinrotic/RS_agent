from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.serving.import_candidate_store_to_cassandra import import_candidate_store_to_cassandra


class FakeSession:
    def __init__(self) -> None:
        self.prepared: list[str] = []
        self.calls: list[tuple[Any, Any]] = []

    def prepare(self, statement: str) -> str:
        self.prepared.append(statement)
        return statement

    def execute(self, statement: Any, parameters: Any | None = None) -> list[Any]:
        self.calls.append((statement, parameters))
        return []


def test_cassandra_importer_dry_run_classifies_usercf_rows(tmp_path: Path) -> None:
    path = tmp_path / "usercf.jsonl"
    path.write_text(json.dumps({"user_id": "u1", "item_id": "i1", "source": "usercf", "score": 0.8}) + "\n", encoding="utf-8")

    result = import_candidate_store_to_cassandra(inputs=[path], store_version="v1")

    report = result["reports"][0]
    assert result["dry_run"] is True
    assert report["schema"] == "usercf_candidates"
    assert report["store_version"] == "v1"
    assert report["importable_rows"] == 1


def test_cassandra_importer_auto_classifies_pool500_rows(tmp_path: Path) -> None:
    path = tmp_path / "pool500.jsonl"
    path.write_text(json.dumps({"user_id": "u1", "item_id": "i1", "sources": ["itemcf"], "source_scores": {"itemcf": 0.8}}) + "\n", encoding="utf-8")

    result = import_candidate_store_to_cassandra(inputs=[path], store_version="v1")

    report = result["reports"][0]
    assert report["schema"] == "pool_candidates"
    assert report["sources"] == {"itemcf": 1}


def test_cassandra_importer_requires_store_version_for_write(tmp_path: Path) -> None:
    path = tmp_path / "usercf.jsonl"
    path.write_text(json.dumps({"user_id": "u1", "item_id": "i1"}) + "\n", encoding="utf-8")
    session = FakeSession()

    result = import_candidate_store_to_cassandra(inputs=[path], write=True, session=session)

    assert result["write_status"] == "rejected_missing_store_version"
    assert session.calls == []


def test_cassandra_importer_writes_usercf_with_bound_values(tmp_path: Path) -> None:
    path = tmp_path / "usercf.jsonl"
    path.write_text(json.dumps({"user_id": "u1", "parent_asin": "i1", "source": "usercf", "score": 1.2, "rank": 3}) + "\n", encoding="utf-8")
    session = FakeSession()

    result = import_candidate_store_to_cassandra(inputs=[path], write=True, session=session, store_version="v1", batch_size=1, artifact_id="a1")

    assert result["reports"][0]["write_status"] == "written"
    assert any("INSERT INTO user_candidates_by_user" in sql for sql in session.prepared)
    candidate_call = next(call for call in session.calls if isinstance(call[1], tuple) and len(call[1]) == 10 and call[1][2] == "u1")
    assert candidate_call[1][0] == "usercf_recall"
    assert candidate_call[1][1] == "v1"
    assert candidate_call[1][4] == "i1"
    assert candidate_call[1][7] == "a1"


def test_cassandra_importer_writes_pool_candidates_with_bound_values(tmp_path: Path) -> None:
    path = tmp_path / "pool500.jsonl"
    path.write_text(json.dumps({"user_id": "u1", "item_id": "i1", "sources": ["itemcf"], "source_scores": {"itemcf": 0.8}, "rank": 2}) + "\n", encoding="utf-8")
    session = FakeSession()

    result = import_candidate_store_to_cassandra(inputs=[path], target_schema="pool_candidates", write=True, session=session, store_version="v1", artifact_id="pool_a1")

    assert result["reports"][0]["write_status"] == "written"
    assert any("INSERT INTO pool_candidates_by_user" in sql for sql in session.prepared)
    candidate_call = next(call for call in session.calls if isinstance(call[1], tuple) and len(call[1]) == 10 and call[1][1] == "u1")
    assert candidate_call[1][0] == "v1"
    assert candidate_call[1][3] == "i1"
    assert candidate_call[1][4] == "itemcf"
    assert candidate_call[1][5] == 0.8
    assert candidate_call[1][7] == "pool_a1"


def test_cassandra_importer_dedupes_pool_candidates_by_user_and_item(tmp_path: Path) -> None:
    path = tmp_path / "pool500.jsonl"
    path.write_text(
        "".join(
            [
                json.dumps({"user_id": "u1", "item_id": "i1", "sources": ["itemcf"], "source_scores": {"itemcf": 0.7}, "rank": 1}) + "\n",
                json.dumps({"user_id": "u1", "item_id": "i1", "sources": ["popular"], "source_scores": {"popular": 0.9}, "rank": 2}) + "\n",
            ]
        ),
        encoding="utf-8",
    )
    session = FakeSession()

    result = import_candidate_store_to_cassandra(inputs=[path], target_schema="pool_candidates", write=True, session=session, store_version="v1")

    assert result["reports"][0]["duplicate_rows"] == 1
    assert result["reports"][0]["written_rows"] == 1
    candidate_call = next(call for call in session.calls if isinstance(call[1], tuple) and len(call[1]) == 10 and call[1][1] == "u1")
    assert candidate_call[1][3] == "i1"
    assert candidate_call[1][4] == "popular"
    assert candidate_call[1][5] == 0.9


def test_cassandra_importer_dry_run_classifies_popular_category_and_profiles(tmp_path: Path) -> None:
    popular = tmp_path / "popular.jsonl"
    category = tmp_path / "category.jsonl"
    profile = tmp_path / "profile.jsonl"
    popular.write_text(json.dumps({"item_id": "p1", "source": "popular", "score": 1.0}) + "\n", encoding="utf-8")
    category.write_text(json.dumps({"item_id": "c1", "source": "category", "bucket": "books", "score": 0.5}) + "\n", encoding="utf-8")
    profile.write_text(json.dumps({"user_id": "u1", "bucket": "books", "score": 2.0}) + "\n", encoding="utf-8")

    result = import_candidate_store_to_cassandra(inputs=[popular, category, profile], store_version="v1")

    assert [report["schema"] for report in result["reports"]] == ["popular_candidates", "category_candidates", "user_category_profiles"]
    assert [report["importable_rows"] for report in result["reports"]] == [1, 1, 1]


def test_cassandra_importer_writes_popular_category_and_profiles(tmp_path: Path) -> None:
    popular = tmp_path / "popular.jsonl"
    category = tmp_path / "category.jsonl"
    profile = tmp_path / "profile.jsonl"
    popular.write_text(json.dumps({"item_id": "p1", "source": "popular_30d", "scope": "global", "bucket": "", "score": 1.0}) + "\n", encoding="utf-8")
    category.write_text(json.dumps({"item_id": "c1", "source": "category", "bucket": "books", "score": 0.5}) + "\n", encoding="utf-8")
    profile.write_text(json.dumps({"user_id": "u1", "bucket": "books", "score": 2.0}) + "\n", encoding="utf-8")
    session = FakeSession()

    result = import_candidate_store_to_cassandra(inputs=[popular, category, profile], write=True, session=session, store_version="v1", artifact_id="a1")

    assert [report["write_status"] for report in result["reports"]] == ["written", "written", "written"]
    assert any("INSERT INTO popular_candidates_by_scope" in sql for sql in session.prepared)
    assert any("INSERT INTO category_candidates_by_bucket" in sql for sql in session.prepared)
    assert any("INSERT INTO user_category_buckets_by_user" in sql for sql in session.prepared)
    popular_call = next(call for call in session.calls if isinstance(call[1], tuple) and len(call[1]) == 11 and call[1][5] == "p1")
    category_call = next(call for call in session.calls if isinstance(call[1], tuple) and len(call[1]) == 10 and call[1][4] == "c1")
    profile_call = next(call for call in session.calls if isinstance(call[1], tuple) and len(call[1]) == 7 and call[1][1] == "u1")
    assert popular_call[1][:6] == ("popular", "v1", "global", "", 1, "p1")
    assert '"raw_source": "popular_30d"' in popular_call[1][9]
    assert category_call[1][:5] == ("category", "v1", "books", 1, "c1")
    assert profile_call[1][:5] == ("v1", "u1", 1, "books", 2.0)


def test_cassandra_importer_writes_item_neighbors_and_dedupes(tmp_path: Path) -> None:
    path = tmp_path / "neighbors.jsonl"
    path.write_text(
        "\n".join([
            json.dumps({"src_item": "s1", "dst_item": "d1", "source": "itemcf", "score": 0.1}),
            json.dumps({"src_item": "s1", "dst_item": "d1", "source": "itemcf", "score": 0.9}),
        ])
        + "\n",
        encoding="utf-8",
    )
    session = FakeSession()

    result = import_candidate_store_to_cassandra(inputs=[path], write=True, session=session, store_version="v1")

    assert result["reports"][0]["duplicate_rows"] == 1
    assert result["reports"][0]["written_rows"] == 1
    assert any("INSERT INTO item_neighbors_by_seed" in sql for sql in session.prepared)
    candidate_call = next(call for call in session.calls if isinstance(call[1], tuple) and len(call[1]) == 10 and call[1][2] == "s1")
    assert candidate_call[1][4] == "d1"
    assert candidate_call[1][5] == 0.9


def test_cassandra_importer_rejects_partial_artifact_in_write_mode(tmp_path: Path) -> None:
    path = tmp_path / "mixed.jsonl"
    path.write_text(json.dumps({"user_id": "u1", "item_id": "i1"}) + "\n" + json.dumps({"src_item": "s1", "dst_item": "d1"}) + "\n", encoding="utf-8")
    session = FakeSession()

    result = import_candidate_store_to_cassandra(inputs=[path], write=True, session=session, store_version="v1")

    assert result["reports"][0]["write_status"] == "rejected_partial_artifact"
    assert session.calls == []


def test_cassandra_importer_rejects_truncated_write(tmp_path: Path) -> None:
    path = tmp_path / "pool500.jsonl"
    path.write_text("".join(json.dumps({"user_id": "u1", "item_id": f"i{idx}", "sources": ["itemcf"], "source_scores": {"itemcf": 0.8}}) + "\n" for idx in range(2)), encoding="utf-8")
    session = FakeSession()

    result = import_candidate_store_to_cassandra(inputs=[path], limit_rows=1, write=True, session=session, store_version="v1")

    assert result["reports"][0]["truncated"] is True
    assert result["reports"][0]["write_status"] == "rejected_partial_artifact"
    assert session.calls == []


def test_cassandra_apply_schema_executes_cql_statements(tmp_path: Path) -> None:
    schema = tmp_path / "schema.cql"
    schema.write_text("CREATE KEYSPACE IF NOT EXISTS x;\n\nCREATE TABLE IF NOT EXISTS x.t (id text PRIMARY KEY);\n", encoding="utf-8")
    session = FakeSession()

    result = import_candidate_store_to_cassandra(inputs=[], apply_schema=True, schema_path=schema, session=session)

    assert result["apply_schema"] is True
    assert result["statement_count"] == 2
    assert len(session.calls) == 2
