from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.offline.training.sft_judge import SftJudgePolicy, judge_jsonl_file


PROJECT_ROOT = ROOT
DEFAULT_INPUT = "outputs/training/multi_turn_sft_gpt53/samples.jsonl"
DEFAULT_OUTPUT = "outputs/training/multi_turn_sft_gpt53/judge_reports.jsonl"
DEFAULT_SUMMARY = "outputs/training/multi_turn_sft_gpt53/judge_summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Judge RS Agent SFT samples with the project SFT quality rubric.")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Input JSONL containing rs_agent_multi_turn_sft_sample_v1 or rs_agent_sft_sample_v1 records.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output JSONL for per-sample judge reports.")
    parser.add_argument("--summary", default=DEFAULT_SUMMARY, help="Output JSON summary for judge aggregate metrics.")
    parser.add_argument("--limit", type=int, default=None, help="Optional max samples for local smoke checks.")
    parser.add_argument("--allow-accept-light", action="store_true", help="Treat accept_light as satisfactory for exploratory data review.")
    parser.add_argument("--no-fail", action="store_true", help="Print judge results without returning a non-zero exit code when samples are unsatisfactory.")
    return parser.parse_args()


def _safe_project_path(raw_path: str, *, root: Path = PROJECT_ROOT) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        raise ValueError(f"absolute paths are not allowed: {raw_path}")
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes project root: {raw_path}") from exc
    return resolved


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    policy = SftJudgePolicy(require_accept_decision_for_satisfaction=not args.allow_accept_light)
    summary = judge_jsonl_file(
        _safe_project_path(args.input),
        output_path=_safe_project_path(args.output),
        summary_path=_safe_project_path(args.summary),
        max_samples=args.limit,
        policy=policy,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.no_fail and not summary.get("judge_satisfied"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
