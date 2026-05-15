from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_phase_c_ranking_actionability_diagnostic import (
    BASELINE_CONFIG,
    CURRENT_RECALL_MAINLINE_CONFIG,
    CURRENT_RECALL_MAINLINE_ID,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SEED,
    ONLINE_METRIC_NAMES,
    build_method_specs,
    main,
    parse_args,
    run_phase_c_ranking_actionability,
    run_phase_c_ranking_actionability_diagnostic,
    run_phase_6_industrial_ranking_chain,
    _run_baseline,
    _run_id,
)


if __name__ == "__main__":
    main()
