"""构建/审核/执行/比较隔离 Skill 评测。所有写入均为显式指定的新评测产物。"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "python_agent"))

from rs_core.offline.evaluation.skill_benchmark.adapters import prepare_java_command
from rs_core.offline.evaluation.skill_benchmark.dataset import (
    build_benchmark,
    load_benchmark,
    validate_benchmark,
)
from rs_core.offline.evaluation.skill_benchmark.runner import (
    SubprocessAgent,
    compare_runs,
    run_benchmark,
    compare_profile_ablation,
)
from rs_core.offline.evaluation.skill_benchmark.personalized import build_personalized_benchmark
from rs_core.offline.evaluation.skill_benchmark.population import prepare_population
from rs_core.offline.evaluation.skill_benchmark.customer_dataset import build_customer_benchmark
from rs_core.offline.evaluation.skill_benchmark.profile_dataset import (
    build_profile_contrast_benchmark,
)
from rs_core.offline.evaluation.skill_benchmark.contrast_examples import build_contrast_examples
from rs_core.offline.evaluation.skill_benchmark.natural_dataset import build_natural_benchmark
from rs_core.offline.evaluation.skill_benchmark.natural_examples import build_natural_examples
from rs_core.offline.evaluation.skill_benchmark.relevance_review import (
    build_relevance_review,
    apply_relevance_review,
)
from rs_core.offline.evaluation.skill_benchmark.readiness import (
    strengthen_benchmark,
    build_calibration_bundle,
    evaluate_calibration,
    audit_benchmark,
)


def _write(path, value):
    destination = Path(path)
    if destination.exists():
        raise ValueError(f"输出文件已存在，请换新路径：{destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8"
    )


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="隔离 Skill 评测：真实商品种子、公式评分、Java Agent 与候选版本对比"
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--source", action="append", required=True)
    build.add_argument("--catalog-limit", type=int, default=200)
    build.add_argument("--max-scan-rows", type=int, default=10000)
    build.add_argument("--family-limit", type=int, default=10)
    build.add_argument("--currency", default="SOURCE_UNIT")
    build.add_argument("--out", required=True)
    personalized = subparsers.add_parser(
        "build-personalized", help="真实画像绑定、中上热度分层随机抽样"
    )
    personalized.add_argument("--source", action="append", required=True)
    personalized.add_argument("--history", required=True)
    personalized.add_argument("--targets", action="append", required=True)
    personalized.add_argument("--seed", type=int, default=42)
    personalized.add_argument("--lower-quantile", type=float, default=0.6)
    personalized.add_argument("--upper-quantile", type=float, default=0.9)
    personalized.add_argument("--family-limit", type=int, default=20)
    personalized.add_argument("--catalog-limit", type=int, default=300)
    personalized.add_argument("--currency", default="SOURCE_UNIT")
    personalized.add_argument("--out", required=True)
    personalized.add_argument(
        "--population", help="prepare-population 生成的 population.json，禁止在小快照上重新计算热度"
    )
    population = subparsers.add_parser(
        "prepare-population", help="全量过去热度统计与资源受限画像快照"
    )
    population.add_argument("--history", required=True)
    population.add_argument("--targets", action="append", required=True)
    population.add_argument("--out-dir", required=True)
    population.add_argument("--seed", type=int, default=42)
    population.add_argument("--candidate-user-limit", type=int, default=1500)
    population.add_argument("--min-user-positive", type=int, default=5)
    population.add_argument("--min-item-interactions", type=int, default=5)
    strengthen = subparsers.add_parser("strengthen", help="增加画像压力任务并要求评分校准")
    strengthen.add_argument("--dataset", required=True)
    strengthen.add_argument("--out", required=True)
    customer = subparsers.add_parser("customerize", help="按顾客意图、信息缺口与弱历史参考重建任务")
    customer.add_argument("--dataset", required=True)
    customer.add_argument("--out", required=True)
    contrasts = subparsers.add_parser(
        "profile-contrasts", help="修正有证据的错标，增加真实画像同需求对照任务"
    )
    contrasts.add_argument("--dataset", required=True, help="保留真实目标绑定的 v3 来源")
    contrasts.add_argument("--out", required=True)
    natural = subparsers.add_parser(
        "naturalize", help="自然购物画像、环境权限与可选澄清 v6；保留旧版"
    )
    natural.add_argument("--dataset", required=True, help="冻结 v5 或保留真实目标绑定的 v3")
    natural.add_argument("--out", required=True)
    natural_examples = subparsers.add_parser(
        "natural-examples", help="非测试集自然画像对照及分层得分"
    )
    natural_examples.add_argument("--dataset", required=True)
    natural_examples.add_argument("--limit", type=int, default=3)
    natural_examples.add_argument("--out", required=True)
    relevance = subparsers.add_parser(
        "relevance-pack", help="生成空白独立相关性人审模板，不自动标注"
    )
    relevance.add_argument("--dataset", required=True)
    relevance.add_argument("--tasks", type=int, default=40)
    relevance.add_argument("--out", required=True)
    relevance_apply = subparsers.add_parser(
        "relevance-apply", help="显式导入已批准人审标签，生成新题集"
    )
    relevance_apply.add_argument("--dataset", required=True)
    relevance_apply.add_argument("--review", required=True)
    relevance_apply.add_argument("--out", required=True)
    examples = subparsers.add_parser(
        "contrast-examples", help="输出非测试集画像对照与公式得分；不是模型成绩"
    )
    examples.add_argument("--dataset", required=True)
    examples.add_argument("--limit", type=int, default=3)
    examples.add_argument("--out", required=True)
    calibration = subparsers.add_parser("calibration-pack", help="生成非测试集盲审材料和分离公式键")
    calibration.add_argument("--dataset", required=True)
    calibration.add_argument("--pairs", type=int, default=60)
    calibration.add_argument("--out-dir", required=True)
    calibration_check = subparsers.add_parser(
        "calibration-check", help="检查独立人审标签与公式一致性"
    )
    calibration_check.add_argument("--key", required=True)
    calibration_check.add_argument("--labels", required=True)
    calibration_check.add_argument("--out", required=True)
    audit = subparsers.add_parser("audit", help="数据规模、参考路径和评分就绪检查；不运行真实模型")
    audit.add_argument("--dataset", required=True)
    audit.add_argument("--calibration-report")
    audit.add_argument("--out", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--dataset", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--dataset", required=True)
    run.add_argument("--split", choices=["train", "dev", "test"], required=True)
    run.add_argument("--repeats", type=int, default=1)
    run.add_argument(
        "--model-config",
        required=True,
        help="非敏感 JSON：model/base_url/temperature/max_tokens/seed",
    )
    run.add_argument("--java", default="java")
    run.add_argument(
        "--skill-overlay", help="JSON 对象：skill_name -> {description, content}；只在隔离进程应用"
    )
    run.add_argument("--out", required=True)
    run.add_argument("--calibration-report", help="对应冻结数据与当前评分器的人工校准收据")
    run.add_argument("--profile-visibility", choices=["visible", "hidden"], default="visible")
    ablation = subparsers.add_parser(
        "compare-profile", help="同 Skill 画像消融；无独立标签不输出质量增益"
    )
    ablation.add_argument("--hidden", required=True)
    ablation.add_argument("--visible", required=True)
    ablation.add_argument("--out", required=True)
    compare = subparsers.add_parser("compare")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--candidate", required=True)
    compare.add_argument("--out", required=True)
    check = subparsers.add_parser(
        "self-check", help="真实 Java Loop + 受控外部模型，仅验证工程正确性"
    )
    check.add_argument("--java", default="java")
    check.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.action == "build":
        result = build_benchmark(
            args.source,
            catalog_limit=args.catalog_limit,
            max_scan_rows=args.max_scan_rows,
            currency=args.currency,
            family_limit=args.family_limit,
        )
        _write(args.out, result)
        print(json.dumps(validate_benchmark(result), ensure_ascii=False))
    elif args.action == "build-personalized":
        if Path(args.out).exists():
            raise ValueError("输出已存在，拒绝扫描和覆盖；请指定新路径")
        result = build_personalized_benchmark(
            args.source,
            args.history,
            args.targets,
            seed=args.seed,
            lower_quantile=args.lower_quantile,
            upper_quantile=args.upper_quantile,
            family_limit=args.family_limit,
            catalog_limit=args.catalog_limit,
            currency=args.currency,
            population_snapshot=json.loads(Path(args.population).read_text(encoding="utf-8"))
            if args.population
            else None,
        )
        _write(args.out, result)
        print(json.dumps(validate_benchmark(result), ensure_ascii=False))
    elif args.action == "prepare-population":
        result = prepare_population(
            args.history,
            args.targets,
            args.out_dir,
            seed=args.seed,
            candidate_user_limit=args.candidate_user_limit,
            min_user_positive=args.min_user_positive,
            min_item_interactions=args.min_item_interactions,
            progress=lambda event: print(
                json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True
            ),
        )
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in (
                        "past_users",
                        "past_items",
                        "eligible_user_population",
                        "eligible_item_population",
                        "user_count_bounds",
                        "item_count_bounds",
                    )
                },
                ensure_ascii=False,
            )
        )
    elif args.action == "strengthen":
        result = strengthen_benchmark(load_benchmark(args.dataset))
        _write(args.out, result)
        print(json.dumps(validate_benchmark(result), ensure_ascii=False))
    elif args.action == "customerize":
        if Path(args.out).exists():
            raise ValueError("输出已存在，顾客版本必须写入新文件")
        result = build_customer_benchmark(load_benchmark(args.dataset))
        _write(args.out, result)
        print(json.dumps(validate_benchmark(result), ensure_ascii=False))
    elif args.action in {"naturalize", "natural-examples", "relevance-pack", "relevance-apply"}:
        if Path(args.out).exists():
            raise ValueError("自然购物与标注产物必须写入新文件，不覆盖已冻结版本")
        benchmark = load_benchmark(args.dataset)
        if args.action == "naturalize":
            result = build_natural_benchmark(benchmark)
        elif args.action == "natural-examples":
            result = build_natural_examples(benchmark, limit=args.limit)
        elif args.action == "relevance-pack":
            result = build_relevance_review(benchmark, task_limit=args.tasks)
        else:
            result = apply_relevance_review(
                benchmark, json.loads(Path(args.review).read_text(encoding="utf-8"))
            )
        _write(args.out, result)
        print(
            json.dumps(
                validate_benchmark(result)
                if "tasks" in result
                else {
                    "origin": result.get("origin"),
                    "entries": len(result.get("entries", [])),
                    "examples": len(result.get("examples", [])),
                },
                ensure_ascii=False,
            )
        )
    elif args.action == "compare-profile":
        result = compare_profile_ablation(
            json.loads(Path(args.hidden).read_text(encoding="utf-8")),
            json.loads(Path(args.visible).read_text(encoding="utf-8")),
        )
        _write(args.out, result)
        print(json.dumps(result, ensure_ascii=False))
    elif args.action == "calibration-pack":
        destination = Path(args.out_dir)
        if destination.exists():
            raise ValueError("校准输出目录已存在，拒绝覆盖")
        result = build_calibration_bundle(load_benchmark(args.dataset), pair_limit=args.pairs)
        for name, value in (
            ("review-queue.json", result["review_queue"]),
            ("scoring-key.json", result["scoring_key"]),
            ("labels.json", result["labels_template"]),
        ):
            _write(destination / name, value)
        (destination / "blind-review.md").write_text(result["review_markdown"], encoding="utf-8")
        print(
            json.dumps(
                {"pairs": len(result["review_queue"]["pairs"]), "status": "pending_human_labels"}
            )
        )
    elif args.action == "profile-contrasts":
        if Path(args.out).exists():
            raise ValueError("画像对照版本必须写入新文件，不能覆盖已冻结题集")
        result = build_profile_contrast_benchmark(load_benchmark(args.dataset))
        _write(args.out, result)
        print(json.dumps(validate_benchmark(result), ensure_ascii=False))
    elif args.action == "contrast-examples":
        result = build_contrast_examples(load_benchmark(args.dataset), limit=args.limit)
        _write(args.out, result)
        print(
            json.dumps(
                {"groups": len(result["examples"]), "origin": result["origin"]}, ensure_ascii=False
            )
        )
    elif args.action == "calibration-check":
        result = evaluate_calibration(
            json.loads(Path(args.key).read_text(encoding="utf-8")),
            json.loads(Path(args.labels).read_text(encoding="utf-8")),
        )
        _write(args.out, result)
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in (
                        "passed",
                        "reviewed_pairs",
                        "reviewed_families",
                        "agreement",
                        "blockers",
                    )
                },
                ensure_ascii=False,
            )
        )
    elif args.action == "audit":
        result = audit_benchmark(
            load_benchmark(args.dataset),
            json.loads(Path(args.calibration_report).read_text(encoding="utf-8"))
            if args.calibration_report
            else None,
        )
        _write(args.out, result)
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in (
                        "summary",
                        "independent_users_per_split",
                        "ready_for_baseline_diagnostics",
                        "readiness_blockers",
                    )
                },
                ensure_ascii=False,
            )
        )
    elif args.action == "validate":
        print(json.dumps(validate_benchmark(load_benchmark(args.dataset)), ensure_ascii=False))
    elif args.action == "run":
        if Path(args.out).exists():
            raise ValueError("输出已存在，不执行模型调用；请使用新的 --out")
        config = json.loads(Path(args.model_config).read_text(encoding="utf-8"))
        allowed = {"model", "base_url", "temperature", "max_tokens", "seed", "task_timeout_seconds"}
        if not config.get("model") or not config.get("base_url") or set(config) - allowed:
            raise ValueError("模型配置缺少 model/base_url 或包含未支持字段/密钥")
        from urllib.parse import urlsplit

        endpoint = urlsplit(config["base_url"])
        if (
            endpoint.scheme not in {"http", "https"}
            or not endpoint.hostname
            or endpoint.username
            or endpoint.query
        ):
            raise ValueError("模型地址必须为不带凭据/查询参数的 HTTP(S) 地址，包含 /v1 路径")
        command = prepare_java_command(ROOT, args.java)
        config["adapter_kind"] = "java_rs_agent_loop"
        config["transport"] = "benchmark-openai-json/1"
        overlays = (
            json.loads(Path(args.skill_overlay).read_text(encoding="utf-8"))
            if args.skill_overlay
            else {}
        )
        if not isinstance(overlays, dict) or any(
            not isinstance(skill.get("content"), str)
            or not isinstance(skill.get("description"), str)
            for skill in overlays.values()
        ):
            raise ValueError("Skill overlay 必须包含字符串 description/content")
        result = run_benchmark(
            load_benchmark(args.dataset),
            SubprocessAgent(command, timeout=config.get("task_timeout_seconds", 180)),
            config,
            split=args.split,
            repeats=args.repeats,
            skills=overlays,
            calibration_report=json.loads(Path(args.calibration_report).read_text(encoding="utf-8"))
            if args.calibration_report
            else None,
            profile_visibility=args.profile_visibility,
        )
        _write(args.out, result)
        print(json.dumps(result["summary"], ensure_ascii=False))
    elif args.action == "self-check":
        if Path(args.out).exists():
            raise ValueError("输出文件已存在，请指定新路径")
        from rs_core.offline.evaluation.skill_benchmark.engineering import run_java_selfcheck

        result = run_java_selfcheck(prepare_java_command(ROOT, args.java))
        _write(args.out, result)
        print(
            json.dumps(
                {
                    "purpose": result["purpose"],
                    "baseline": result["baseline"]["summary"],
                    "candidate": result["candidate"]["summary"],
                    "comparison": result["comparison"],
                },
                ensure_ascii=False,
            )
        )
    else:
        result = compare_runs(
            json.loads(Path(args.baseline).read_text(encoding="utf-8")),
            json.loads(Path(args.candidate).read_text(encoding="utf-8")),
        )
        _write(args.out, result)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
