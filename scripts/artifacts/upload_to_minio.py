from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.artifacts.manifest import (  # noqa: E402
    apply_artifact_store_patch,
    build_artifact_store_patch,
    find_local_artifact_path,
    read_manifest,
    uploaded_timestamp,
    write_manifest,
)
from rs_core.artifacts.resolver import resolve_artifact  # noqa: E402


def read_inventory(path: str | Path) -> list[Path]:
    inventory_path = Path(path)
    text = inventory_path.read_text(encoding="utf-8")
    if inventory_path.suffix.lower() == ".json":
        payload = json.loads(text)
    else:
        payload = yaml.safe_load(text)
    raw_items = payload.get("artifacts") if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        raise ValueError("Inventory must be a list or a mapping with artifacts")
    result: list[Path] = []
    for item in raw_items:
        if isinstance(item, str):
            result.append(Path(item))
        elif isinstance(item, dict) and item.get("manifest"):
            result.append(Path(str(item["manifest"])))
        else:
            raise ValueError("Inventory items must be manifest paths or {manifest: path}")
    return result


def build_planned_patch(
    manifest_path: str | Path,
    *,
    bucket: str,
    object_name: str | None = None,
    cache_policy: str = "local_trial_cache",
) -> dict[str, Any]:
    manifest = read_manifest(manifest_path)
    local_path = find_local_artifact_path(manifest)
    chosen_object = object_name or f"{manifest.get('artifact_id', Path(manifest_path).stem)}/{Path(local_path or manifest_path).name}"
    return build_artifact_store_patch(
        manifest,
        local_path=local_path,
        bucket=bucket,
        object_name=chosen_object,
        cache_policy=cache_policy,
        uploaded_at=None,
        compute_hash=True,
    )


def process_manifest(
    manifest_path: str | Path,
    *,
    endpoint: str | None,
    bucket: str,
    access_key: str | None,
    secret_key: str | None,
    secure: bool,
    dry_run: bool,
    upload: bool,
    verify: bool,
    client: Any | None = None,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    manifest = read_manifest(manifest_path)
    patch = build_planned_patch(manifest_path, bucket=bucket)
    planned = {"manifest": str(manifest_path), "patch": patch}
    if dry_run or not upload:
        return planned
    local_path = patch["artifact_store"].get("local_path")
    minio_uri = patch["artifact_store"].get("minio_uri")
    if not local_path:
        raise ValueError(f"Manifest has no local artifact path: {manifest_path}")
    remote_client = client or _build_minio_client(endpoint, access_key, secret_key, secure)
    object_name = str(minio_uri).split(f"minio://{bucket}/", 1)[1]
    remote_client.fput_object(bucket, object_name, local_path)
    patch["artifact_store"]["uploaded_at"] = uploaded_timestamp()
    updated = apply_artifact_store_patch(manifest, patch)
    write_manifest(manifest_path, updated)
    planned["patch"] = patch
    planned["uploaded"] = True
    if verify:
        planned["verify"] = resolve_artifact(
            minio_uri,
            cache_dir=Path(".cache") / "rs_artifacts_verify",
            sha256=patch["artifact_store"].get("sha256"),
            size_bytes=patch["artifact_store"].get("size_bytes"),
            client=remote_client,
        ).diagnostics
    return planned


def process_inputs(args: argparse.Namespace, *, client: Any | None = None) -> list[dict[str, Any]]:
    manifest_paths: list[Path] = []
    if args.manifest:
        manifest_paths.append(Path(args.manifest))
    if args.inventory:
        manifest_paths.extend(read_inventory(args.inventory))
    if not manifest_paths:
        raise ValueError("Provide --manifest or --inventory")
    access_key = os.environ.get(args.access_key_env) if args.access_key_env else None
    secret_key = os.environ.get(args.secret_key_env) if args.secret_key_env else None
    return [
        process_manifest(
            path,
            endpoint=args.endpoint,
            bucket=args.bucket,
            access_key=access_key,
            secret_key=secret_key,
            secure=args.secure,
            dry_run=args.dry_run,
            upload=args.upload,
            verify=args.verify,
            client=client,
        )
        for path in manifest_paths
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan or upload local/trial artifacts to MinIO from manifests.")
    parser.add_argument("--manifest", help="Single artifact manifest path")
    parser.add_argument("--inventory", help="JSON/YAML list of manifest paths or {artifacts: [...]} inventory")
    parser.add_argument("--dry-run", action="store_true", help="Only print planned artifact_store patches; no network")
    parser.add_argument("--upload", action="store_true", help="Upload local artifact and update manifest")
    parser.add_argument("--verify", action="store_true", help="Resolve uploaded artifact through MinIO client after upload")
    parser.add_argument("--endpoint", default=os.environ.get("RS_MINIO_ENDPOINT"))
    parser.add_argument("--bucket", default=os.environ.get("RS_MINIO_BUCKET", "rs-artifacts-local"))
    parser.add_argument("--access-key-env", default="RS_MINIO_ACCESS_KEY")
    parser.add_argument("--secret-key-env", default="RS_MINIO_SECRET_KEY")
    parser.add_argument("--secure", action="store_true", default=os.environ.get("RS_MINIO_SECURE", "0") == "1")
    return parser


def main(argv: list[str] | None = None) -> list[dict[str, Any]]:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.dry_run and not args.upload:
        args.dry_run = True
    result = process_inputs(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _build_minio_client(endpoint: str | None, access_key: str | None, secret_key: str | None, secure: bool) -> Any:
    if not endpoint:
        raise RuntimeError("MinIO endpoint is required for upload")
    if not access_key or not secret_key:
        raise RuntimeError("MinIO credentials are required for upload")
    try:
        from minio import Minio
    except ImportError as exc:
        raise RuntimeError("MinIO SDK is not installed; install optional dependency rs-agent[artifacts]") from exc
    return Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)


if __name__ == "__main__":
    main()
