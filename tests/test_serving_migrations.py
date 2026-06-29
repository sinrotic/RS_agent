from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.serving]

REPO_ROOT = Path(__file__).resolve().parents[1]
DDL_PATH = REPO_ROOT / "configs" / "serving" / "schema" / "phase1a_serving_baseline.sql"
MAPPING_PATH = REPO_ROOT / "configs" / "serving" / "schema" / "sqlite_to_phase1a_mapping.json"

REQUIRED_TABLES = {
    "serving_sessions",
    "serving_turns",
    "serving_feedback_events",
    "serving_request_summaries",
    "outbox_events",
    "recommendation_requests",
    "recommendation_results",
    "recall_traces",
    "artifact_registry",
    "rag_evidence",
    "task_runs",
}

SQLITE_TABLES = {
    "serving_sessions",
    "serving_turns",
    "serving_feedback_events",
    "serving_request_summaries",
}


def test_phase1a_sql_baseline_exists_without_alembic_or_runtime_adapter() -> None:
    sql = DDL_PATH.read_text(encoding="utf-8").lower()

    assert "no alembic" in sql
    assert "mysql-only structured store baseline" in sql
    assert "alembic_version" not in sql
    assert "create extension" not in sql


def test_phase1a_sql_baseline_declares_required_tables_indexes_and_constraints() -> None:
    sql = DDL_PATH.read_text(encoding="utf-8")
    declared_tables = set(re.findall(r"CREATE TABLE\s+([a-z_]+)\s*\(", sql, flags=re.IGNORECASE))
    declared_indexes = set(re.findall(r"CREATE INDEX\s+([a-z_]+)\s+ON\s+([a-z_]+)", sql, flags=re.IGNORECASE))

    assert REQUIRED_TABLES <= declared_tables
    assert {table for _, table in declared_indexes} >= {
        "serving_turns",
        "serving_feedback_events",
        "serving_request_summaries",
        "outbox_events",
        "recommendation_results",
        "recall_traces",
        "rag_evidence",
        "task_runs",
    }
    assert "PRIMARY KEY" in sql
    assert "REFERENCES serving_sessions" in sql
    assert "UNIQUE(session_id, turn_index)" in sql


def test_sqlite_to_phase1a_mapping_covers_current_public_persistence_schema() -> None:
    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))

    assert mapping["phase"] == "1a"
    assert mapping["runtime_adapter"] == "not_implemented_in_phase_1a"
    assert mapping["migration_framework"] == "sql_ddl_baseline_only_no_alembic"
    assert set(mapping["tables"]) == SQLITE_TABLES
    assert mapping["tables"]["serving_feedback_events"]["fields"]["comment"] == "comment_public"
    assert mapping["tables"]["serving_feedback_events"]["fields"]["comment_truncated"] == "comment_truncated"
    assert mapping["tables"]["serving_feedback_events"]["fields"]["comment_redacted"] == "comment_redacted"


def test_mapping_targets_exist_in_phase1a_sql_baseline() -> None:
    sql = DDL_PATH.read_text(encoding="utf-8")
    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    declared_tables = set(re.findall(r"CREATE TABLE\s+([a-z_]+)\s*\(", sql, flags=re.IGNORECASE))

    for table_mapping in mapping["tables"].values():
        assert table_mapping["target_table"] in declared_tables
