"""模型直连基线之后补充真实最终回答回归；私有 payload 不进入报告。"""
import argparse
from pathlib import Path

from benchmark_core import main, measure, payload, metrics
from replay import append_replay
from steady import append_steady


if __name__ == "__main__":
    main()
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    append_replay(args.output, args.base_url)
    append_steady(args.output, args.base_url)
