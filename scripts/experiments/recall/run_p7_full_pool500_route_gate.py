from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.workflow.pool500_route_gate import (
    DEFAULT_BASELINE_CONFIG,
    DEFAULT_MAIN_ROUTE_DIR,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PHASE_CONFIG,
    run_p7_route_gate,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run P7 full pool500 recall-only route gate.")
    parser.add_argument("--main-route-dir", default=str(DEFAULT_MAIN_ROUTE_DIR))
    parser.add_argument("--phase-config", default=str(DEFAULT_PHASE_CONFIG))
    parser.add_argument("--baseline-config", default=str(DEFAULT_BASELINE_CONFIG))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--candidate-quality-audit", default=None)
    parser.add_argument("--pool500-candidates", default=None)
    parser.add_argument("--skip-venv-check", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = run_p7_route_gate(
        main_route_dir=Path(args.main_route_dir),
        phase_config_path=Path(args.phase_config),
        baseline_config_path=Path(args.baseline_config),
        output_dir=Path(args.output_dir),
        candidate_quality_audit_path=Path(args.candidate_quality_audit) if args.candidate_quality_audit else None,
        pool500_candidates_path=Path(args.pool500_candidates) if args.pool500_candidates else None,
        enforce_venv=not args.skip_venv_check,
        overwrite=args.overwrite,
    )
    print(json.dumps({"status": manifest["status"], "decision": manifest["decision"], "manifest_path": manifest["required_artifacts"]["manifest"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
