"""汇总冻结场景的漂移检查结果；输入是实际复核记录，标签由独立标注提供。"""

import argparse
import json
from pathlib import Path

from rs_core.offline.evaluation.drift_evaluation import summarize_drift_reviews


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    scenarios = json.loads(args.scenarios.read_text(encoding="utf-8"))["scenarios"]
    reviews = [json.loads(line) for line in args.reviews.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = summarize_drift_reviews(scenarios, reviews)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
