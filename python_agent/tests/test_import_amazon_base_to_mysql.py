from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.data.import_amazon_base_to_mysql import (
    _insert_sql,
    import_amazon_base_to_mysql,
    item_row,
    ms_to_mysql_datetime,
    review_row,
)


def test_amazon_base_row_transforms_use_raw_mysql_shape(tmp_path: Path) -> None:
    item = item_row(
        {
            "dataset": "McAuley-Lab/Amazon-Reviews-2023",
            "category": "Office_Products",
            "parent_asin": "B001",
            "title": "Desk lamp",
            "main_category": "Office Products",
            "categories": ["Office", "Lighting"],
            "description": ["Bright lamp"],
            "features": ["LED"],
            "images": [{"variant": "MAIN", "large": "https://example.test/lamp.jpg"}],
            "price": 12.5,
            "average_rating": 4.5,
            "rating_number": 10,
            "store": "StoreA",
            "details": {"Brand": "StoreA"},
        },
        source_path=tmp_path / "metadata.base.jsonl",
        source_line=7,
    )
    review = review_row(
        {
            "dataset": "McAuley-Lab/Amazon-Reviews-2023",
            "category": "Office_Products",
            "user_id": "u1",
            "parent_asin": "B001",
            "asin": "A001",
            "rating": 5.0,
            "title": "Great",
            "text": "Works well",
            "text_len": 10,
            "timestamp": 1704067200000,
            "verified_purchase": True,
            "helpful_vote": 2,
        },
        source_path=tmp_path / "reviews.base.jsonl",
        source_line=3,
    )

    assert item[:4] == ["McAuley-Lab/Amazon-Reviews-2023", "Office_Products", "B001", "Desk lamp"]
    assert item[5] == ["Office", "Lighting"]
    assert item[8] == [{"variant": "MAIN", "large": "https://example.test/lamp.jpg"}]
    assert item[13] == "StoreA"
    assert review[0]
    assert review[1:6] == ["McAuley-Lab/Amazon-Reviews-2023", "Office_Products", "u1", "B001", "A001"]
    assert review[7:11] == [10, True, True, review[0]]
    assert review[12] == "2024-01-01 00:00:00"
    assert review[13] is True


def test_ms_to_mysql_datetime_accepts_seconds_and_invalid_values() -> None:
    assert ms_to_mysql_datetime(1704067200) == "2024-01-01 00:00:00"
    assert ms_to_mysql_datetime("bad") is None


def test_dry_run_reports_manifest_inputs(tmp_path: Path) -> None:
    metadata_path = tmp_path / "metadata.base.jsonl"
    reviews_path = tmp_path / "reviews.base.jsonl"
    metadata_path.write_text("", encoding="utf-8")
    reviews_path.write_text("", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "outputs": [
                    {
                        "category": "Office_Products",
                        "metadata_path": str(metadata_path),
                        "reviews_path": str(reviews_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = import_amazon_base_to_mysql(manifest_path=manifest_path, write=False, skip_reviews=True)

    assert result["dry_run"] is True
    assert result["reports"][0]["table"] == "amazon_items_base"
    assert result["reports"][0]["exists"] is True
    assert result["reports"][1]["selected"] is False


def test_insert_sql_uses_json_and_raw_table_upsert() -> None:
    sql = _insert_sql(
        "amazon_items_base",
        ["category", "parent_asin", "categories", "images", "details"],
        [["Office", "B001", ["Office"], [{"variant": "MAIN", "large": "https://example.test/a.jpg"}], {"Brand": "A"}]],
    )

    assert "INSERT INTO amazon_items_base" in sql
    assert "CAST('[\"Office\"]' AS JSON)" in sql
    assert 'CAST(\'[{"variant":"MAIN","large":"https://example.test/a.jpg"}]\' AS JSON)' in sql
    assert "CAST('{\"Brand\":\"A\"}' AS JSON)" in sql
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "category = VALUES(category)" not in sql
    assert "parent_asin = VALUES(parent_asin)" not in sql


def test_write_mode_can_create_schema_truncate_and_insert(tmp_path: Path) -> None:
    metadata_path = tmp_path / "metadata.base.jsonl"
    reviews_path = tmp_path / "reviews.base.jsonl"
    metadata_path.write_text(
        json.dumps(
            {
                "dataset": "McAuley-Lab/Amazon-Reviews-2023",
                "category": "Office_Products",
                "parent_asin": "B001",
                "title": "Desk lamp",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    reviews_path.write_text(
        json.dumps(
            {
                "dataset": "McAuley-Lab/Amazon-Reviews-2023",
                "category": "Office_Products",
                "user_id": "u1",
                "parent_asin": "B001",
                "rating": 5.0,
                "timestamp": 1704067200000,
                "verified_purchase": True,
                "helpful_vote": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "outputs": [
                    {
                        "category": "Office_Products",
                        "metadata_path": str(metadata_path),
                        "reviews_path": str(reviews_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text("CREATE TABLE amazon_items_base (id INT);", encoding="utf-8")
    calls: list[tuple[list[str], str]] = []

    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        calls.append((command, sql))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = import_amazon_base_to_mysql(
        manifest_path=manifest_path,
        schema_file=schema_file,
        create_schema=True,
        truncate=True,
        write=True,
        batch_size=1,
        runner=runner,
    )

    assert result["dry_run"] is False
    assert result["imported"] == {"amazon_items_base": 1, "amazon_reviews_base": 1}
    assert calls[0][1] == "CREATE TABLE amazon_items_base (id INT);"
    assert calls[1][1] == "TRUNCATE TABLE amazon_reviews_base;\nTRUNCATE TABLE amazon_items_base;"
    assert "INSERT INTO amazon_items_base" in calls[2][1]
    assert "INSERT INTO amazon_reviews_base" in calls[3][1]
    assert calls[2][0][-3:] == ["sh", "-lc", "MYSQL_PWD=\"$MYSQL_PASSWORD\" mysql --batch --raw --skip-column-names --default-character-set=utf8mb4 -u 'rs_agent' 'rs_agent'"]


def test_recent2y_universe_filters_base_items_and_reviews(tmp_path: Path) -> None:
    metadata_path = tmp_path / "metadata.base.jsonl"
    reviews_path = tmp_path / "reviews.base.jsonl"
    metadata_path.write_text(
        "\n".join(
            [
                json.dumps({"dataset": "Amazon", "category": "Office_Products", "parent_asin": "keep", "title": "Keep"}),
                json.dumps({"dataset": "Amazon", "category": "Office_Products", "parent_asin": "drop", "title": "Drop"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    reviews_path.write_text(
        "\n".join(
            [
                json.dumps({"dataset": "Amazon", "category": "Office_Products", "user_id": "u1", "parent_asin": "keep", "timestamp": 1000}),
                json.dumps({"dataset": "Amazon", "category": "Office_Products", "user_id": "u2", "parent_asin": "keep", "timestamp": 2000}),
                json.dumps({"dataset": "Amazon", "category": "Office_Products", "user_id": "u1", "parent_asin": "drop", "timestamp": 1000}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"outputs": [{"category": "Office_Products", "metadata_path": str(metadata_path), "reviews_path": str(reviews_path)}]}),
        encoding="utf-8",
    )
    recent2y_dir = tmp_path / "recent2y"
    recent2y_dir.mkdir()
    (recent2y_dir / "canonical_items.jsonl").write_text(json.dumps({"parent_asin": "keep"}) + "\n", encoding="utf-8")
    (recent2y_dir / "canonical_interactions.train.jsonl").write_text(
        json.dumps({"user_id": "u1", "parent_asin": "keep", "timestamp": 1000}) + "\n",
        encoding="utf-8",
    )
    calls: list[tuple[list[str], str]] = []

    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        calls.append((command, sql))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = import_amazon_base_to_mysql(
        manifest_path=manifest_path,
        recent2y_source_dir=recent2y_dir,
        write=True,
        batch_size=10,
        runner=runner,
    )

    assert result["recent2y_filter"] == {"item_count": 1, "interaction_key_count": 1, "review_filter_mode": "strict"}
    item_sql = next(sql for _, sql in calls if "INSERT INTO amazon_items_base" in sql)
    review_sql = next(sql for _, sql in calls if "INSERT INTO amazon_reviews_base" in sql)
    assert "Keep" in item_sql
    assert "Drop" not in item_sql
    assert "u1" in review_sql
    assert "u2" not in review_sql
    assert "source_line" in review_sql
