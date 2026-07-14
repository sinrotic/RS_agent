from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class BatchWindow:
    end_item_id: str
    row_count: int


@dataclass(frozen=True)
class ProjectionRun:
    run_id: int
    status: str
    last_source_item_id: str
    processed_rows: int
    source_rows: int


class MysqlCli:
    def __init__(self, container: str) -> None:
        self.container = container

    def query_rows(self, sql: str) -> list[tuple[str, ...]]:
        output = self._run(sql)
        return [tuple(line.split("\t")) for line in output.splitlines() if line.strip()]

    def execute(self, sql: str) -> None:
        self._run(sql)

    def _run(self, sql: str) -> str:
        command = [
            "docker",
            "exec",
            "-i",
            self.container,
            "sh",
            "-lc",
            'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql '
            "--batch --raw --skip-column-names --default-character-set=utf8mb4 "
            '-u"$MYSQL_USER" "$MYSQL_DATABASE"',
        ]
        process = subprocess.run(
            command,
            input=sql,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=600,
            check=False,
        )
        if process.returncode != 0:
            detail = process.stderr.strip()[-4000:]
            raise RuntimeError(f"mysql command failed ({process.returncode}): {detail}")
        return process.stdout


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Project amazon_items_base into the canonical rs_catalog_item table."
    )
    parser.add_argument("--container", default="rs-agent-java-mysql")
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--resume-run-id", type=int)
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--progress-every", type=int, default=10)
    return parser.parse_args(argv)


def sql_text(value: str) -> str:
    cleaned = str(value).replace("\x00", "")
    return "'" + cleaned.replace("\\", "\\\\").replace("'", "''") + "'"


def next_batch_window(mysql: MysqlCli, after_item_id: str, batch_size: int) -> BatchWindow | None:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    rows = mysql.query_rows(
        "SELECT COALESCE(MAX(batch.parent_asin), ''), COUNT(*) "
        "FROM ("
        "SELECT DISTINCT parent_asin FROM amazon_items_base "
        f"WHERE parent_asin > {sql_text(after_item_id)} "
        f"ORDER BY parent_asin LIMIT {batch_size}"
        ") AS batch"
    )
    if not rows:
        return None
    end_item_id, row_count = rows[0]
    count = int(row_count)
    if count == 0 or not end_item_id:
        return None
    return BatchWindow(end_item_id=end_item_id, row_count=count)


def build_projection_batch_sql(
    run_id: int,
    after_item_id: str,
    end_item_id: str,
    row_count: int,
) -> str:
    after = sql_text(after_item_id)
    end = sql_text(end_item_id)
    return f"""
SET SESSION group_concat_max_len = 16777215;
START TRANSACTION;
INSERT INTO rs_catalog_item (
    item_id,
    source_item_id,
    title,
    category,
    category_path,
    brand,
    store_name,
    price,
    image_url,
    summary,
    description,
    attributes_json,
    raw_metadata_json,
    status
)
SELECT
    source.parent_asin,
    source.parent_asin,
    COALESCE(NULLIF(TRIM(source.title), ''), source.parent_asin),
    COALESCE(NULLIF(TRIM(source.main_category), ''), NULLIF(TRIM(source.category), '')),
    (
        SELECT GROUP_CONCAT(category_row.category_value ORDER BY category_row.category_index SEPARATOR ' > ')
        FROM JSON_TABLE(source.categories, '$[*]' COLUMNS (
            category_index FOR ORDINALITY,
            category_value VARCHAR(512) PATH '$'
        )) AS category_row
    ),
    COALESCE(
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(source.details, '$.Brand')), 'null'),
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(source.details, '$.brand')), 'null')
    ),
    NULLIF(TRIM(source.store), ''),
    source.price,
    COALESCE(
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(source.images, '$[0].hi_res')), 'null'),
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(source.images, '$[0].large')), 'null'),
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(source.images, '$[0].thumb')), 'null')
    ),
    COALESCE(
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(source.features, '$[0]')), 'null'),
        NULLIF(TRIM(source.title), ''),
        source.parent_asin
    ),
    (
        SELECT GROUP_CONCAT(
            description_row.description_value
            ORDER BY description_row.description_index SEPARATOR '\\n'
        )
        FROM JSON_TABLE(source.description, '$[*]' COLUMNS (
            description_index FOR ORDINALITY,
            description_value MEDIUMTEXT PATH '$'
        )) AS description_row
    ),
    COALESCE(source.details, JSON_OBJECT()),
    JSON_OBJECT(
        'dataset', source.dataset,
        'source_category', source.category,
        'source_file', source.source_file,
        'source_line', source.source_line,
        'average_rating', source.average_rating,
        'rating_number', source.rating_number
    ),
    'active'
FROM amazon_items_base AS source
WHERE source.parent_asin > {after}
  AND source.parent_asin <= {end}
ORDER BY source.parent_asin
ON DUPLICATE KEY UPDATE
    source_item_id = VALUES(source_item_id),
    title = VALUES(title),
    category = VALUES(category),
    category_path = VALUES(category_path),
    brand = VALUES(brand),
    store_name = VALUES(store_name),
    price = VALUES(price),
    image_url = VALUES(image_url),
    summary = VALUES(summary),
    description = VALUES(description),
    attributes_json = VALUES(attributes_json),
    raw_metadata_json = VALUES(raw_metadata_json),
    status = 'active',
    updated_at = CURRENT_TIMESTAMP;
UPDATE rs_catalog_projection_run
SET status = 'RUNNING',
    last_source_item_id = {end},
    processed_rows = processed_rows + {row_count},
    error_message = NULL
WHERE run_id = {run_id};
COMMIT;
""".strip()


def start_projection_run(mysql: MysqlCli) -> ProjectionRun:
    source_rows = int(mysql.query_rows("SELECT COUNT(DISTINCT parent_asin) FROM amazon_items_base")[0][0])
    rows = mysql.query_rows(
        "INSERT INTO rs_catalog_projection_run (status, source_rows) "
        f"VALUES ('RUNNING', {source_rows}); SELECT LAST_INSERT_ID();"
    )
    return ProjectionRun(int(rows[-1][0]), "RUNNING", "", 0, source_rows)


def load_projection_run(mysql: MysqlCli, run_id: int) -> ProjectionRun:
    rows = mysql.query_rows(
        "SELECT run_id, status, last_source_item_id, processed_rows, source_rows "
        f"FROM rs_catalog_projection_run WHERE run_id = {run_id}"
    )
    if not rows:
        raise ValueError(f"projection run {run_id} does not exist")
    row = rows[0]
    return ProjectionRun(int(row[0]), row[1], row[2], int(row[3]), int(row[4]))


def resume_projection_run(mysql: MysqlCli, run: ProjectionRun) -> ProjectionRun:
    if run.status == "COMPLETED":
        raise ValueError(f"projection run {run.run_id} is already completed")
    mysql.execute(
        "UPDATE rs_catalog_projection_run SET status = 'RUNNING', error_message = NULL "
        f"WHERE run_id = {run.run_id}"
    )
    return ProjectionRun(run.run_id, "RUNNING", run.last_source_item_id, run.processed_rows, run.source_rows)


def complete_projection_run(mysql: MysqlCli, run_id: int) -> None:
    mysql.execute(
        "UPDATE rs_catalog_projection_run "
        "SET status = 'COMPLETED', completed_at = CURRENT_TIMESTAMP, error_message = NULL "
        f"WHERE run_id = {run_id}"
    )


def fail_projection_run(mysql: MysqlCli, run_id: int, error: BaseException) -> None:
    message = str(error).replace("\r", " ").replace("\n", " ")[:2000]
    mysql.execute(
        "UPDATE rs_catalog_projection_run "
        f"SET status = 'FAILED', error_message = {sql_text(message)} WHERE run_id = {run_id}"
    )


def run_projection(mysql: MysqlCli, run: ProjectionRun, batch_size: int, max_batches: int | None, progress_every: int) -> ProjectionRun:
    current = run
    batch_number = 0
    while max_batches is None or batch_number < max_batches:
        window = next_batch_window(mysql, current.last_source_item_id, batch_size)
        if window is None:
            complete_projection_run(mysql, current.run_id)
            return ProjectionRun(
                current.run_id,
                "COMPLETED",
                current.last_source_item_id,
                current.processed_rows,
                current.source_rows,
            )
        mysql.execute(
            build_projection_batch_sql(
                current.run_id,
                current.last_source_item_id,
                window.end_item_id,
                window.row_count,
            )
        )
        batch_number += 1
        current = ProjectionRun(
            current.run_id,
            "RUNNING",
            window.end_item_id,
            current.processed_rows + window.row_count,
            current.source_rows,
        )
        if batch_number % max(1, progress_every) == 0:
            print(json.dumps(current.__dict__, ensure_ascii=True), flush=True)
    return current


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.batch_size <= 0:
        raise ValueError("batch_size must be positive")
    mysql = MysqlCli(args.container)
    run = (
        resume_projection_run(mysql, load_projection_run(mysql, args.resume_run_id))
        if args.resume_run_id is not None
        else start_projection_run(mysql)
    )
    print(json.dumps(run.__dict__, ensure_ascii=True), flush=True)
    try:
        result = run_projection(mysql, run, args.batch_size, args.max_batches, args.progress_every)
    except BaseException as error:
        try:
            fail_projection_run(mysql, run.run_id, error)
        except BaseException as mark_error:
            print(f"failed to mark projection run: {mark_error}", file=sys.stderr)
        raise
    print(json.dumps(result.__dict__, ensure_ascii=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
