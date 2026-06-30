from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_lab.experiments.ranking.run_phase_c_ranking_actionability_diagnostic import main


if __name__ == "__main__":
    main()
