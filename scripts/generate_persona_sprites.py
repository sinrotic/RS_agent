from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "frontend" / "src" / "assets" / "persona-sprites" / "manifest.json"
DEFAULT_OUTPUT_DIR = DEFAULT_MANIFEST.parent / "generated"
DEFAULT_MODEL = "gpt-image-2"
DEFAULT_SIZE = "1024x1024"
API_KEY_ENV_NAMES = ("OPENAI_API_KEY", "OPENAI_IMAGES_API_KEY", "OPENAI_IMAGE_API_KEY")
API_BASE_ENV_NAMES = ("OPENAI_IMAGES_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE")


class SpriteConfigError(ValueError):
    pass


@dataclass(frozen=True)
class PersonaSprite:
    persona_id: str
    prompt: str
    output_name: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate local PNG persona pixel sprites from the frontend persona sprite "
            "manifest. This script is isolated from recommendation decision code."
        )
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Path to persona sprite manifest JSON.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where generated PNG files will be written.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenAI Images API model name.")
    parser.add_argument("--size", default=DEFAULT_SIZE, help="Image size passed to the Images API.")
    parser.add_argument(
        "--model-config",
        default="",
        help="Optional JSON config containing api_base/api_key and optional image_model/model.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate manifest prompts and list planned outputs without contacting the API.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate manifest prompts and required environment without contacting the API.",
    )
    parser.add_argument(
        "--persona-id",
        action="append",
        default=[],
        help="Generate only the selected persona id. Can be passed multiple times.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing PNG outputs. By default existing outputs are skipped.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SpriteConfigError(f"Persona sprite manifest not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpriteConfigError(f"Invalid JSON in persona sprite manifest {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SpriteConfigError(f"Persona sprite manifest must be a JSON object: {path}")
    return payload


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    return cleaned or "persona"


def output_name_for(persona_id: str, entry: Any = None) -> str:
    if isinstance(entry, dict):
        for key in ("output", "output_name", "file", "filename", "asset"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                name = Path(value).name
                return name if name.lower().endswith(".png") else f"{safe_filename(name)}.png"
    return f"{safe_filename(persona_id)}.png"


def prompt_from_entry(entry: Any, *, allow_plain_string: bool = False) -> str | None:
    if allow_plain_string and isinstance(entry, str):
        return entry.strip() or None
    if isinstance(entry, dict):
        value = entry.get("prompt")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def filter_personas(personas: list[PersonaSprite], persona_ids: list[str]) -> list[PersonaSprite]:
    if not persona_ids:
        return personas
    selected = {persona_id.strip() for persona_id in persona_ids if persona_id.strip()}
    result = [persona for persona in personas if persona.persona_id in selected]
    missing = sorted(selected - {persona.persona_id for persona in result})
    if missing:
        raise SpriteConfigError(f"Selected persona ids not found in manifest: {', '.join(missing)}")
    return result


def extract_personas(manifest: dict[str, Any]) -> list[PersonaSprite]:
    personas: list[PersonaSprite] = []

    prompts = manifest.get("prompts")
    if isinstance(prompts, dict):
        for persona_id, entry in prompts.items():
            prompt = prompt_from_entry(entry, allow_plain_string=True)
            if prompt:
                personas.append(
                    PersonaSprite(str(persona_id), prompt, output_name_for(str(persona_id), entry))
                )

    persona_list = manifest.get("personas")
    if isinstance(persona_list, list):
        for entry in persona_list:
            if not isinstance(entry, dict):
                continue
            persona_id = next(
                (
                    str(entry[key]).strip()
                    for key in ("id", "key", "slug", "name", "persona")
                    if isinstance(entry.get(key), str) and str(entry[key]).strip()
                ),
                "",
            )
            prompt = prompt_from_entry(entry)
            if persona_id and prompt:
                personas.append(PersonaSprite(persona_id, prompt, output_name_for(persona_id, entry)))

    sprites = manifest.get("sprites")
    if isinstance(sprites, dict):
        for persona_id, entry in sprites.items():
            prompt = prompt_from_entry(entry)
            if prompt:
                personas.append(
                    PersonaSprite(str(persona_id), prompt, output_name_for(str(persona_id), entry))
                )

    unique: dict[str, PersonaSprite] = {}
    for persona in personas:
        unique[persona.persona_id] = persona
    result = list(unique.values())
    if not result:
        raise SpriteConfigError(
            "No persona sprite prompts found in manifest. Add prompts as one of: "
            "`prompts: {id: prompt}`, `prompts: {id: {prompt, output}}`, "
            "`personas: [{id, prompt}]`, or `sprites: {id: {prompt}}`."
        )
    return result


def find_env_name(names: tuple[str, ...]) -> str | None:
    return next((name for name in names if os.environ.get(name)), None)


def load_model_config(path_value: str) -> dict[str, Any]:
    if not path_value:
        return {}
    path = Path(path_value)
    if not path.exists():
        raise SpriteConfigError(f"Model config not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpriteConfigError(f"Invalid JSON in model config {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SpriteConfigError(f"Model config must be a JSON object: {path}")
    return payload


def require_api_key(model_config: dict[str, Any]) -> tuple[str, str]:
    config_key = model_config.get("api_key")
    if isinstance(config_key, str) and config_key.strip():
        return "model_config.api_key", config_key.strip()
    name = find_env_name(API_KEY_ENV_NAMES)
    if not name:
        raise SpriteConfigError(
            "Missing OpenAI API key. Set OPENAI_API_KEY, pass --model-config with api_key, "
            "or set one of the compatible image key variables: "
            f"{', '.join(API_KEY_ENV_NAMES[1:])}."
        )
    return name, os.environ[name]


def api_base_url(model_config: dict[str, Any]) -> str:
    config_base = model_config.get("image_api_base") or model_config.get("api_base")
    if isinstance(config_base, str) and config_base.strip():
        raw = config_base.strip()
    else:
        name = find_env_name(API_BASE_ENV_NAMES)
        raw = os.environ[name] if name else "https://api.openai.com"
    return raw.rstrip("/")


def image_generations_url(model_config: dict[str, Any]) -> str:
    explicit = model_config.get("image_generations_url")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    base = api_base_url(model_config)
    if base.endswith("/images/generations"):
        return base
    if base.endswith("/v1"):
        return f"{base}/images/generations"
    return f"{base}/v1/images/generations"


def resolve_model(default_model: str, model_config: dict[str, Any]) -> str:
    for key in ("image_model", "image_generation_model"):
        value = model_config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default_model


def call_images_api(api_key: str, model: str, prompt: str, size: str, model_config: dict[str, Any]) -> bytes:
    payload = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "n": 1,
    }
    request = urllib.request.Request(
        image_generations_url(model_config),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Images API request failed with HTTP {exc.code}: {redact_error(detail)}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Images API request failed: {exc.reason}") from exc

    response_payload = json.loads(body)
    data = response_payload.get("data")
    if not isinstance(data, list) or not data:
        raise RuntimeError("Images API response did not include image data.")
    first = data[0]
    if not isinstance(first, dict):
        raise RuntimeError("Images API response image entry had an unexpected shape.")

    b64_json = first.get("b64_json")
    if isinstance(b64_json, str) and b64_json:
        return base64.b64decode(b64_json)

    url = first.get("url")
    if isinstance(url, str) and url:
        with urllib.request.urlopen(url, timeout=180) as response:
            return response.read()

    raise RuntimeError("Images API response contained neither b64_json nor url image output.")


def redact_error(message: str, extra_values: tuple[str, ...] = ()) -> str:
    for name in API_KEY_ENV_NAMES:
        value = os.environ.get(name)
        if value:
            message = message.replace(value, "[redacted]")
    for value in extra_values:
        if value:
            message = message.replace(value, "[redacted]")
    return message


def validate_png(payload: bytes) -> None:
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("Generated image payload was not a PNG.")


def planned_outputs(personas: list[PersonaSprite], output_dir: Path) -> list[tuple[PersonaSprite, Path]]:
    return [(persona, output_dir / persona.output_name) for persona in personas]


def print_plan(personas: list[PersonaSprite], output_dir: Path) -> None:
    print(f"Manifest personas: {len(personas)}")
    print(f"Output directory: {output_dir}")
    for persona, output_path in planned_outputs(personas, output_dir):
        print(f"- {persona.persona_id} -> {output_path.name}")


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).resolve()
    output_dir = Path(args.output_dir).resolve()
    model_config: dict[str, Any] = {}
    api_key = ""

    try:
        manifest = load_json(manifest_path)
        personas = filter_personas(extract_personas(manifest), args.persona_id)
        model_config = load_model_config(args.model_config)
        selected_model = resolve_model(args.model, model_config)
        print_plan(personas, output_dir)

        if args.dry_run:
            print("Dry run complete; no API request was made and no files were written.")
            return 0

        if args.check:
            env_name, api_key = require_api_key(model_config)
            print(f"Environment check passed using {env_name}; secret value was not printed.")
            print(f"Images endpoint: {image_generations_url(model_config)}")
            print(f"Using model: {selected_model}")
            print("Check complete; no API request was made and no files were written.")
            return 0

        env_name, api_key = require_api_key(model_config)
        print(f"Using API key from {env_name}; secret value was not printed.")
        print(f"Images endpoint: {image_generations_url(model_config)}")
        print(f"Using model: {selected_model}")
        output_dir.mkdir(parents=True, exist_ok=True)
        for persona, output_path in planned_outputs(personas, output_dir):
            if output_path.exists() and not args.force:
                print(f"Skipping existing: {output_path.name}")
                continue
            print(f"Generating: {persona.persona_id} -> {output_path.name}")
            image_bytes = call_images_api(api_key, selected_model, persona.prompt, args.size, model_config)
            validate_png(image_bytes)
            output_path.write_bytes(image_bytes)
            time.sleep(0.25)
        print("Persona sprite generation complete.")
        return 0
    except SpriteConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Generation error: {redact_error(str(exc), (api_key,))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
