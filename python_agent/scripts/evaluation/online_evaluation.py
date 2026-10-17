"""在线评价 worker、审核包和候选 Skill overlay 的本地管理入口。"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rs_core.offline.evaluation.skill_benchmark.dataset import load_benchmark
from rs_core.online_evaluation.app import configured_evaluation
from rs_core.online_evaluation.bridge import improvement_jobs, reviewed_benchmarks


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    worker = commands.add_parser("work", help="有界处理持久队列；可由外部调度器重复调用")
    worker.add_argument("--limit", type=int, default=10)
    review = commands.add_parser("review-pack", help="导出待审核需求、评分与事实快照")
    review.add_argument("--out", required=True)
    jobs = commands.add_parser("improvement-jobs", help="输出候选 overlay 及离线验证任务，绝不上线")
    jobs.add_argument("--baseline", required=True)
    jobs.add_argument("--out", required=True)
    replay = commands.add_parser("reviewed-replays", help="将已授权、人工填写 gold 的案例导出为补充基准")
    replay.add_argument("--review", required=True)
    replay.add_argument("--baseline", required=True)
    replay.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    if args.command == "reviewed-replays":
        pack = json.loads(Path(args.review).read_text(encoding="utf-8"))
        datasets = reviewed_benchmarks(pack, load_benchmark(args.baseline))
        destination = Path(args.out_dir)
        if destination.exists():
            raise ValueError("补充题集输出目录必须是新目录")
        for dataset in datasets:
            write_new(destination / (dataset["tasks"][0]["task_id"] + ".json"), dataset)
        print(json.dumps({"exported": len(datasets), "auto_deploy": False}))
        return
    module = configured_evaluation()
    if args.command == "work":
        if not 1 <= args.limit <= 100:
            raise ValueError("worker limit 必须为 1..100")
        processed, errors = 0, 0
        for _ in range(args.limit):
            report = module.process_one()
            if report is None:
                break
            processed += 1
            errors += "evaluation_error" in report
        print(json.dumps({"processed": processed, "errors": errors, "auto_deploy": False}))
    elif args.command == "review-pack":
        write_new(args.out, module.review_pack())
    else:
        write_new(args.out, improvement_jobs(module.candidates(), load_benchmark(args.baseline)))


if __name__ == "__main__":
    main()
