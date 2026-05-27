from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import read_json, write_json
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "pool500_itemcf_method_dataset_source_adapter_v1"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "recall" / "pool500_method_sources" / "itemcf_formal_from_method_dataset_v1"
VALID_SOURCES = {"itemcf_weak", "itemcf_strong"}
FORBIDDEN_PATH_TOKENS = {"holdout", "valid", "test", "lopo", "oracle", "eval_label"}
SHARD_KEY = "src_item_sha256_mod"


def build_itemcf_source_from_method_dataset(
    *,
    source: str,
    method_dataset_manifest_path: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    method_dataset_rows_path: Path | None = None,
    limit_rows: int | None = None,
    shard_count: int = 1,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        enforce_project_venv(ROOT)
    if source not in VALID_SOURCES:
        raise ValueError(f"unsupported ItemCF source: {source!r}")
    if limit_rows is not None and limit_rows <= 0:
        raise ValueError("limit_rows must be positive when provided")
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")

    method_dataset_manifest_path = method_dataset_manifest_path.resolve()
    _reject_forbidden_path(method_dataset_manifest_path)
    method_dataset_manifest = read_json(method_dataset_manifest_path)
    method_dataset_rows_path = (method_dataset_rows_path or _default_rows_path(method_dataset_manifest_path, method_dataset_manifest)).resolve()
    _reject_forbidden_path(method_dataset_rows_path)
    if not method_dataset_rows_path.is_file():
        raise FileNotFoundError(str(method_dataset_rows_path))

    manifest_source = method_dataset_manifest.get("source") or method_dataset_manifest.get("canonical_source")
    if manifest_source and manifest_source != source:
        raise ValueError(f"method dataset source mismatch: {manifest_source!r} != {source!r}")

    run_id = run_id or _default_run_id(source, limit_rows, shard_count)
    output_dir = (output_root / source / run_id).resolve()
    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"Output directory already exists: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    if shard_count == 1:
        conversion = _write_single_edges(
            source=source,
            input_path=method_dataset_rows_path,
            output_dir=output_dir,
            limit_rows=limit_rows,
        )
    else:
        conversion = _write_sharded_edges(
            source=source,
            input_path=method_dataset_rows_path,
            output_dir=output_dir,
            limit_rows=limit_rows,
            shard_count=shard_count,
        )

    manifest_signature = _file_signature(method_dataset_manifest_path)
    rows_signature = _file_signature(method_dataset_rows_path)
    source_index_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source": source,
        "canonical_source": source,
        "source_status": "DIAGNOSTIC_ONLY",
        "diagnostic_only": True,
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": method_dataset_manifest.get("train_only", True) is not False,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(output_dir),
        "edges_path": conversion["edges_path"],
        "row_count": conversion["row_count"],
        "edge_count": conversion["row_count"],
        "sharded": shard_count > 1,
        "shard_count": shard_count,
        "shard_key": SHARD_KEY if shard_count > 1 else None,
        "edges_shards": conversion.get("edges_shards", []),
        "edge_shard_stats": conversion.get("edge_shard_stats", []),
        "schema": {
            "input": "method_dataset_rows.jsonl",
            "output": "item_pair_edges_jsonl",
            "field_mapping": {
                "src_item_id": "src_item",
                "dst_item_id": "dst_item",
                "itemcf_score": "score",
                "edge_rank": "rank",
            },
        },
        "diagnostic_boundary": {
            "label_usage": "none_in_candidate_generation",
            "post_hoc_label_diagnostic_only": True,
            "forbidden_inputs": sorted(FORBIDDEN_PATH_TOKENS),
        },
        "input": {
            "method_dataset_manifest_path": str(method_dataset_manifest_path),
            "method_dataset_rows_path": str(method_dataset_rows_path),
            "method_dataset_manifest_sha256": manifest_signature["sha256"],
            "method_dataset_rows_sha256": rows_signature["sha256"],
            "declared_manifest_row_count": method_dataset_manifest.get("row_count")
            or method_dataset_manifest.get("candidate_row_count")
            or method_dataset_manifest.get("edge_count"),
            "limit_rows": limit_rows,
        },
        "edge_signature": conversion.get("edge_signature"),
        "outputs": {
            "source_index_manifest": str(output_dir / "source_index_manifest.json"),
            **({"edges_path": conversion["edges_path"]} if conversion["edges_path"] else {}),
            **({"edges_shards": conversion["edges_shards"], "edge_shard_stats": conversion["edge_shard_stats"]} if shard_count > 1 else {}),
        },
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "runtime_seconds": round(perf_counter() - started, 6),
    }
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    return source_index_manifest


def _default_rows_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    for section_name in ("outputs", "output_files", "required_artifacts"):
        section = manifest.get(section_name)
        if isinstance(section, dict):
            for key in ("method_dataset_rows", "rows", "dataset_rows"):
                value = section.get(key)
                if value:
                    return _resolve_path(manifest_path, value)
    for key in ("method_dataset_rows_path", "rows_path", "dataset_rows_path"):
        value = manifest.get(key)
        if value:
            return _resolve_path(manifest_path, value)
    return manifest_path.parent / "method_dataset_rows.jsonl"


def _resolve_path(manifest_path: Path, value: Any) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    manifest_relative = manifest_path.parent / path
    return manifest_relative if manifest_relative.exists() else ROOT / path


def _write_single_edges(*, source: str, input_path: Path, output_dir: Path, limit_rows: int | None) -> dict[str, Any]:
    edges_path = output_dir / f"{source}_edges.jsonl"
    row_count = 0
    with input_path.open("r", encoding="utf-8") as input_handle, edges_path.open("w", encoding="utf-8") as output_handle:
        for line_number, line in enumerate(input_handle, start=1):
            edge = _edge_from_line(source, input_path, line_number, line, row_count)
            if edge is None:
                continue
            output_handle.write(json.dumps(edge, ensure_ascii=False) + "\n")
            row_count += 1
            if limit_rows is not None and row_count >= limit_rows:
                break
    return {"edges_path": str(edges_path), "row_count": row_count, "edge_signature": _file_signature(edges_path)}


def _write_sharded_edges(*, source: str, input_path: Path, output_dir: Path, limit_rows: int | None, shard_count: int) -> dict[str, Any]:
    shards_dir = output_dir / "edges_shards"
    shards_dir.mkdir()
    shard_paths = [shards_dir / f"{source}_edges_shard_{shard_id:05d}.jsonl" for shard_id in range(shard_count)]
    handles = [path.open("w", encoding="utf-8") for path in shard_paths]
    shard_row_counts = [0] * shard_count
    row_count = 0
    try:
        with input_path.open("r", encoding="utf-8") as input_handle:
            for line_number, line in enumerate(input_handle, start=1):
                edge = _edge_from_line(source, input_path, line_number, line, row_count)
                if edge is None:
                    continue
                shard_id = stable_itemcf_shard_id(str(edge["src_item"]), shard_count)
                handles[shard_id].write(json.dumps(edge, ensure_ascii=False) + "\n")
                shard_row_counts[shard_id] += 1
                row_count += 1
                if limit_rows is not None and row_count >= limit_rows:
                    break
    finally:
        for handle in handles:
            handle.close()

    edge_shard_stats = []
    for shard_id, path in enumerate(shard_paths):
        signature = _file_signature(path)
        edge_shard_stats.append(
            {
                "shard_id": shard_id,
                "path": str(path),
                "row_count": shard_row_counts[shard_id],
                "edge_count": shard_row_counts[shard_id],
                "signature": signature,
            }
        )
    return {
        "edges_path": None,
        "row_count": row_count,
        "edges_shards": [str(path) for path in shard_paths],
        "edge_shard_stats": edge_shard_stats,
    }


def _edge_from_line(source: str, input_path: Path, line_number: int, line: str, fallback_rank: int) -> dict[str, Any] | None:
    line = line.strip()
    if not line:
        return None
    row = json.loads(line)
    src_item = str(row.get("src_item_id") or "")
    dst_item = str(row.get("dst_item_id") or "")
    if not src_item or not dst_item:
        raise ValueError(f"missing src_item_id or dst_item_id in row {line_number}: {input_path}")
    try:
        score = float(row.get("itemcf_score", 0.0) or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid itemcf_score in row {line_number}: {input_path}") from exc
    return {
        "source": source,
        "src_item": src_item,
        "dst_item": dst_item,
        "score": score,
        "rank": int(row.get("edge_rank", fallback_rank + 1) or fallback_rank + 1),
        "metadata": {
            key: value
            for key, value in row.items()
            if key not in {"src_item_id", "dst_item_id", "itemcf_score", "edge_rank"}
        },
    }


def stable_itemcf_shard_id(src_item: str, shard_count: int) -> int:
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    digest = hashlib.sha256(src_item.encode("utf-8")).hexdigest()[:16]
    return int(digest, 16) % shard_count


def _file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    row_count = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            row_count += chunk.count(b"\n")
    return {"path": str(path), "sha256": digest.hexdigest(), "size_bytes": path.stat().st_size, "row_count": row_count}


def _reject_forbidden_path(path: Path) -> None:
    lowered_parts = {part.lower() for part in path.parts}
    if lowered_parts & FORBIDDEN_PATH_TOKENS:
        raise ValueError(f"Forbidden label/eval path for source adapter: {path}")


def _default_run_id(source: str, limit_rows: int | None, shard_count: int) -> str:
    suffix = f"limit{limit_rows}" if limit_rows is not None else "full"
    if shard_count > 1:
        suffix = f"{suffix}_shards{shard_count}"
    return f"{source}_{suffix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert formal ItemCF method_dataset rows into pool500 ItemCF edge source.")
    parser.add_argument("--source", required=True, choices=sorted(VALID_SOURCES))
    parser.add_argument("--method-dataset-manifest", required=True)
    parser.add_argument("--method-dataset-rows")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--limit-rows", type=int)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_itemcf_source_from_method_dataset(
        source=args.source,
        method_dataset_manifest_path=Path(args.method_dataset_manifest),
        method_dataset_rows_path=Path(args.method_dataset_rows) if args.method_dataset_rows else None,
        output_root=Path(args.output_root),
        run_id=args.run_id,
        limit_rows=args.limit_rows,
        shard_count=args.shard_count,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({"source_index_manifest": manifest["outputs"]["source_index_manifest"], "row_count": manifest["row_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
