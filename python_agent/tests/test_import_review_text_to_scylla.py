from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rs_core.data.review_text_store import (
    DEFAULT_SCHEMA_PATH,
    import_review_text_to_scylla,
    review_text_key,
)


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


class FlakySession(FakeSession):
    def __init__(self) -> None:
        super().__init__()
        self.failed_once = False

    def execute(self, statement: Any, parameters: Any | None = None) -> list[Any]:
        if "INSERT INTO review_text_by_item" in str(statement) and not self.failed_once:
            self.failed_once = True
            raise RuntimeError("WriteTimeout: coordinator timed out")
        return super().execute(statement, parameters)


def test_review_text_key_matches_mysql_importer_contract() -> None:
    row = {
        "category": "Electronics",
        "user_id": "u1",
        "parent_asin": "p1",
        "asin": "a1",
        "timestamp": 1700000000000,
    }

    assert (
        review_text_key(row, source_line=42)
        == "fe339bed3a01a8e247b0e6bf764e6d526b2a20496c4c94b29a6d6880dcea16f9"
    )


def test_review_text_importer_dry_run_reports_importable_text_rows(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "category": "Electronics",
                        "user_id": "u1",
                        "parent_asin": "p1",
                        "asin": "a1",
                        "rating": 5.0,
                        "title": "Good",
                        "text": "Long useful review text",
                        "timestamp": 1700000000000,
                        "verified_purchase": True,
                        "helpful_vote": 3,
                    }
                ),
                json.dumps({"category": "Electronics", "user_id": "u2", "parent_asin": "p2", "text": ""}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = import_review_text_to_scylla(inputs=[path], limit_rows=100, write=False)

    assert result["dry_run"] is True
    assert result["reports"][0]["scanned_rows"] == 2
    assert result["reports"][0]["importable_rows"] == 1
    assert result["reports"][0]["skipped_without_text"] == 1


def test_review_text_importer_filters_by_timestamp_range(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"category": "Electronics", "user_id": "u1", "parent_asin": "p1", "title": "old", "timestamp": 10}),
                json.dumps({"category": "Electronics", "user_id": "u2", "parent_asin": "p2", "title": "keep", "timestamp": 20}),
                json.dumps({"category": "Electronics", "user_id": "u3", "parent_asin": "p3", "title": "new", "timestamp": 30}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = import_review_text_to_scylla(
        inputs=[path],
        limit_rows=100,
        write=False,
        min_timestamp_ms=20,
        max_timestamp_ms=20,
    )

    assert result["reports"][0]["scanned_rows"] == 3
    assert result["reports"][0]["importable_rows"] == 1
    assert result["reports"][0]["skipped_outside_time_range"] == 2


def test_review_text_importer_filters_by_source_line_file(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    source_lines = tmp_path / "source_lines.txt"
    path.write_text(
        "\n".join(
            [
                json.dumps({"category": "Electronics", "user_id": "u1", "parent_asin": "p1", "title": "skip"}),
                json.dumps({"category": "Electronics", "user_id": "u2", "parent_asin": "p2", "title": "keep"}),
                json.dumps({"category": "Electronics", "user_id": "u3", "parent_asin": "p3", "title": "skip"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    source_lines.write_text("2\n", encoding="utf-8")

    result = import_review_text_to_scylla(
        inputs=[path],
        limit_rows=100,
        write=False,
        source_line_filters={path: source_lines},
    )

    assert result["reports"][0]["scanned_rows"] == 3
    assert result["reports"][0]["importable_rows"] == 1
    assert result["reports"][0]["skipped_outside_source_lines"] == 2


def test_review_text_importer_writes_main_and_lookup_rows(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    path.write_text(
        json.dumps(
            {
                "category": "Office_Products",
                "user_id": "u1",
                "parent_asin": "p1",
                "asin": "a1",
                "rating": 4.0,
                "title": "Solid",
                "text": "Full body",
                "timestamp": 1700000000000,
                "verified_purchase": False,
                "helpful_vote": 2,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    session = FakeSession()

    result = import_review_text_to_scylla(inputs=[path], write=True, session=session, batch_size=1)

    assert result["reports"][0]["write_status"] == "written"
    assert result["reports"][0]["written_rows"] == 1
    assert any("INSERT INTO review_text_by_key" in statement for statement in session.prepared)
    assert any("INSERT INTO review_text_by_item" in statement for statement in session.prepared)
    assert any("INSERT INTO review_text_by_user" in statement for statement in session.prepared)
    main_call = next(call for call in session.calls if isinstance(call[1], tuple) and len(call[1]) == 16)
    assert main_call[1][1] == "Office_Products"
    assert main_call[1][4] == "a1"
    assert main_call[1][7] == 4.0
    assert main_call[1][8] == "Solid"
    assert main_call[1][9] == "Full body"
    assert main_call[1][11] is False
    assert main_call[1][12] == 2


def test_review_text_importer_retries_transient_write_timeout(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl"
    path.write_text(
        json.dumps(
            {
                "category": "Electronics",
                "user_id": "u1",
                "parent_asin": "p1",
                "asin": "a1",
                "title": "Good",
                "text": "Full body",
                "timestamp": 1700000000000,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    session = FlakySession()

    result = import_review_text_to_scylla(
        inputs=[path],
        write=True,
        session=session,
        retry_attempts=2,
        retry_sleep_seconds=0,
    )

    assert result["reports"][0]["written_rows"] == 1
    assert session.failed_once is True
    by_item_calls = [call for call in session.calls if "INSERT INTO review_text_by_item" in str(call[0])]
    assert len(by_item_calls) == 1


def test_review_text_apply_schema_executes_cql_statements(tmp_path: Path) -> None:
    schema = tmp_path / "schema.cql"
    schema.write_text("CREATE KEYSPACE IF NOT EXISTS x;\nCREATE TABLE IF NOT EXISTS x.t (id text PRIMARY KEY);\n")
    session = FakeSession()

    result = import_review_text_to_scylla(inputs=[], apply_schema=True, schema_path=schema, session=session)

    assert result["apply_schema"] is True
    assert result["statement_count"] == 2
    assert len(session.calls) == 2
    assert DEFAULT_SCHEMA_PATH.name == "001_review_text_store.cql"
