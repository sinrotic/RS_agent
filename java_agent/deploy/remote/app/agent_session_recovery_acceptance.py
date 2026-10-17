#!/usr/bin/env python3
"""仅选取浏览器验收账号的已完成会话，验证 Agent 重启恢复与归属隔离。"""
import json
import subprocess
import time
import urllib.error
from pathlib import Path
from feedback_acceptance import sql
from personalized_home_acceptance import http


def main():
    row = sql("""
      SELECT p.session_id, s.profile_user_id
      FROM agent_sessions p JOIN rs_user_session s ON s.session_id = p.session_id
      JOIN rs_auth_account a ON a.account_id = s.account_id
      WHERE a.username LIKE 'paging_%' AND p.last_entry_type = 'ASSISTANT_FINAL'
      ORDER BY p.updated_at DESC LIMIT 1
    """)
    assert row, "没有已完成的浏览器验收会话"
    session, profile = row.split("\t")
    base = "http://127.0.0.1:18104"
    path = "/api/agent/sessions/" + session + "/turns"
    headers = {"X-Profile-User-Id": profile}
    before = http(base, path, headers=headers)
    assert len(before["turns"]) >= 2
    subprocess.run(["docker", "restart", "-t", "10", "rs-agent-java-service-agent"], check=True, capture_output=True, timeout=45)
    started = time.monotonic()
    for _ in range(40):
        try:
            if http(base, "/actuator/health/readiness", timeout=2)["status"] == "UP": break
        except Exception: pass
        time.sleep(1)
    else: raise AssertionError("Agent 重启后未就绪")
    after = http(base, path, headers=headers)
    assert [(turn["request_id"], turn["assistant_message"]) for turn in before["turns"]] == [
        (turn["request_id"], turn["assistant_message"]) for turn in after["turns"]]
    try:
        http(base, path, headers={"X-Profile-User-Id": "unrelated-acceptance-profile"})
        raise AssertionError("其他画像能够读取验收会话")
    except urllib.error.HTTPError as error:
        assert error.code == 404
    report = {"status": "PASS", "session_id": session, "turns": len(after["turns"]),
              "restart_readiness_seconds": round(time.monotonic() - started, 2), "foreign_profile_http_status": 404}
    Path("agent-session-recovery-acceptance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
