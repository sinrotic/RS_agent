"""冻结本地代码/配置证据；不读取凭证，不把部署模板当作运行中实例。"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
SAFE_CONFIG_KEYS = (
    "RS_AGENT_OPENAI_MODEL", "RS_AGENT_RECOMMENDATION_TYPE", "RS_AGENT_SESSION_STORE_TYPE",
    "RS_AGENT_SESSION_PERSISTENCE_ENABLED", "RS_AGENT_TRACE_ENABLED",
    "RS_AGENT_CONSTRAINED_DECODING_ENABLED", "RS_AGENT_MAX_ACTIVE_LOOPS",
    "RS_AGENT_MAX_MODEL_STREAMS", "RS_AGENT_MAX_RECOMMENDATION_CALLS", "RS_AGENT_MAX_TOOL_CALLS",
    "RS_AGENT_MAX_SESSION_QUEUE_SIZE", "RS_RECOMMEND_TWO_TOWER_ENABLED",
    "RS_RECOMMEND_TWO_TOWER_MODEL_KEY", "RS_RECOMMEND_TWO_TOWER_COLLECTION",
    "RS_RECOMMEND_TWO_TOWER_DIMENSION", "RS_RECOMMEND_TWO_TOWER_PRIMARY_SHARE",
    "RS_RECOMMEND_TWO_TOWER_PROTECTED_HEAD_COUNT", "RS_RECOMMEND_QUERY_TOWER_ENABLED",
    "RS_RECOMMEND_MULTI_RECALL_ENABLED", "RS_RECOMMEND_TRAINED_RANKING_ENABLED",
)


def build_manifest(root=ROOT):
    root = Path(root)
    paths = [
        "java_agent/rs-service-agent/src/main/resources/application.yml",
        "java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/config/AgentTemplateProperties.java",
        "java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentRuntimeConfigurationService.java",
        "java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/SpringAiChatResponseMapper.java",
        "java_agent/rs-service-recommend/src/test/java/com/sinrotic/rs/recommend/service/FrozenAgentBaselineTest.java",
        "python_agent/rs_core/offline/evaluation/skill_benchmark/execution_metrics.py",
        "java_agent/deploy/remote/app/docker-compose.yml",
        "java_agent/deploy/remote/app/.env.example",
        "java_agent/deploy/remote/app/product-three-tower-final.env.example",
        "java_agent/deploy/remote/app/agent-gpu1-concurrency.env.example",
        "docs/reports/product-three-tower-final/RESULTS.txt",
        "artifacts/models/product_three_tower_final_v1/manifest.json",
        "python_agent/benchmarks/skill_benchmark/agent-baseline-v1.json",
    ]
    paths += sorted(path.relative_to(root).as_posix() for path in
                    (root / "java_agent/rs-service-agent/src/main/resources/agent-skills").glob("*/SKILL.md"))
    files = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in paths}
    presets = {}
    for name in paths:
        if not name.endswith(".env.example"):
            continue
        # 只解析受版本控制的示例；不读取 .env，也不枚举当前进程环境。
        values = {}
        for line in (root / name).read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() in SAFE_CONFIG_KEYS:
                values[key.strip()] = value.strip()
        presets[name] = values
    config = yaml.safe_load((root / paths[0]).read_text(encoding="utf-8"))
    agent = config["rs"]["agent"]
    selected_defaults = {key: agent[key] for key in ("recommendation", "session-store", "execution")}
    # recommendation 含服务地址，但本报告只需要类型；不扩大允许输出的字段。
    selected_defaults["recommendation"] = {"type": agent["recommendation"]["type"]}
    return {
        "schema_version": "rs-agent-baseline-manifest/1",
        "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "snapshot_kind": "working_tree_files_identified_by_sha256",
        "file_sha256": files, "repository_defaults": selected_defaults, "versioned_presets": presets,
        "runtime_probe": {"status": "not_performed", "reason": "本轮未连接远程实例核验，不由模板推断当前生效配置"},
        "model_route_evidence": {
            "model_key": "product_three_tower_final_v1", "dimension": 1024,
            "basis": "docs/reports/product-three-tower-final/RESULTS.txt",
            "status": "historical_deployment_report_not_live_probe",
        },
        "product_path": "Java Agent → Java Recommend/Catalog；Python 模型服务、仿真、评测和训练",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build_manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
