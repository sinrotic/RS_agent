"""购物质量评测与离线 Skill 自进化入口；仅新建产物，不修改线上运行配置。"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "python_agent"))

from rs_core.common.openai_compatible_client import OpenAICompatibleClient
from rs_core.online_evaluation.adapters import JsonModel
from rs_core.offline.evaluation.skill_benchmark.adapters import prepare_java_command
from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint, load_benchmark, validate_benchmark
from rs_core.offline.evaluation.skill_benchmark.quality_dataset import build_quality_benchmark, coverage_report
from rs_core.offline.evaluation.skill_benchmark.quality_review import (
    apply_quality_reviews, build_quality_calibration, build_quality_review, evaluate_quality_calibration,
)
from rs_core.offline.evaluation.skill_benchmark.evolution import evolve_skills
from rs_core.offline.evaluation.skill_benchmark.quality_evidence import evidence_pack, apply_use_evidence
from rs_core.offline.evaluation.skill_benchmark.runner import SubprocessAgent, run_benchmark
from rs_core.offline.evaluation.skill_benchmark.request_synthesis import synthesize_requests


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def configured_model(prefix):
    base_url, model = os.getenv(prefix + "_BASE_URL"), os.getenv(prefix + "_MODEL")
    if not base_url and not model:
        return None
    if not base_url or not model:
        raise ValueError(prefix + " 的模型和地址必须同时配置")
    endpoint = urlsplit(base_url)
    if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        raise ValueError("模型地址不得携带凭证或查询参数")
    client = OpenAICompatibleClient(base_url=base_url, api_key_env=prefix + "_API_KEY",
        timeout_seconds=60, allow_insecure_local_api_base=os.getenv(prefix + "_ALLOW_LOCAL_HTTP") == "true")
    client._validate_base_url()
    budget = int(os.getenv(prefix + "_MAX_TOKENS", "12000" if prefix == "RS_SKILL_OPT" else "2400"))
    adapter = JsonModel(client, model, max_tokens=budget)
    adapter.identity = fingerprint({"endpoint": base_url, "model": model, "temperature": 0,
                                    "max_tokens": budget, "response_format": "json_object"})
    return adapter


def run_configuration(path):
    config = read(path)
    allowed = {"model", "base_url", "temperature", "max_tokens", "seed", "task_timeout_seconds"}
    if not isinstance(config, dict) or set(config) - allowed or not config.get("model") or not config.get("base_url"):
        raise ValueError("运行配置必须显式指定 model/base_url，不能含凭证或工具变更")
    endpoint = urlsplit(config["base_url"])
    if (endpoint.scheme not in {"http", "https"} or not endpoint.hostname or endpoint.username
            or endpoint.password or endpoint.query or endpoint.fragment
            or endpoint.scheme == "http" and endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}):
        raise ValueError("远端模型使用无凭证 HTTPS；HTTP 仅限 loopback")
    return dict(config, adapter_kind="java_rs_agent_loop", transport="benchmark-openai-json/1")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export-skills", help="将指定内置推荐 Skill 复制为隔离基线，不修改原文件")
    export.add_argument("--names", nargs="+", default=["explicit-need-recommendation"])
    export.add_argument("--out", required=True)
    build = commands.add_parser("build", help="从冻结 v6 构建用途/画像质量契约与异常场景")
    build.add_argument("--source", required=True)
    build.add_argument("--out", required=True)
    cover = commands.add_parser("coverage", help="逐集合检查场景、用户与标签覆盖")
    cover.add_argument("--dataset", required=True)
    cover.add_argument("--out", required=True)
    synthesis = commands.add_parser("synthesize", help="分角色生成、盲提取与预审自然请求；默认不同模型，只生成候选包")
    synthesis.add_argument("--dataset", required=True)
    synthesis.add_argument("--splits", nargs="+", choices=["train", "dev"], default=["train", "dev"])
    synthesis.add_argument("--seed-limit", type=int, default=6)
    synthesis.add_argument("--variants", type=int, default=2)
    synthesis.add_argument("--max-calls", type=int, default=144)
    synthesis.add_argument("--out-dir", required=True)
    synthesis.add_argument("--allow-shared-model-preview", action="store_true",
                           help="显式允许同模型的隔离上下文预览；输出仍非gold，不能自动入正式题集")
    evidence = commands.add_parser("evidence-pack", help="导出独立用途规格/测量证据的待补录模板")
    evidence.add_argument("--dataset", required=True)
    evidence.add_argument("--out", required=True)
    enrich = commands.add_parser("apply-evidence", help="冻结经双人核实的独立用途事实，并使旧标签与校准失效")
    enrich.add_argument("--dataset", required=True)
    enrich.add_argument("--evidence", required=True)
    enrich.add_argument("--out", required=True)
    pack = commands.add_parser("label-pack", help="导出空白双人独立标注；测试材料须单独授权导出")
    pack.add_argument("--dataset", required=True)
    pack.add_argument("--splits", nargs="+", choices=["train", "dev", "test"], default=["train", "dev"])
    pack.add_argument("--limit", type=int, default=60)
    pack.add_argument("--include-test", action="store_true")
    pack.add_argument("--out", required=True)
    apply = commands.add_parser("apply-labels", help="合并多份独立审核包，另存带标签的新题集")
    apply.add_argument("--dataset", required=True)
    apply.add_argument("--reviews", nargs="+", required=True)
    apply.add_argument("--out", required=True)
    calibration = commands.add_parser("calibration-pack", help="从非测试真实运行导出盲审包及隔离评分键")
    calibration.add_argument("--dataset", required=True)
    calibration.add_argument("--run", required=True)
    calibration.add_argument("--limit", type=int, default=120)
    calibration.add_argument("--out-dir", required=True)
    check = commands.add_parser("calibration-check", help="检查独立人审与评分的一致性及错误放行")
    check.add_argument("--key", required=True)
    check.add_argument("--review", required=True)
    check.add_argument("--out", required=True)
    for command in ("run", "evolve"):
        sub = commands.add_parser(command, help="真实隔离 Agent 评测" if command == "run" else "有界生成、开发比较和隐藏测试验收")
        sub.add_argument("--dataset", required=True)
        sub.add_argument("--model-config", required=True)
        sub.add_argument("--skills", required=True)
        sub.add_argument("--java", default="java")
        sub.add_argument("--calibration-report")
        sub.add_argument("--quality-calibration")
        sub.add_argument("--repeats", type=int, default=3)
        if command == "run":
            sub.add_argument("--split", choices=["train", "dev", "test"], required=True)
            sub.add_argument("--out", required=True)
        else:
            sub.add_argument("--rounds", type=int, default=2)
            sub.add_argument("--candidates", type=int, default=2)
            sub.add_argument("--max-trials", type=int, default=20000)
            sub.add_argument("--holdout-registry", required=True, help="跨运行共享的隐藏测试占用登记目录")
            sub.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)
    destination = getattr(args, "out", None) or getattr(args, "out_dir", None)
    if destination and Path(destination).exists():
        raise ValueError("输出必须是新路径，拒绝覆盖或重复调用模型")
    if args.command == "export-skills":
        skills = {}
        directory = ROOT / "java_agent/rs-service-agent/src/main/resources/agent-skills"
        for name in args.names:
            if not re.fullmatch(r"[a-z0-9-]+", name) or name == "a2ui-interface":
                raise ValueError("仅导出已有推荐 Skill；a2ui-interface 含 Runtime 动态扩展，不能从源文件冒充完整基线")
            content = (directory / name / "SKILL.md").read_text(encoding="utf-8")
            description = re.search(r"^description:\s*(.+)$", content, re.MULTILINE)
            if not description:
                raise ValueError("Skill 源文件缺少 description")
            skills[name] = {"description": description.group(1), "content": content}
        write(args.out, skills)
    elif args.command == "build":
        value = build_quality_benchmark(load_benchmark(args.source))
        write(args.out, value)
        print(json.dumps(validate_benchmark(value), ensure_ascii=False))
    elif args.command == "coverage":
        write(args.out, coverage_report(load_benchmark(args.dataset)))
    elif args.command == "synthesize":
        benchmark = load_benchmark(args.dataset)
        generator, verifier = configured_model("RS_REQUEST_GEN"), configured_model("RS_REQUEST_VERIFY")
        if generator is None or verifier is None:
            raise ValueError("请单独配置RS_REQUEST_GEN与RS_REQUEST_VERIFY，不继承推荐模型或密钥")
        Path(args.out_dir).mkdir(parents=True, exist_ok=False)
        result = synthesize_requests(benchmark, generator, verifier, seed_limit=args.seed_limit,
            variants=args.variants, splits=tuple(args.splits), max_calls=args.max_calls,
            allow_shared_model_preview=args.allow_shared_model_preview,
            checkpoint=lambda row: write(Path(args.out_dir) / "checkpoints" / (row["candidate_id"] + ".json"), row))
        write(Path(args.out_dir) / "request-candidates.json", result)
        print(json.dumps({"summary": result["summary"], "human_reviewed": False,
                          "is_gold": False, "auto_deploy": False}, ensure_ascii=False))
    elif args.command == "evidence-pack":
        write(args.out, evidence_pack(load_benchmark(args.dataset)))
    elif args.command == "apply-evidence":
        write(args.out, apply_use_evidence(load_benchmark(args.dataset), read(args.evidence)))
    elif args.command == "label-pack":
        write(args.out, build_quality_review(load_benchmark(args.dataset), splits=tuple(args.splits),
              task_limit=args.limit, include_test=args.include_test))
    elif args.command == "apply-labels":
        write(args.out, apply_quality_reviews(load_benchmark(args.dataset), [read(path) for path in args.reviews]))
    elif args.command == "calibration-pack":
        result = build_quality_calibration(load_benchmark(args.dataset), read(args.run), limit=args.limit)
        Path(args.out_dir).mkdir(parents=True, exist_ok=False)
        write(Path(args.out_dir) / "blind-review.json", result["review"])
        write(Path(args.out_dir) / "private-scoring-key.json", result["scoring_key"])
    elif args.command == "calibration-check":
        write(args.out, evaluate_quality_calibration(read(args.key), read(args.review)))
    else:
        benchmark, config, skills = load_benchmark(args.dataset), run_configuration(args.model_config), read(args.skills)
        judge = configured_model("RS_QUALITY_JUDGE")
        structural = read(args.calibration_report) if args.calibration_report else None
        quality = read(args.quality_calibration) if args.quality_calibration else None
        # 构建本地命令不调用远端模型；未就绪的 evolve 将直接返回门槛报告。
        command = None
        def adapter(request):
            nonlocal command
            if command is None:
                command = prepare_java_command(ROOT, args.java)
            return SubprocessAgent(command, timeout=config.get("task_timeout_seconds", 180))(request)
        if args.command == "run":
            result = run_benchmark(benchmark, adapter, config, split=args.split, repeats=args.repeats,
                skills=skills, calibration_report=structural, quality_judge=judge, quality_calibration=quality)
            write(args.out, result)
        else:
            result = evolve_skills(benchmark, adapter, config, skills, configured_model("RS_SKILL_OPT"), judge=judge,
                calibration=structural, quality_calibration=quality, rounds=args.rounds,
                candidates_per_round=args.candidates, repeats=args.repeats, max_trials=args.max_trials,
                out_dir=args.out_dir, holdout_registry=args.holdout_registry)
        print(json.dumps({"status": result.get("status", "evaluated"), "blockers": result.get("blockers", []),
                          "auto_deploy": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
