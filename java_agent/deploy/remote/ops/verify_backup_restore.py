#!/usr/bin/env python3
"""在无网络、无宿主端口的临时 MySQL 中验证备份与恢复，不访问正式数据。"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import uuid


def command(arguments, **kwargs):
    result = subprocess.run(arguments, capture_output=True, timeout=90, **kwargs)
    if result.returncode:
        raise RuntimeError("isolated backup verification command failed")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--backup-script", type=Path, default=Path(__file__).resolve().parents[1] / "app/backup_application_state.sh")
    args = parser.parse_args()
    if not args.backup_script.is_file():
        parser.error("backup-script does not exist")
    work = args.work_dir.resolve()
    work.mkdir(parents=True, mode=0o700, exist_ok=False)
    container = "rs-agent-java-backup-fixture-" + uuid.uuid4().hex[:8]
    password = secrets.token_urlsafe(24)
    created = False
    report = {"status": "FAIL", "scope": "isolated_mysql_fixture_only; not_production_backup_or_scylla_restore"}
    try:
        command(["docker", "run", "-d", "--name", container, "--network", "none", "--memory", "768m",
                 "--log-opt", "max-size=2m", "--label", "rs-agent-purpose=backup-fixture",
                 "-e", f"MYSQL_ROOT_PASSWORD={password}", "-e", f"MYSQL_PASSWORD={password}",
                 "-e", "MYSQL_USER=rs_backup_fixture", "-e", "MYSQL_DATABASE=rs_backup_fixture", "mysql:8.0",
                 "--innodb-buffer-pool-size=64M", "--performance-schema=OFF"])
        created = True
        for attempt in range(60):
            ready = subprocess.run(["docker", "exec", container, "sh", "-ec",
                    'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u "$MYSQL_USER" "$MYSQL_DATABASE" -e "SELECT 1"'],
                    capture_output=True, timeout=5)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("isolated MySQL readiness timed out")
        print("隔离 MySQL 已就绪，开始校验备份与恢复", flush=True)

        def sql(statement, database="rs_backup_fixture"):
            return command(["docker", "exec", "-i", container, "sh", "-ec",
                            'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql -N -u root "$1"', "sh", database],
                           input=statement.encode())

        sql("""
            CREATE TABLE rs_auth_account(id INT PRIMARY KEY, username VARCHAR(64));
            INSERT INTO rs_auth_account VALUES(1,'fixture-a'),(2,'fixture-b');
            CREATE TABLE rs_user_session(id INT PRIMARY KEY, account_id INT);
            INSERT INTO rs_user_session VALUES(1,1);
            CREATE TABLE rs_recommend_feedback_event(id INT PRIMARY KEY, event_type VARCHAR(20));
            INSERT INTO rs_recommend_feedback_event VALUES(1,'like'),(2,'dislike');
            CREATE TABLE rs_catalog_item(id INT PRIMARY KEY);
            INSERT INTO rs_catalog_item VALUES(1);
        """)
        backup = work / "backup"
        environment = {**os.environ, "RS_MYSQL_CONTAINER": container, "RS_BACKUP_DIR": str(backup)}
        command(["bash", str(args.backup_script.resolve())], env=environment)
        dump = backup / "application.sql.gz"
        payload = gzip.decompress(dump.read_bytes())
        expected = (backup / "SHA256SUMS").read_text().split()[0]
        assert hashlib.sha256(dump.read_bytes()).hexdigest() == expected
        assert b"CREATE TABLE `rs_catalog_item`" not in payload
        sql("CREATE DATABASE rs_backup_restored;")
        command(["docker", "exec", "-i", container, "sh", "-ec",
                 'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql -u root rs_backup_restored'], input=payload)
        counts = sql("SELECT COUNT(*) FROM rs_auth_account; SELECT COUNT(*) FROM rs_user_session; SELECT COUNT(*) FROM rs_recommend_feedback_event;",
                     "rs_backup_restored").decode().splitlines()
        assert counts == ["2", "1", "2"]
        assert sql("SHOW TABLES;", "rs_backup_restored").decode().splitlines() == ["rs_auth_account", "rs_recommend_feedback_event", "rs_user_session"]
        report.update(status="PASS", restored_rows={"accounts": 2, "sessions": 1, "feedback": 2},
                      excluded_catalog=True, backup_sha256=expected)
    except Exception as error:
        report["error"] = type(error).__name__
    finally:
        if created:
            cleanup = subprocess.run(["docker", "rm", "-f", "-v", container], capture_output=True, timeout=30)
            report["temporary_container_removed"] = cleanup.returncode == 0
            if cleanup.returncode:
                report["status"] = "FAIL"
        (work / "backup-restore-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
