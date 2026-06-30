from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.data.import_recent2y_to_mysql import (
    _insert_sql,
    import_recent2y_to_mysql,
    interaction_row,
    ms_to_mysql_datetime,
    product_row,
    sequence_row,
)


def test_recent2y_row_transforms_use_mysql_shape() -> None:
    product = product_row(
        {
            "parent_asin": "B001",
            "title_clean": "Desk lamp",
            "category": "Office",
            "categories_flat": ["Office", "Lighting"],
            "store": "BrandA",
            "average_rating": 4.5,
            "description_text": "Bright",
            "features_text": "LED",
        },
        "recent_2y",
    )
    interaction = interaction_row(
        {"user_id": "u1", "parent_asin": "B001", "timestamp": 1704067200000, "rating": 5.0, "label_binary": 1, "split": "train", "category": "Office"},
        "recent_2y",
    )
    sequence = sequence_row({"user_id": "u1", "recent_item_sequence": ["B001"], "recent_positive_item_sequence": ["B001"]}, "recent_2y")

    assert product[0] == "B001"
    assert product[3] == ["Office", "Lighting"]
    assert product[8] == ["LED"]
    assert product[9]["import_source"] == "recent_2y"
    assert interaction[:3] == ["u1", "B001", "rating"]
    assert interaction[3] == "2024-01-01 00:00:00"
    assert interaction[7] == "recent_2y"
    assert sequence[:3] == ["u1", "recent_2y", ["B001"]]


def test_ms_to_mysql_datetime_accepts_seconds_and_invalid_values() -> None:
    assert ms_to_mysql_datetime(1704067200) == "2024-01-01 00:00:00"
    assert ms_to_mysql_datetime("bad") is None


def test_dry_run_reports_selected_inputs_without_writing(tmp_path: Path) -> None:
    (tmp_path / "canonical_items.jsonl").write_text("", encoding="utf-8")

    result = import_recent2y_to_mysql(source_dir=tmp_path, write=False, skip_interactions=True, skip_user_sequences=True)

    assert result["dry_run"] is True
    assert result["reports"]["products"]["exists"] is True
    assert result["reports"]["interactions"]["selected"] is False
    assert result["reports"]["user_sequences"]["selected"] is False


def test_insert_sql_uses_mysql_json_and_on_duplicate_key_update() -> None:
    sql = _insert_sql("products", ["parent_asin", "categories", "metadata"], [["B001", ["Office"], {"source": "recent_2y"}]])

    assert "INSERT INTO products" in sql
    assert "CAST('[\"Office\"]' AS JSON)" in sql
    assert "CAST('{\"source\":\"recent_2y\"}' AS JSON)" in sql
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "parent_asin = VALUES(parent_asin)" not in sql


def test_write_mode_streams_batches_to_mysql_runner(tmp_path: Path) -> None:
    (tmp_path / "canonical_items.jsonl").write_text(
        json.dumps({"parent_asin": "B001", "title_clean": "Desk lamp", "category": "Office"}) + "\n",
        encoding="utf-8",
    )
    calls: list[tuple[list[str], str]] = []

    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        calls.append((command, sql))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = import_recent2y_to_mysql(
        source_dir=tmp_path,
        write=True,
        skip_interactions=True,
        skip_user_sequences=True,
        batch_size=1,
        runner=runner,
    )

    assert result["dry_run"] is False
    assert result["imported"] == {"products": 1}
    command, sql = calls[0]
    assert command[-3:] == ["sh", "-lc", "MYSQL_PWD=\"$MYSQL_PASSWORD\" mysql --batch --raw --skip-column-names --default-character-set=utf8mb4 -u 'rs_agent' 'rs_agent'"]
    assert "INSERT INTO products" in sql
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "rs_agent_dev_only" not in " ".join(command)


def test_write_mode_can_truncate_before_import(tmp_path: Path) -> None:
    (tmp_path / "canonical_items.jsonl").write_text("", encoding="utf-8")
    calls: list[tuple[list[str], str]] = []

    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        calls.append((command, sql))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    import_recent2y_to_mysql(source_dir=tmp_path, write=True, truncate=True, skip_interactions=True, skip_user_sequences=True, runner=runner)

    assert calls[0][1] == "TRUNCATE TABLE interactions;\nTRUNCATE TABLE user_sequences;\nTRUNCATE TABLE products;"
