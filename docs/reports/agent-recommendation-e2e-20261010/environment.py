"""真实业务验收环境；只写独立命名空间，并记录、恢复原容器状态。"""
import argparse
import json
import os
import re
import secrets
import subprocess
import time
from pathlib import Path

INFRA = ["rs-agent-java-mysql", "rs-agent-java-scylla", "rs-agent-java-milvus-etcd",
         "rs-agent-java-milvus-minio", "rs-agent-java-elasticsearch", "rs-agent-java-milvus-standalone"]
MODULES = {"catalog": ("rs-service-catalog", 18202), "model": ("rs-service-model", 18205),
           "user": ("rs-service-user", 18201), "trace": ("rs-service-platform-trace", 18208),
           "recommend-base": ("rs-service-recommend", 18203), "recommend-fast": ("rs-service-recommend", 18213),
           "agent-base": ("rs-service-agent", 18204), "agent-fast": ("rs-service-agent", 18214),
           "gateway": ("rs-api-gateway", 18288)}

def run(args, *, data=None, timeout=120):
    result = subprocess.run(args, input=data, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"command failed: {args[0:2]}: {result.stderr[-500:]}")
    return result.stdout.strip()

def inspect(name):
    return json.loads(run(["docker", "inspect", name]))[0]

def root_sql(text):
    return run(["docker", "exec", "-i", "rs-agent-java-mysql", "sh", "-c",
                'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -B'], data=text)

def original_env(module):
    source = "api-gateway" if module == "rs-api-gateway" else "service-" + module.removeprefix("rs-service-")
    return dict(value.split("=", 1) for value in inspect("rs-agent-java-" + source)["Config"]["Env"])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "services", "status", "cleanup"))
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not str(root).startswith("/tmp/rs-agent-e2e-20261010-"):
        raise ValueError("unexpected workspace")
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        "suffix": secrets.token_hex(4), "started_infra": [], "containers": []}
    prefix = "rs-e2e-" + state["suffix"] + "-"
    database = "rs_e2e_" + state["suffix"]
    assert re.fullmatch(r"rs_e2e_[0-9a-f]{8}", database)
    def save(): state_path.write_text(json.dumps(state, indent=2))
    save()
    if args.phase == "prepare":
        for name in INFRA:
            if not inspect(name)["State"]["Running"]:
                state["started_infra"].append(name); save()
                run(["docker", "start", name])
                print("started", name, flush=True)
        for _ in range(60):
            try:
                root_sql("SELECT 1;"); break
            except Exception: time.sleep(1)
        else: raise RuntimeError("MySQL not ready")
        credentials = root / "credentials.json"
        if not credentials.exists():
            password = secrets.token_urlsafe(32)
            root_sql(f"CREATE DATABASE `{database}`; CREATE USER '{database}'@'%' IDENTIFIED BY '{password}';"
                     f" GRANT ALL ON `{database}`.* TO '{database}'@'%'; GRANT SELECT ON rs_agent.* TO '{database}'@'%';")
            credentials.write_text(json.dumps({"user": database, "password": password})); credentials.chmod(0o600)
            state["database"] = database; save()
            schema = "\n".join((root / name).read_text() for name in (
                "rs_service_user_schema.sql", "rs_service_recommend_schema.sql",
                "rs_service_agent_mysql_projection_schema.sql", "rs_agent_session_projection_upgrade.sql"))
            root_sql(f"USE `{database}`;\n" + schema)
            owned = set(root_sql(f"SHOW TABLES FROM `{database}`;").splitlines())
            originals = root_sql("SHOW TABLES FROM rs_agent;").splitlines()
            for table in originals:
                if table not in owned:
                    assert re.fullmatch(r"\w+", table)
                    root_sql(f"CREATE SQL SECURITY INVOKER VIEW `{database}`.`{table}` AS SELECT * FROM rs_agent.`{table}`;")
            print("isolated mysql tables/views", len(owned), len(originals), flush=True)
        cql = (root / "rs_service_agent_scylla_session_schema.cql").read_text().replace("rs_agent", database)
        for _ in range(90):
            try:
                run(["docker", "exec", "-i", "rs-agent-java-scylla", "cqlsh"], data=cql, timeout=10)
                state["keyspace"] = database; save(); break
            except Exception: time.sleep(1)
        else: raise RuntimeError("Scylla not ready")
        if "redis" not in state:
            name = prefix + "redis"
            state["containers"].append(name); save()
            image = inspect("rs-agent-java-redis")["Config"]["Image"]
            run(["docker", "run", "-d", "--name", name, "--network", "host", image,
                 "redis-server", "--bind", "127.0.0.1", "--port", "18279", "--save", "", "--appendonly", "no",
                 "--maxmemory", "256mb", "--maxmemory-policy", "allkeys-lru"])
            state["redis"] = name; save()
        print("PREPARED", flush=True)
    elif args.phase == "services":
        creds = json.loads((root / "credentials.json").read_text())
        for label, (module, port) in MODULES.items():
            if label in state: continue
            env = original_env(module)
            jdbc = f"jdbc:mysql://127.0.0.1:13306/{database}?useUnicode=true&characterEncoding=utf8&useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai"
            env.update({"SERVER_PORT": str(port), "SERVER_ADDRESS": "127.0.0.1", "JAVA_OPTS": "-Xms128m -Xmx768m",
                "SPRING_APPLICATION_NAME": prefix + label, "SPRING_CLOUD_NACOS_DISCOVERY_ENABLED": "false",
                "SPRING_CLOUD_DISCOVERY_ENABLED": "false", "SPRING_DATASOURCE_URL": jdbc,
                "SPRING_DATASOURCE_USERNAME": creds["user"], "SPRING_DATASOURCE_PASSWORD": creds["password"],
                "SPRING_DATA_REDIS_HOST": "127.0.0.1", "SPRING_DATA_REDIS_PORT": "18279", "SPRING_DATA_REDIS_PASSWORD": "",
                "SPRING_REDIS_HOST": "127.0.0.1", "SPRING_REDIS_PORT": "18279", "SPRING_REDIS_PASSWORD": "",
                "RS_MYSQL_JDBC_URL": jdbc, "RS_MYSQL_USER": creds["user"], "RS_MYSQL_PASSWORD": creds["password"],
                "RS_SCYLLA_HOST": "127.0.0.1", "RS_SCYLLA_PORT": "19042", "RS_SCYLLA_KEYSPACE": database,
                "RS_AGENT_SESSION_PERSISTENCE_ENABLED": "true", "RS_AGENT_SESSION_LIFECYCLE_ENABLED": "true",
                "RS_AGENT_RECOMMENDATION_TYPE": "http", "RS_AGENT_SESSION_STORE_TYPE": "redis",
                "RS_AGENT_PERFORMANCE_OBSERVATION_ENABLED": "true", "RS_RECOMMEND_PERFORMANCE_OBSERVATION_ENABLED": "true",
                "RS_CATALOG_BASE_URL": "http://127.0.0.1:18202", "RS_MODEL_BASE_URL": "http://127.0.0.1:18205",
                "RS_USER_SERVICE_URL": "http://127.0.0.1:18201", "RS_PLATFORM_TRACE_SERVICE_URL": "http://127.0.0.1:18208",
                "RS_RECOMMEND_BASE_URL": "http://127.0.0.1:18213", "RS_RECOMMEND_SERVICE_URL": "http://127.0.0.1:18213",
                "RS_AGENT_RECOMMENDATION_BASE_URL": "http://127.0.0.1:18213",
                "RS_MODEL_RUNTIME_EMBEDDING_BASE_URL": "http://127.0.0.1:18215", "RS_MODEL_RUNTIME_RERANK_BASE_URL": "http://127.0.0.1:18215",
                "RS_ELASTICSEARCH_BASE_URL": "http://127.0.0.1:19200", "RS_ELASTICSEARCH_URI": "http://127.0.0.1:19200",
                "RS_MILVUS_BASE_URL": "http://127.0.0.1:19530", "RS_RECOMMEND_TRAINED_RANKING_ENABLED": "true",
                "RS_RECOMMEND_TRAINED_RANKING_BASE_URL": "http://172.21.0.1:18119",
                "RS_RECOMMEND_MULTI_RECALL_ENABLED": "true", "RS_RECOMMEND_MULTI_RECALL_BASE_URL": "http://172.21.0.1:18118",
                "RS_RECOMMEND_FEEDBACK_PERSISTENCE": "jdbc", "RS_RECOMMEND_FEEDBACK_PROJECTION": "redis",
                "RS_RECOMMEND_FEEDBACK_JDBC_URL": jdbc, "RS_RECOMMEND_FEEDBACK_JDBC_USERNAME": creds["user"],
                "RS_RECOMMEND_FEEDBACK_JDBC_PASSWORD": creds["password"],
                "RS_AGENT_OPENAI_BASE_URL": "http://127.0.0.1:18082/v1", "RS_AGENT_OPENAI_MODEL": "qwen35-4b",
                "RS_AGENT_API_KEY": "local-test", "RS_AGENT_CONSTRAINED_DECODING_ENABLED": "true",
                "RS_AGENT_OPENAI_TEMPERATURE": "0.1", "RS_AGENT_OPENAI_MAX_TOKENS": "1200",
                "RS_AGENT_DIRECT_RECOMMENDATION_ENABLED": "true" if label == "agent-fast" else "false",
                "RS_AGENT_CATALOG_CURRENCY": "", "RS_RECOMMEND_INFERENCE_CACHE_EMBEDDING_VERSION": "bge_m3_fp16_e2e_v1" if label == "recommend-fast" else "",
                "RS_RECOMMEND_INFERENCE_CACHE_RERANKER_VERSION": "bge_reranker_fp16_e2e_v1" if label == "recommend-fast" else ""})
            if label == "agent-base":
                for key in ("RS_RECOMMEND_BASE_URL", "RS_RECOMMEND_SERVICE_URL", "RS_AGENT_RECOMMENDATION_BASE_URL"):
                    env[key] = "http://127.0.0.1:18203"
            if label == "gateway":
                env["RS_GATEWAY_MAX_REQUESTS_PER_MINUTE"] = "2000"
                routes = [("agent-base", 18204, ["Path=/api/agent/**", "Header=X-E2E-Route,baseline"]),
                    ("agent-fast", 18214, ["Path=/api/agent/**"]), ("auth", 18201, ["Path=/api/auth/**"]),
                    ("user", 18201, ["Path=/api/users/**,/api/sessions/**"]),
                    ("catalog", 18202, ["Path=/api/catalog/**"]), ("recommend", 18213, ["Path=/api/recommend/**"]),
                    ("trace", 18208, ["Path=/api/platform/**"])]
                for index, (route, destination, predicates) in enumerate(routes):
                    key = f"SPRING_CLOUD_GATEWAY_SERVER_WEBFLUX_ROUTES_{index}_"
                    env[key + "ID"] = route; env[key + "URI"] = "http://127.0.0.1:" + str(destination)
                    for number, predicate in enumerate(predicates): env[key + f"PREDICATES_{number}"] = predicate
            env_file = root / (label + ".env")
            env_file.write_text("\n".join(key + "=" + value for key, value in env.items())); env_file.chmod(0o600)
            name = prefix + label
            state["containers"].append(name); save()
            run(["docker", "run", "-d", "--name", name, "--network", "host", "--env-file", str(env_file),
                 "-v", str(root / (module + ".jar")) + ":/app/service.jar:ro", "eclipse-temurin:21-jre",
                 "sh", "-c", "exec java $JAVA_OPTS -jar /app/service.jar"])
            env_file.unlink(); state[label] = name; save()
            print("started isolated", label, port, flush=True)
    elif args.phase == "status":
        for name in state["containers"]:
            print(name, inspect(name)["State"]["Status"])
    elif args.phase == "cleanup":
        for name in reversed(state["containers"]):
            if not name.startswith(prefix): raise ValueError("cleanup owner mismatch")
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
        if state.get("keyspace"):
            run(["docker", "exec", "-i", "rs-agent-java-scylla", "cqlsh"], data=f"DROP KEYSPACE IF EXISTS {database};")
        if state.get("database"):
            root_sql(f"DROP DATABASE IF EXISTS `{database}`; DROP USER IF EXISTS '{database}'@'%';")
        for name in reversed(state["started_infra"]):
            run(["docker", "stop", "--time", "30", name])
        for file in root.glob("*.env"): file.unlink()
        (root / "credentials.json").unlink(missing_ok=True)
        state["cleaned"] = True; save(); print("CLEANED", flush=True)

if __name__ == "__main__": main()
