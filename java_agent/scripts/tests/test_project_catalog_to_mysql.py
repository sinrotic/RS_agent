from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from project_catalog_to_mysql import (  # noqa: E402
    BatchWindow,
    build_projection_batch_sql,
    next_batch_window,
    sql_text,
)


class FakeMysql:
    def __init__(self, rows: list[tuple[str, ...]]) -> None:
        self.rows = rows
        self.queries: list[str] = []

    def query_rows(self, sql: str) -> list[tuple[str, ...]]:
        self.queries.append(sql)
        return self.rows


class ProjectionSqlTest(unittest.TestCase):
    def test_next_batch_uses_stable_item_id_cursor(self) -> None:
        mysql = FakeMysql([("A999", "250")])

        window = next_batch_window(mysql, "A050", 250)

        self.assertEqual(BatchWindow("A999", 250), window)
        self.assertIn("parent_asin > 'A050'", mysql.queries[0])
        self.assertIn("ORDER BY parent_asin", mysql.queries[0])
        self.assertIn("LIMIT 250", mysql.queries[0])

    def test_next_batch_returns_none_when_source_is_exhausted(self) -> None:
        mysql = FakeMysql([("", "0")])

        self.assertIsNone(next_batch_window(mysql, "Z999", 5000))

    def test_batch_sql_maps_online_fields_and_checkpoints_transactionally(self) -> None:
        sql = build_projection_batch_sql(7, "A050", "A999", 250)

        self.assertIn("START TRANSACTION", sql)
        self.assertIn("INSERT INTO rs_catalog_item", sql)
        self.assertIn("COALESCE(NULLIF(TRIM(source.title), ''), source.parent_asin)", sql)
        self.assertIn("JSON_TABLE(source.categories", sql)
        self.assertIn("JSON_EXTRACT(source.images, '$[0].hi_res')", sql)
        self.assertIn("JSON_EXTRACT(source.details, '$.Brand')", sql)
        self.assertIn("JSON_OBJECT(", sql)
        self.assertIn("'dataset', source.dataset", sql)
        self.assertIn("ON DUPLICATE KEY UPDATE", sql)
        self.assertIn("UPDATE rs_catalog_projection_run", sql)
        self.assertIn("last_source_item_id = 'A999'", sql)
        self.assertIn("processed_rows = processed_rows + 250", sql)
        self.assertIn("COMMIT", sql)
        self.assertNotIn("TRUNCATE", sql.upper())
        self.assertNotIn("raw_json", sql)

    def test_sql_text_escapes_quotes_backslashes_and_nuls(self) -> None:
        self.assertEqual("'A''B\\\\C'", sql_text("A'B\\C\x00"))


if __name__ == "__main__":
    unittest.main()
