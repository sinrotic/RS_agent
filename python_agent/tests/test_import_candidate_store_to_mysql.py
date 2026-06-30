from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.serving.import_candidate_store_to_mysql import _insert_sql, import_candidate_store_to_mysql


def test_importer_dry_run_classifies_pool500_usercf_rows(tmp_path: Path) -> None:
    path = tmp_path / "usercf_candidates.jsonl"
    path.write_text(json.dumps({"user_id": "u1", "item_id": "i1", "sources": ["usercf_bounded"], "source_scores": {"usercf_bounded": 0.7}}) + "\n", encoding="utf-8")

    result = import_candidate_store_to_mysql(inputs=[path], limit_rows=10, artifact_id="artifact-1")

    assert result["dry_run"] is True
    report = result["reports"][0]
    assert report["schema"] == "usercf_candidates"
    assert report["status"] == "supported"
    assert report["importable_rows"] == 1
    assert report["sources"] == {"usercf_recall": 1}


def test_importer_write_skips_unsupported_without_runner(tmp_path: Path) -> None:
    path = tmp_path / "unsupported.jsonl"
    path.write_text(json.dumps({"hello": "world"}) + "\n", encoding="utf-8")
    calls: list[tuple[list[str], str]] = []

    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        calls.append((command, sql))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = import_candidate_store_to_mysql(inputs=[path], write=True, runner=runner)

    assert calls == []
    assert result["dry_run"] is False
    assert result["reports"][0]["write_status"] == "skipped_unsupported_schema"


def test_importer_write_generates_mysql_stdin_sql_with_on_duplicate_key_update(tmp_path: Path) -> None:
    path = tmp_path / "usercf_candidates.jsonl"
    path.write_text(json.dumps({"user_id": "u1", "parent_asin": "i1", "source": "usercf", "score": 1.2, "rank": 3}) + "\n", encoding="utf-8")
    calls: list[tuple[list[str], str]] = []

    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        calls.append((command, sql))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = import_candidate_store_to_mysql(inputs=[path], write=True, runner=runner, batch_size=1, artifact_id="artifact-2")

    assert result["reports"][0]["write_status"] == "written"
    assert result["reports"][0]["written_rows"] == 1
    command, sql = calls[0]
    assert command[:3] == ["docker", "compose", "-f"]
    assert command[-3:] == ["sh", "-lc", "MYSQL_PWD=\"$MYSQL_PASSWORD\" mysql --batch --raw --skip-column-names --default-character-set=utf8mb4 -u 'rs_agent' 'rs_agent'"]
    assert "artifact-2" in sql
    assert "INSERT INTO usercf_candidates" in sql
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "VALUES(score)" in sql
    assert "rs_agent_dev_only" not in " ".join(command)


def test_item_neighbor_insert_sql_is_mysql_idempotent() -> None:
    sql = _insert_sql(
        "item_neighbors",
        [{"source": "itemcf", "src_item_id": "s1", "dst_item_id": "d1", "score": 0.5, "rank": 1, "category": "", "artifact_id": "a1", "metadata": {}}],
    )

    assert "INSERT INTO item_neighbors" in sql
    assert "`rank`" in sql
    assert "CAST('{" in sql
    assert "ON DUPLICATE KEY UPDATE" in sql


def test_importer_dedupes_duplicate_usercf_keys_before_write(tmp_path: Path) -> None:
    path = tmp_path / "usercf_candidates.jsonl"
    path.write_text(
        "\n".join([
            json.dumps({"user_id": "u1", "item_id": "i1", "score": 0.1}),
            json.dumps({"user_id": "u1", "item_id": "i1", "score": 0.9}),
        ])
        + "\n",
        encoding="utf-8",
    )
    calls: list[tuple[list[str], str]] = []

    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        calls.append((command, sql))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = import_candidate_store_to_mysql(inputs=[path], write=True, runner=runner, batch_size=50)

    assert result["reports"][0]["duplicate_rows"] == 1
    assert result["reports"][0]["written_rows"] == 1
    assert "0.9" in calls[0][1]
    assert "0.1" not in calls[0][1]


def test_importer_rejects_partial_artifact_in_write_mode(tmp_path: Path) -> None:
    path = tmp_path / "mixed.jsonl"
    path.write_text(json.dumps({"user_id": "u1", "item_id": "i1"}) + "\n" + json.dumps({"src_item": "s1", "dst_item": "d1"}) + "\n", encoding="utf-8")
    calls: list[tuple[list[str], str]] = []

    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        calls.append((command, sql))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = import_candidate_store_to_mysql(inputs=[path], write=True, runner=runner)

    assert calls == []
    assert result["reports"][0]["mixed_schema_rows"] == 1
    assert result["reports"][0]["write_status"] == "rejected_partial_artifact"
