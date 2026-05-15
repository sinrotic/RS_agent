from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_MODEL_CONFIG_PATH = Path("configs/simulation_model.local.json")
DEFAULT_API_BASE = "https://api.sinrotic233.com"


class SimulationModelUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class SimulationModelConfig:
    api_base: str
    api_key: str
    model: str
    timeout_seconds: float = 30.0

    @classmethod
    def from_file(cls, path: str | Path = DEFAULT_MODEL_CONFIG_PATH) -> "SimulationModelConfig":
        config_path = Path(path)
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise SimulationModelUnavailableError(f"Simulation model config not found: {config_path}") from exc
        except json.JSONDecodeError as exc:
            raise SimulationModelUnavailableError(f"Simulation model config is not valid JSON: {config_path}") from exc
        if not isinstance(raw, dict):
            raise SimulationModelUnavailableError(f"Simulation model config must be a JSON object: {config_path}")
        api_base = str(raw.get("api_base") or DEFAULT_API_BASE).rstrip("/")
        api_key = str(raw.get("api_key") or "").strip()
        model = str(raw.get("model") or "").strip()
        timeout_seconds = float(raw.get("timeout_seconds") or 30.0)
        if not api_key:
            raise SimulationModelUnavailableError(f"Simulation model api_key is empty: {config_path}")
        if not model:
            raise SimulationModelUnavailableError(f"Simulation model name is empty: {config_path}")
        return cls(api_base=api_base, api_key=api_key, model=model, timeout_seconds=timeout_seconds)


class SimulationModelClient:
    def __init__(self, config: SimulationModelConfig) -> None:
        self.config = config

    @classmethod
    def from_file(cls, path: str | Path = DEFAULT_MODEL_CONFIG_PATH) -> "SimulationModelClient":
        return cls(SimulationModelConfig.from_file(path))

    def complete(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.7,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            self.config.api_base + "/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise SimulationModelUnavailableError(f"Simulation model HTTP error: {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise SimulationModelUnavailableError(f"Simulation model request failed: {type(exc).__name__}") from exc
        return _extract_message_content(data)


def _extract_message_content(data: dict[str, Any]) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SimulationModelUnavailableError("Simulation model response missing choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise SimulationModelUnavailableError("Simulation model response content is empty")
    return content
