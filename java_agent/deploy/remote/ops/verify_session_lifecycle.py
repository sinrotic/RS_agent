#!/usr/bin/env python3
"""在隔离 MySQL 中验证仓库 Session Mapper 的超时和原子准入 SQL，不访问正式数据。"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET


def fixture_payload(root):
    mapper = ET.parse(root / "java_agent/rs-service-user/src/main/resources/mapper/UserSessionMapper.xml")
    updates = {element.attrib["id"]: "".join(element.itertext()).strip() for element in mapper.findall("update")}
    schema = (root / "java_agent/sql/rs_service_user_schema.sql").read_text(encoding="utf-8")
    tables = []
    for table in ("rs_auth_account", "rs_user_session"):
        tables.append(re.search(r"CREATE TABLE IF NOT EXISTS " + table + r" \(.*?\n\);", schema, re.S).group())
    return {"updates": updates, "schema": "\n".join(tables)}


REMOTE = r'''
import json, re, secrets, subprocess, time, uuid
payload = PAYLOAD
container = "rs-agent-session-fixture-" + uuid.uuid4().hex
password = secrets.token_urlsafe(24)
report = {"status": "FAIL", "scope": "isolated_mysql_session_mapper_only"}
created = False
def command(args, **kwargs):
    result = subprocess.run(args, capture_output=True, timeout=60, **kwargs)
    if result.returncode: raise RuntimeError("隔离 MySQL 命令失败")
    return result.stdout
try:
    command(["docker", "run", "-d", "--name", container, "--network", "none", "--memory", "768m", "--cpus", "1",
             "--log-opt", "max-size=2m", "--label", "rs-agent-purpose=session-fixture", "-e", "MYSQL_ROOT_PASSWORD=" + password,
             "-e", "MYSQL_DATABASE=session_fixture", "mysql:8.0", "--innodb-buffer-pool-size=64M", "--performance-schema=OFF"])
    created = True
    def sql(statement):
        return command(["docker", "exec", "-i", container, "sh", "-ec",
                        'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql --default-character-set=utf8mb4 -N -u root session_fixture'],
                       input=statement.encode()).decode().splitlines()
    for attempt in range(60):
        try:
            sql("SELECT 1;"); break
        except RuntimeError:
            time.sleep(1)
    else: raise RuntimeError("隔离 MySQL 未就绪")
    sql(payload["schema"])
    sql("INSERT INTO rs_auth_account(account_id,username,password_hash) VALUES('account','fixture','fixture');")
    sql("""INSERT INTO rs_user_session(session_id,account_id,profile_user_id,active_preferences_json,last_active_at,status)
        VALUES('active','account','profile','{}','2026-10-10 09:00:00','ACTIVE'),
              ('expired','account','profile','{}','2026-10-09 10:00:00','ACTIVE'),
              ('ended','account','profile','{}','2026-10-10 09:00:00','ENDED');""")
    values = {"accountId": "account", "profileUserId": "profile", "now": "2026-10-10 10:00:00",
              "cutoff": "2026-10-09 10:00:00", "query": "预算五百，品牌 O'Reilly"}
    def update(name, session, **overrides):
        parameters = {**values, "sessionId": session, **overrides}
        statement = re.sub(r"#\{(\w+)\}", lambda match: "'" + parameters[match[1]].replace("'", "''") + "'", payload["updates"][name])
        return sql(statement + "; SELECT ROW_COUNT();")[0]
    assert update("admitSession", "active", accountId="other") == "0"
    assert update("admitSession", "active", profileUserId="other") == "0"
    assert update("admitSession", "active") == "1"
    assert sql("SELECT DATE_FORMAT(last_active_at,'%Y-%m-%d %H:%i:%s'),last_user_query FROM rs_user_session WHERE session_id='active';") == ["2026-10-10 10:00:00\t预算五百，品牌 O'Reilly"]
    assert update("expireOwnedSession", "active") == "0"
    assert update("admitSession", "expired") == "0"
    assert update("expireOwnedSession", "expired") == "1"
    assert update("expireOwnedSession", "expired") == "0"
    assert update("admitSession", "expired") == "0"
    assert update("admitSession", "ended") == "0"
    sql("UPDATE rs_user_session SET status='ENDED' WHERE session_id='active';")
    assert update("admitSession", "active") == "0"
    report.update(status="PASS", assertions=11, activity_refreshed=True, cutoff_exclusive=True,
                  account_and_profile_isolated=True, ended_session_not_revived=True)
except Exception as error:
    report["error"] = type(error).__name__
finally:
    if created:
        cleanup = subprocess.run(["docker", "rm", "-f", "-v", container], capture_output=True, timeout=30)
        report["temporary_container_removed"] = cleanup.returncode == 0
        if cleanup.returncode: report["status"] = "FAIL"
print(json.dumps(report, ensure_ascii=False))
raise SystemExit(0 if report["status"] == "PASS" else 1)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--host", default="server")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = fixture_payload(args.root.resolve())
    script = REMOTE.replace("payload = PAYLOAD", "payload = json.loads(" + repr(json.dumps(payload)) + ")")
    result = subprocess.run(["ssh", args.host, "python3 -"], input=script.encode(), capture_output=True, timeout=180)
    # 输出仅包含结构化验收报告，不记录容器密码或数据库命令。
    report = json.loads(result.stdout.decode().splitlines()[-1])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
