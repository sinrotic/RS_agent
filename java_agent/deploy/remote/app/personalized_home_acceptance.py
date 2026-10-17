#!/usr/bin/env python3
"""部署主机上的真实个性化验收。创建专用账号，结束时撤销反馈并登出。"""
import concurrent.futures
import json
import math
import secrets
import time
import urllib.request
from pathlib import Path
from feedback_acceptance import sql, literal


def http(base, path, data=None, token=None, headers=None, timeout=90):
    headers = {"Content-Type": "application/json", **(headers or {})}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(base + path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        return json.loads(body) if body else {}


def fresh_profile(category):
    profiles = sql("""
        SELECT DISTINCT r.user_id FROM
          (SELECT user_id FROM amazon_reviews_base WHERE category = (%s COLLATE utf8mb4_unicode_ci) AND rating >= 4 LIMIT 1000) r
        WHERE NOT EXISTS (SELECT 1 FROM rs_account_profile_binding b WHERE BINARY b.profile_user_id = BINARY r.user_id)
          AND NOT EXISTS (SELECT 1 FROM rs_recommend_feedback_event f WHERE BINARY f.profile_user_id = BINARY r.user_id)
        LIMIT 1
    """ % literal(category))
    assert profiles, "该类别前 1000 条评论中没有空闲验收画像"
    return profiles


def main():
    base = "http://127.0.0.1:18088"
    accounts = []
    reversals = []
    report = {"checks": [], "latency_ms": [], "profiles": []}

    def passed(name):
        report["checks"].append(name)
        print("PASS", name, flush=True)

    def feed(account, cursor=""):
        started = time.monotonic()
        result = http(base, "/api/recommend/home", {"session_id": account["session"], "scene": "home", "page_size": 6, "cursor": cursor}, account["token"])
        report["latency_ms"].append(round((time.monotonic() - started) * 1000, 1))
        assert len(result["items"]) == 6, result
        assert not result.get("degradation_reasons"), result.get("degradation_reasons")
        assert len({item["item_id"] for item in result["items"]}) == 6
        return result

    try:
        first_pages = []
        for category in ["Electronics", "Office_Products"]:
            profile = fresh_profile(category)
            auth = http(base, "/api/auth/register", {"username": "personalized_" + secrets.token_hex(8),
                        "password": secrets.token_urlsafe(24), "nickname": "个性化验收", "bindStrategy": "selected", "profileUserId": profile})
            account = {"token": auth["accessToken"], "profile": profile}
            accounts.append(account)
            account["session"] = http(base, "/api/sessions", {"entryScene": "home-acceptance"}, account["token"])["sessionId"]
            page = feed(account)
            assert page["recommendation_mode"] == "personalized", page
            assert any("profile_semantic" in item["source_tags"] for item in page["items"])
            assert all("bge_reranker" in item["source_tags"] for item in page["items"])
            assert page["config"]["fine_rank_size"] > 6
            coverage = len({item["display"]["category"] for item in page["items"]})
            assert coverage >= 2, "首屏应至少覆盖两个候选类目"
            first_pages.append(page)
            report["profiles"].append({"profile": profile, "category": category, "first_page": page, "category_coverage": coverage})
        ids = lambda page: {item["item_id"] for item in page["items"]}
        assert ids(first_pages[0]) != ids(first_pages[1])
        report["cross_profile_overlap"] = len(ids(first_pages[0]) & ids(first_pages[1])) / 6
        passed("两个真实画像均经过语义召回和 BGE 排序，首屏不同且包含多个类目")

        account = accounts[0]
        previous = first_pages[0]
        seen = set(ids(previous))
        for _ in range(2):
            previous = feed(account, previous["next_cursor"])
            assert seen.isdisjoint(ids(previous)), "换批重复了已交付商品"
            seen.update(ids(previous))
        report["three_page_unique_items"] = len(seen)
        assert len(seen) == 18
        passed("连续三批共 18 个不重复商品")

        liked = next((item for item in previous["items"] if "catalog_exploration" in item["source_tags"]), previous["items"][0])
        event = {"request_id": previous["request_id"], "session_id": account["session"], "item_id": liked["item_id"],
                 "event_type": "like", "event_value": 1, "occurred_at": int(time.time() * 1000)}
        ack = http(base, "/api/recommend/feedback/event", event, account["token"])
        reversals.append((account, ack["feedback_id"]))
        assert ack["application_status"] == "APPLIED"
        duplicate = http(base, "/api/recommend/feedback/event", event, account["token"])
        assert duplicate["duplicate"] and duplicate["feedback_id"] == ack["feedback_id"]
        changed = feed(account, "similar:" + previous["request_id"])
        assert changed["preference_version"] >= ack["preference_version"]
        assert ack["feedback_id"] in changed["applied_feedback_event_ids"]
        assert seen.isdisjoint(ids(changed))
        assert any(any(tag.startswith("feedback_") for tag in item["source_tags"]) for item in changed["items"]), changed
        # Catalog 的同类天线可能分别标为手机配件、家庭音响、GPS；不能只按类目字符串判断相关性。
        # final score 至多包含 0.25 偏好加分，>= 0.9 保证模型原始相关分至少为 0.65。
        related = sum(item["display"]["category"] == liked["display"]["category"]
                      or ("feedback_semantic" in item["source_tags"] and item["score"] >= .9)
                      for item in changed["items"])
        assert related >= 3, {"liked_category": liked["display"]["category"], "result": changed}
        report["feedback_relevance_matches"] = related
        report["feedback"] = {"liked": liked, "next_page": changed}
        passed("喜欢后重新召回相似商品、偏好版本可见、反馈重试幂等")

        account["session"] = http(base, "/api/sessions", {"entryScene": "cross-session-acceptance"}, account["token"])["sessionId"]
        new_session_page = feed(account)
        assert (seen | ids(changed)).isdisjoint(ids(new_session_page))
        passed("重新创建会话后仍排除近期已交付商品")

        # 有限并发，使用两个专用画像，不改变任何真实用户反馈。
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(feed, [accounts[0], accounts[1]] * 3))
        assert all(len(result["items"]) == 6 for result in results)
        for offset in [0, 1]:
            simultaneous_seen = set()
            for result in results[offset::2]:
                assert simultaneous_seen.isdisjoint(ids(result)), "同画像并发换批出现重复交付"
                simultaneous_seen.update(ids(result))
        durations = sorted(report["latency_ms"])
        report["p95_ms"] = durations[math.ceil(len(durations) * .95) - 1]
        report["max_concurrency"] = 2
        assert report["p95_ms"] < 30000, report["p95_ms"]
        passed("双并发六次推荐成功，记录实测 P95（非容量上限）")
    finally:
        cleanup_errors = []
        for account, eid in reversed(reversals):
            try:
                assert http(base, "/api/recommend/feedback/reversal", {"feedback_event_id": eid}, account["token"])["accepted"]
            except Exception as error:
                cleanup_errors.append(str(error))
        for account in accounts:
            try:
                http(base, "/api/auth/logout", {}, account["token"])
            except Exception as error:
                cleanup_errors.append(str(error))
        report["cleanup_errors"] = cleanup_errors
        Path("personalized-home-acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        assert not cleanup_errors, cleanup_errors


if __name__ == "__main__":
    main()
