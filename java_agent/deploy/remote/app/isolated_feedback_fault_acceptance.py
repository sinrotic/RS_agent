#!/usr/bin/env python3
"""用独立数据库、Redis、Recommend 容器验证 PENDING 恢复，不停止共享基础设施。"""
import json
import os
import re
import secrets
import subprocess
import tempfile
import shutil
import time
from pathlib import Path
from personalized_home_acceptance import http, fresh_profile


def run(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=60, **kwargs)


def root_sql(statement):
    return run(["docker", "exec", "-i", "rs-agent-java-mysql", "sh", "-c",
                'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N'], input=statement).stdout


def main():
    suffix = secrets.token_hex(5)
    database = "rs_home_acceptance_" + suffix
    redis_name = "rs-home-fault-redis-" + suffix
    service_name = "rs-home-fault-recommend-" + suffix
    assert re.fullmatch(r"rs_home_acceptance_[0-9a-f]{10}", database)
    root = Path("/home/luo/RS_agent_java")
    config = json.loads(run(["docker", "inspect", "rs-agent-java-service-recommend"]).stdout)[0]
    mysql_config = json.loads(run(["docker", "inspect", "rs-agent-java-mysql"]).stdout)[0]
    mysql_env = dict(entry.split("=", 1) for entry in mysql_config["Config"]["Env"])
    database_user = mysql_env["MYSQL_USER"]
    assert re.fullmatch(r"[a-zA-Z0-9_]+", database_user)
    env = dict(entry.split("=", 1) for entry in config["Config"]["Env"])
    report = {"database": database, "checks": []}
    env_path = None
    jar_path = None
    created_database = False

    def passed(name):
        print("PASS", name, flush=True)
        report["checks"].append(name)

    try:
        root_sql(f"CREATE DATABASE `{database}`; GRANT ALL PRIVILEGES ON `{database}`.* TO '{database_user}'@'%';")
        created_database = True
        root_sql(f"USE `{database}`; CREATE TABLE rs_schema_version (component VARCHAR(100) PRIMARY KEY, version VARCHAR(100), applied_at DATETIME(6));\n"
                 + (root / "sql/rs_service_recommend_schema.sql").read_text())
        redis_image = json.loads(run(["docker", "inspect", "rs-agent-java-redis"]).stdout)[0]["Config"]["Image"]
        run(["docker", "run", "-d", "--name", redis_name, "--network", "rs-agent-java_default", redis_image, "redis-server", "--save", "", "--appendonly", "no"])
        jdbc = re.sub(r"/rs_agent(?=[?]|$)", "/" + database, env["RS_RECOMMEND_FEEDBACK_JDBC_URL"])
        assert "/" + database in jdbc
        env.update({"SPRING_APPLICATION_NAME": "rs-home-fault-acceptance", "SERVER_PORT": "18103",
                    "SPRING_CLOUD_NACOS_DISCOVERY_ENABLED": "false", "SPRING_CLOUD_DISCOVERY_ENABLED": "false",
                    "SPRING_DATA_REDIS_HOST": redis_name, "SPRING_REDIS_HOST": redis_name,
                    "SPRING_DATA_REDIS_PASSWORD": "", "SPRING_REDIS_PASSWORD": "",
                    "SPRING_DATA_REDIS_TIMEOUT": "1s", "SPRING_DATA_REDIS_CONNECT_TIMEOUT": "1s",
                    "RS_RECOMMEND_FEEDBACK_JDBC_URL": jdbc, "SPRING_DATASOURCE_URL": jdbc,
                    "RS_MODEL_BASE_URL": "http://127.0.0.1:9",
                    "RS_RECOMMEND_FEEDBACK_OUTBOX_RETRY_DELAY": "1000", "JAVA_OPTS": "-Xms128m -Xmx384m"})
        with tempfile.NamedTemporaryFile(mode="w", prefix="rs-home-fault-", delete=False) as handle:
            env_path = Path(handle.name)
            os.chmod(env_path, 0o600)
            handle.write("\n".join(key + "=" + value for key, value in env.items()) + "\n")
        with tempfile.NamedTemporaryFile(prefix="rs-home-fault-", suffix=".jar", delete=False) as artifact:
            jar_path = Path(artifact.name)
        shutil.copyfile(root / "services/rs-service-recommend.jar", jar_path)
        run(["docker", "run", "-d", "--name", service_name, "--network", "rs-agent-java_default",
             "--env-file", str(env_path), "-p", "127.0.0.1:18133:18103",
             "-v", str(jar_path) + ":/app/rs-service-recommend.jar:ro", config["Config"]["Image"],
             "sh", "-c", "java $JAVA_OPTS -jar /app/rs-service-recommend.jar"])
        env_path.unlink()
        env_path = None
        base = "http://127.0.0.1:18133"
        for attempt in range(40):
            try:
                if http(base, "/actuator/health/readiness", timeout=2)["status"] == "UP":
                    break
            except Exception:
                pass
            time.sleep(2)
        else:
            raise AssertionError("隔离 Recommend 未就绪")
        identity = {"X-Account-Id": "fault-" + suffix, "X-Profile-User-Id": fresh_profile("Electronics")}
        sid = "fault-session-" + suffix
        page = http(base, "/api/recommend/home", {"session_id": sid, "scene": "home", "page_size": 6}, headers=identity)
        assert len(page["items"]) == 6 and page["recommendation_mode"] == "degraded"
        assert "model_rank_unavailable" in page["degradation_reasons"]
        assert "semantic_recall_unavailable" in page["degradation_reasons"]
        passed("模型连接故障时返回 Catalog 探索商品并明确标记降级")

        run(["docker", "stop", "-t", "1", redis_name])
        ack = http(base, "/api/recommend/feedback/event", {"session_id": sid, "request_id": page["request_id"],
                   "item_id": page["items"][0]["item_id"], "event_type": "dislike", "event_value": -1,
                   "occurred_at": int(time.time() * 1000)}, headers=identity)
        assert ack["accepted"] and ack["application_status"] == "PENDING", ack
        event_id = ack["feedback_id"]
        assert re.fullmatch(r"fb_evt_[a-zA-Z0-9-]+", event_id)
        state = root_sql(f"SELECT status FROM `{database}`.rs_recommend_feedback_outbox WHERE event_id='{event_id}';").strip()
        assert state == "PENDING", state
        passed("Redis 不可用时反馈已持久化，接口和 Outbox 均为 PENDING")

        run(["docker", "start", redis_name])
        started = time.monotonic()
        for attempt in range(40):
            status = http(base, "/api/recommend/feedback/status/" + event_id, headers=identity)
            if status["application_status"] == "APPLIED":
                break
            time.sleep(1)
        else:
            raise AssertionError("Redis 恢复后 Outbox 未应用")
        report["recovery_seconds"] = round(time.monotonic() - started, 2)
        refreshed = http(base, "/api/recommend/home", {"session_id": sid, "scene": "home", "page_size": 6,
                         "cursor": "rerank:" + page["request_id"]}, headers=identity)
        assert event_id in refreshed["applied_feedback_event_ids"]
        assert page["items"][0]["item_id"] not in {item["item_id"] for item in refreshed["items"]}
        passed("Redis 恢复后自动变为 APPLIED，下一次推荐过滤已踩商品")
    finally:
        for name in [service_name, redis_name]:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, timeout=45)
        if env_path:
            env_path.unlink(missing_ok=True)
        if jar_path:
            jar_path.unlink(missing_ok=True)
        if created_database:
            root_sql(f"REVOKE ALL PRIVILEGES ON `{database}`.* FROM '{database_user}'@'%'; DROP DATABASE `{database}`;")
        Path("isolated-feedback-fault-acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
