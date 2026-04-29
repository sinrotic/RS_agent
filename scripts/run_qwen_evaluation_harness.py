from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.workflow.hybrid_demo import run_qwen_evaluation_harness

DEFAULT_CONFIG = ROOT / "configs/hybrid_demo_small.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic/rule/Qwen rerank evaluation comparison.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to hybrid demo config.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick run.")
    parser.add_argument("--feedback", default="I prefer Audio and bluetooth", help="Feedback text applied to rule and Qwen modes.")
    parser.add_argument("--output-dir", default=None, help="Optional output directory for comparison artifacts.")
    parser.add_argument("--qwen-model-id", default=None, help="Local Qwen model path or cached model id for inference.")
    parser.add_argument("--qwen-max-new-tokens", type=int, default=None, help="Override Qwen max_new_tokens for rerank JSON generation.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_qwen_evaluation_harness(
        args.config,
        limit_users=args.limit_users,
        feedback_text=args.feedback,
        output_dir=args.output_dir,
        qwen_model_id=args.qwen_model_id,
        qwen_max_new_tokens=args.qwen_max_new_tokens,
    )
    print(f"Comparison JSON written to: {result['comparison_path']}")
    print(f"Comparison report written to: {result['report_path']}")


if __name__ == "__main__":
    main()
