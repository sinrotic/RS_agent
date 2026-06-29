from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TYPE_EXPORT = """export * from '../types';\n"""
PUBLIC_TYPE_MARKERS = (
    "export interface StartSessionRequest",
    "export interface ChatRequest",
    "export interface FeedbackRequest",
    "export interface RagQueryRequest",
    "export interface RecommendFromSequenceRequest",
    "export interface RecallRequest",
    "export interface RankRequest",
    "export interface SessionExportResponse",
)
SNAPSHOT_PATHS = (
    "dic/architecture/RS_AGENT_ONLINE_SERVICE_OPENAPI_SNAPSHOT.json",
    "dic/architecture/RS_AGENT_AGENT_SERVICE_OPENAPI_SNAPSHOT.json",
)
FORBIDDEN_FRONTEND_TYPE_MARKERS = (
    "oracle",
    "holdout",
    "label_binary",
    "ground_truth",
    "training_samples",
    "diagnostics_path",
    "score_trace",
    "agent_tool_trace",
)


def main() -> int:
    target = PROJECT_ROOT / "frontend/src/types/index.ts"
    source = PROJECT_ROOT / "frontend" / "src" / "types.ts"
    source_text = source.read_text(encoding="utf-8")
    missing_markers = [marker for marker in PUBLIC_TYPE_MARKERS if marker not in source_text]
    forbidden_markers = [marker for marker in FORBIDDEN_FRONTEND_TYPE_MARKERS if marker in source_text.lower()]
    missing_snapshots = [path for path in SNAPSHOT_PATHS if not (PROJECT_ROOT / path).exists()]

    if missing_markers or forbidden_markers or missing_snapshots:
        if missing_markers:
            print(f"missing public type markers: {missing_markers}")
        if forbidden_markers:
            print(f"forbidden frontend type markers: {forbidden_markers}")
        if missing_snapshots:
            print(f"missing service OpenAPI snapshots: {missing_snapshots}")
        return 1

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(TYPE_EXPORT, encoding="utf-8")
    print(f"generated {target.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
