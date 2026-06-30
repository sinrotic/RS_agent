from __future__ import annotations

from itertools import islice
from pathlib import Path
from typing import Any

from rs_core.common.io import read_json, read_jsonl, write_jsonl
from rs_core.common.openai_compatible_client import OpenAICompatibleClient
from rs_core.offline.training.data_contracts import synthetic_sft_samples, validate_sft_samples
from rs_core.offline.training.gpt_sft_config import load_gpt_sft_config
from rs_core.offline.training.gpt_sft_generator import DEFAULT_SYSTEM_PROMPT, build_gpt_sft_messages, generate_gpt_sft_sample


class GptSftExecutionDisabledError(RuntimeError):
    pass


def run_gpt_sft(
    config_path: str | None = None,
    *,
    execute: bool = False,
    limit: int | None = None,
    input_path: str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    overrides: dict[str, Any] = {"data": {}}
    if input_path is not None:
        overrides["data"]["input_path"] = input_path
    if output_path is not None:
        overrides["data"]["output_path"] = output_path
    if limit is not None:
        overrides["data"]["max_samples"] = limit
    if not overrides["data"]:
        overrides = {}

    config = load_gpt_sft_config(config_path, overrides=overrides)
    data = config["data"]
    gpt_sft = config["gpt_sft"]
    sample_limit = int(data["max_samples"])
    seed_records = _load_seed_records(data.get("input_path"))
    selected = list(islice(seed_records, max(sample_limit, 0)))
    validate_sft_samples(selected)

    system_prompt = str(gpt_sft.get("system_prompt") or DEFAULT_SYSTEM_PROMPT)
    result: dict[str, Any] = {
        "mode": "gpt_sft",
        "dry_run": not execute,
        "input_path": data.get("input_path"),
        "output_path": data["output_path"],
        "seed_count": len(seed_records),
        "sample_count": len(selected),
        "generated_count": 0,
        "failed_count": 0,
        "provider": gpt_sft["provider"],
        "model": gpt_sft["model"],
        "api_base": gpt_sft["api_base"],
        "api_key_env": gpt_sft["api_key_env"],
        "first_message_summary": _message_summary(build_gpt_sft_messages(selected[0], system_prompt=system_prompt)),
        "api_called": False,
    }
    if not execute:
        return result
    if config.get("dry_run", True) or not gpt_sft.get("enabled", False):
        raise GptSftExecutionDisabledError("GPT SFT execution requires config dry_run=false and gpt_sft.enabled=true")

    client = OpenAICompatibleClient(
        base_url=gpt_sft["api_base"],
        api_key_env=gpt_sft["api_key_env"],
        timeout_seconds=float(gpt_sft["timeout_seconds"]),
        allow_insecure_local_api_base=bool(gpt_sft.get("allow_insecure_local_api_base", False)),
    )
    generated: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, sample in enumerate(selected):
        try:
            generated.append(generate_gpt_sft_sample(
                sample,
                client=client,
                model=gpt_sft["model"],
                system_prompt=system_prompt,
                temperature=gpt_sft.get("temperature"),
                max_tokens=gpt_sft.get("max_tokens"),
                response_format=gpt_sft.get("response_format"),
            ))
        except Exception as exc:
            if gpt_sft.get("strict", True):
                raise
            failures.append({"index": index, "error_type": type(exc).__name__, "error": str(exc)[:300]})
    result.update({
        "api_called": True,
        "generated_count": len(generated),
        "failed_count": len(failures),
        "failures": failures,
    })
    if not generated:
        return result
    validate_sft_samples(generated)
    write_jsonl(data["output_path"], generated)
    return result


def _message_summary(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {"role": message.get("role"), "content_chars": len(str(message.get("content", "")))}
        for message in messages
    ]


def _load_seed_records(input_path: str | None) -> list[dict[str, Any]]:
    if not input_path:
        return synthetic_sft_samples()
    path = Path(input_path)
    if path.suffix.lower() == ".jsonl":
        return read_jsonl(path)
    payload = read_json(path)
    if isinstance(payload, list):
        return _as_record_list(payload)
    if not isinstance(payload, dict):
        raise ValueError(f"Unsupported GPT SFT input payload: {path}")
    if payload.get("schema_version") == "rs_agent_training_signals_v1":
        return _as_record_list(payload.get("sft"))
    if isinstance(payload.get("training_signals"), dict):
        return _as_record_list(payload["training_signals"].get("sft"))
    if payload.get("schema_version") == "rs_agent_sft_sample_v1":
        return [payload]
    if isinstance(payload.get("sft"), list):
        return _as_record_list(payload.get("sft"))
    raise ValueError(f"Unsupported GPT SFT input payload: {path}")


def _as_record_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [record for record in value if isinstance(record, dict)]
