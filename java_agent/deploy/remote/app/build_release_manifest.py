#!/usr/bin/env python3
"""记录当前源码与部署产物的 SHA-256；只读工作区，不提交文件，不收集 .env。"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

EXCLUDED = {"node_modules", "target", "dist", ".git", "logs", "data", "db", "__pycache__"}
SOURCE_SUFFIXES = {".java", ".xml", ".ts", ".tsx", ".json", ".css", ".html", ".yml", ".yaml", ".sql", ".cql", ".py", ".sh", ".ps1", ".conf", ".md", ".mjs"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_manifest(root: Path) -> dict[str, str]:
    files = {}
    for path in sorted((root / "java_agent").rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(part in EXCLUDED for part in relative.parts):
            continue
        if path.name.startswith(".env") or path.suffix not in SOURCE_SUFFIXES:
            continue
        files[relative.as_posix()] = sha256(path)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, action="append", default=[])
    args = parser.parse_args()
    root = args.root.resolve()
    source = source_manifest(root)
    artifacts = {}
    for supplied in args.artifact:
        path = supplied.resolve()
        if not path.is_file() or not path.is_relative_to(root):
            parser.error("artifact must be an existing workspace file")
        artifacts[path.relative_to(root).as_posix()] = sha256(path)
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "git_head": result.stdout.strip(),
              "source_tree_sha256": hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest(),
              "source_files": source, "artifacts": artifacts,
              "scope": "current_java_working_tree_including_uncommitted_sources; excludes_runtime_secrets"}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"release manifest: {len(source)} sources, {len(artifacts)} artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
