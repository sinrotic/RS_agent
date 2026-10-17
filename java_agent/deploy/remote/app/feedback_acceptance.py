#!/usr/bin/env python3
"""在部署主机执行真实 Gateway/MySQL 反馈验收；仅创建独立验收账号并撤销测试偏好。"""
import json
import secrets
import subprocess
import time
import urllib.error
import urllib.request


def sql(statement):
    result = subprocess.run(
        ["docker", "exec", "-i", "rs-agent-java-mysql", "sh", "-c",
         'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u"$MYSQL_USER" "$MYSQL_DATABASE" -N'],
        input=statement, text=True, capture_output=True, timeout=30, check=True,
    )
    return result.stdout.strip()


def literal(value):
    # 服务生成的标识符也需安全编码，避免将响应拼成 SQL 语法。
    return "CONVERT(0x" + value.encode().hex() + " USING utf8mb4)"


def main():
    token = None
    pending_reversals = []

    def call(path, data=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(
            "http://127.0.0.1:18088" + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            return json.loads(body) if body else {}

    def applied(ack):
        assert ack["accepted"]
        for _ in range(30):
            if ack["application_status"] == "APPLIED":
                return
            time.sleep(1)
            ack = call("/api/recommend/feedback/status/" + ack["feedback_id"])
        raise AssertionError("反馈未在 30 秒内变成 APPLIED")

    profile = sql("""
        SELECT r.user_id FROM (SELECT DISTINCT user_id FROM amazon_reviews_base LIMIT 100) r
        WHERE NOT EXISTS (SELECT 1 FROM rs_account_profile_binding b
                          WHERE BINARY b.profile_user_id = BINARY r.user_id)
          AND NOT EXISTS (SELECT 1 FROM rs_recommend_feedback_event f
                          WHERE BINARY f.profile_user_id = BINARY r.user_id)
        LIMIT 1;
    """)
    assert profile, "前 100 个画像中没有空闲验收画像，请明确指定新的验收数据范围"
    username = "acceptance_" + secrets.token_hex(8)
    auth = call("/api/auth/register", {
        "username": username, "password": secrets.token_urlsafe(24),
        "nickname": "Service Acceptance", "bindStrategy": "selected", "profileUserId": profile,
    })
    token = auth["accessToken"]
    print("PASS register", username, flush=True)
    try:
        session = call("/api/sessions", {"entryScene": "service-acceptance"})
        sid = session["sessionId"]
        print("PASS session", flush=True)
        body = {"session_id": sid, "scene": "home", "page_size": 5, "debug": False}
        rec = call("/api/recommend/home", body)
        assert len(rec["items"]) == 5
        rid = rec["request_id"]
        item = rec["items"][0]["item_id"]
        assert sql("SELECT COUNT(*) FROM rs_recommendation_delivery WHERE request_id=" + literal(rid)) == "1"
        assert not call("/api/recommend/preferences")["items"]
        print("PASS home and durable delivery", flush=True)
        exposure = call("/api/recommend/feedback/exposure", {
            "request_id": rid, "session_id": sid,
            "items": [{"item_id": item, "position": 1, "visible_ratio": 1,
                       "visible_duration_ms": 1200}], "exposed_at": int(time.time() * 1000),
        })
        assert exposure["accepted"] and exposure["application_status"] == "NOT_APPLICABLE"
        print("PASS exposure", flush=True)
        for kind in ["like", "dislike"]:
            feedback = {"request_id": rid, "session_id": sid, "item_id": item,
                        "event_type": kind, "event_value": 1, "occurred_at": int(time.time() * 1000)}
            ack = call("/api/recommend/feedback/event", feedback)
            eid = ack["feedback_id"]
            pending_reversals.append(eid)
            applied(ack)
            duplicate = call("/api/recommend/feedback/event", feedback)
            assert duplicate["duplicate"] and duplicate["feedback_id"] == eid
            assert sql("SELECT COUNT(*) FROM rs_recommend_feedback_event WHERE event_id=" + literal(eid)) == "1"
            assert sql("SELECT status FROM rs_recommend_feedback_outbox WHERE event_id=" + literal(eid)) == "APPLIED"
            page = call("/api/recommend/home/refresh", {**body, "refresh_token": "rerecall_pool500"})
            assert len(page["items"]) == 5 and page["has_more"]
            assert page["preference_version"] >= ack["preference_version"]
            assert eid in page["applied_feedback_event_ids"]
            visible = next((entry for entry in page["items"] if entry["item_id"] == item), None)
            if kind == "like":
                assert visible is None, "新一轮召回不应再次交付已展示的商品"
                assert any(any(tag.startswith("feedback_") for tag in entry["source_tags"]) for entry in page["items"])
            else:
                assert visible is None
            print("PASS", kind, "durability, idempotency, ranking and pagination", flush=True)
    finally:
        cleanup_errors = []
        for eid in reversed(pending_reversals):
            try:
                applied(call("/api/recommend/feedback/reversal", {"feedback_event_id": eid}))
            except Exception as error:
                cleanup_errors.append(str(error))
        try:
            if pending_reversals:
                assert not call("/api/recommend/preferences")["items"]
                page = call("/api/recommend/home", body)
                assert all(entry["item_id"] != item for entry in page["items"]), "撤销偏好不应清除近期交付去重"
                assert sql("SELECT current_state FROM rs_profile_item_preference_projection WHERE "
                           "profile_user_id=" + literal(profile) + " AND item_id=" + literal(item)) == "none"
                print("PASS reversal, delivery dedup and durable tombstone", flush=True)
        finally:
            call("/api/auth/logout", {})
        assert not cleanup_errors, cleanup_errors
    print("PASS gateway feedback acceptance", flush=True)


if __name__ == "__main__":
    main()
