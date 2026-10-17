#!/usr/bin/env python3
"""将已构建的服务、前端及部署配置打包，记录工作区源码和产物哈希；不发布、不收集运行密钥。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

from build_release_manifest import sha256, source_manifest

SERVICES = (
    "rs-api-gateway", "rs-service-user", "rs-service-catalog", "rs-service-recommend",
    "rs-service-agent", "rs-service-model", "rs-service-platform-trace", "rs-service-inventory",
    "rs-service-order", "rs-service-promotion", "rs-service-payment", "rs-service-seckill",
)


def release_files(root: Path) -> dict[str, Path]:
    java = root / "java_agent"
    files = {}
    for service in SERVICES:
        target = java / service / "target"
        jar = target / f"{service}-exec.jar"
        if not jar.is_file():
            jar = target / f"{service}.jar"
        with zipfile.ZipFile(jar) as archive:
            if not any(name.startswith("BOOT-INF/classes/") for name in archive.namelist()):
                raise ValueError(f"service must be an executable Spring Boot JAR: {service}")
        files[f"services/{service}.jar"] = jar
    dist = java / "frontend/dist"
    if not (dist / "index.html").is_file() or not list((dist / "assets").glob("*.js")):
        raise ValueError("build frontend before preparing a release")
    for path in sorted(dist.rglob("*")):
        if path.is_file():
            files[f"frontend_deploy/dist/{path.relative_to(dist).as_posix()}"] = path
    for folder, destination in (("app", "app_deploy"), ("infra", "infra"), ("frontend", "frontend_deploy"), ("ops", "ops"), ("model", "model_deploy")):
        source = java / "deploy/remote" / folder
        for path in sorted(source.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.name.startswith(".env") and path.name != ".env.example":
                continue
            if path.suffix not in {".py", ".sh", ".mjs", ".yml", ".yaml", ".conf", ".md"} and path.name != ".env.example":
                continue
            files[f"{destination}/{path.relative_to(source).as_posix()}"] = path
    for path in sorted((java / "sql").glob("*")):
        if path.is_file() and path.suffix in {".sql", ".cql"}:
            files[f"sql/{path.name}"] = path
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output_dir.resolve()
    if not output.is_relative_to(root):
        parser.error("output-dir must be inside the workspace")
    output.mkdir(parents=True, exist_ok=True)
    package = output / "service-release.zip"
    if package.exists():
        parser.error("release already exists; use a new output directory")
    files = release_files(root)
    source = source_manifest(root)
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "git_head": git.stdout.strip(),
                "source_tree_sha256": hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest(),
                "source_files": source, "artifacts": {name: sha256(path) for name, path in files.items()},
                "scope": "current_java_working_tree_including_uncommitted_sources; not_deployed; runtime_secrets_excluded",
                "deployment_mode": "recommend_by_default; full_commerce_requires_explicit_configuration"}
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    temporary = output / "service-release.zip.tmp"
    try:
        with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
            for name, path in sorted(files.items()):
                archive.write(path, name, compress_type=zipfile.ZIP_STORED if name.endswith(".jar") else zipfile.ZIP_DEFLATED)
            archive.writestr("release-manifest.json", rendered, compress_type=zipfile.ZIP_DEFLATED)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError("release archive verification failed")
        temporary.rename(package)
    finally:
        if temporary.exists():
            temporary.unlink()
    (output / "release-manifest.json").write_text(rendered, encoding="utf-8")
    digest = sha256(package)
    (output / "SHA256SUMS").write_text(f"{digest}  {package.name}\n", encoding="utf-8")
    print(json.dumps({"package": str(package), "files": len(files), "sha256": digest,
                      "size_mib": round(package.stat().st_size / 1024**2, 1), "deployed": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
