#!/usr/bin/env python3
"""核验 GPU 1 模型后切换 BF16/FP8 对照配置，备份原部署并支持恢复。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request


FP8_CONFIG = {"ignore": ["lm_head", "re:.*visual.*", "re:.*linear_attn.*", "re:.*self_attn.*"]}


def proc_environment(pid):
    return dict(entry.decode().split("=", 1) for entry in
                Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if b"=" in entry)


def proc_command(pid):
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except FileNotFoundError:
        return ""


def get_json(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def stop_model(directory, saved):
    pid = int((directory / "model-wrapper.pid").read_text())
    command = proc_command(pid)
    expected = (saved["script"], str(directory / "start_qwen35_4b_vllm.sh"))
    if command:
        if not any(script in command for script in expected):
            raise RuntimeError("PID 不属于已核验的模型启动器")
        if proc_environment(pid).get("CUDA_VISIBLE_DEVICES") != "1":
            raise RuntimeError("拒绝停止非 GPU 1 启动器")
        try:
            with urllib.request.urlopen("http://127.0.0.1:18082/metrics", timeout=5) as response:
                for line in response.read().decode().splitlines():
                    if line.startswith(("vllm:num_requests_running{", "vllm:num_requests_waiting{")):
                        if float(line.rsplit(None, 1)[1]) > 0:
                            raise RuntimeError("模型仍有请求，暂不切换")
        except OSError:
            pass
        if os.getpgid(pid) == pid:
            os.killpg(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    for _ in range(120):
        result = subprocess.run(["nvidia-smi", "--query-compute-apps=gpu_uuid,pid", "--format=csv,noheader"],
                                capture_output=True, text=True, check=True)
        if saved["gpu_uuid"] not in result.stdout:
            try:
                get_json("http://127.0.0.1:18082/v1/models")
            except OSError:
                return
        time.sleep(.5)
    raise RuntimeError("GPU 1 或模型端口仍占用；不停止其他进程")


def write_private(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    path.chmod(0o600)


def update_env(path, updates):
    import shlex
    lines = path.read_text().splitlines()
    result = []
    for line in lines:
        key = line.split("=", 1)[0].strip().removeprefix("export ")
        if key not in updates:
            result.append(line)
    result.extend(f"{key}={shlex.quote(value)}" for key, value in updates.items())
    path.write_text("\n".join(result) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["capture", "bf16", "fp8", "promote", "restore"])
    parser.add_argument("--directory", required=True)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--scheme", choices=["fp8_per_channel", "fp8_per_block", "fp8_per_tensor"], default="fp8_per_channel")
    parser.add_argument("--weight-only", action="store_true", help="使用 Marlin W8A16；不兼容 per-channel")
    parser.add_argument("--keep-edge-layers", type=int, default=0, help="保留开头和末尾指定数量的 Transformer 层")
    args = parser.parse_args()
    if args.weight_only and args.scheme == "fp8_per_channel":
        parser.error("per-channel 在线量化要求 FP8 激活，不能使用 W8A16")
    directory = Path(args.directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    backup = directory / "original-model.json"
    if args.action == "capture":
        if backup.exists():
            raise RuntimeError("备份已存在，不覆盖")
        env = proc_environment(args.pid)
        raw_command = Path(f"/proc/{args.pid}/cmdline").read_bytes().split(b"\0")
        if env.get("CUDA_VISIBLE_DEVICES") != "1" or raw_command[0] not in (b"bash", b"/bin/bash"):
            raise RuntimeError("目标不是 GPU 1 的 bash 模型启动器")
        script = Path(raw_command[1].decode()).resolve()
        if script.name != "start_qwen35_4b_vllm.sh":
            raise RuntimeError("启动器名称不匹配")
        result = subprocess.run(["nvidia-smi", "-i", "1", "--query-gpu=uuid", "--format=csv,noheader"],
                                capture_output=True, text=True, check=True)
        saved_env = {key: value for key, value in env.items()
                     if key.startswith("VLLM_") or key in ("CUDA_VISIBLE_DEVICES", "MODEL_PATH", "SERVED_MODEL_NAME")}
        saved = {"pid": args.pid, "script": str(script), "environment": saved_env,
                 "gpu_uuid": result.stdout.strip(),
                 "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
                 "models": get_json("http://127.0.0.1:18082/v1/models")}
        for source, target in ((script, directory / "original-start.sh"),
                               (script.parent / ".env", directory / "original.env")):
            target.write_bytes(source.read_bytes())
            target.chmod(0o600)
        write_private(backup, saved)
        (directory / "model-wrapper.pid").write_text(str(args.pid))
        print(json.dumps({"captured_pid": args.pid, "gpu": 1, "script_sha256": saved["script_sha256"]}))
        return
    saved = json.loads(backup.read_text())
    quantization_config = {"ignore": list(FP8_CONFIG["ignore"])}
    if args.keep_edge_layers:
        model_config = json.loads((Path(saved["environment"]["MODEL_PATH"]) / "config.json").read_text())
        layers = model_config.get("text_config", model_config)["num_hidden_layers"]
        if not 0 < args.keep_edge_layers < layers / 2:
            raise RuntimeError("保留层数必须为正，且两端合计少于总层数")
        edges = list(range(args.keep_edge_layers)) + list(range(layers - args.keep_edge_layers, layers))
        quantization_config["ignore"].append("re:.*layers\\.(?:" + "|".join(map(str, edges)) + ")\\..*")
    live_script = Path(saved["script"])
    live_env = live_script.parent / ".env"
    if args.action == "promote":
        gate = json.loads((directory / "acceptance.json").read_text())
        if gate.get("promote") is not True:
            raise RuntimeError("验收未通过，不能推广")
        current = json.loads((directory / "current-model.json").read_text())
        if any(gate.get(key) != current.get(key) for key in ("quantization", "quantization_config", "weight_only", "prefix_keepalive")):
            raise RuntimeError("验收配置与当前实测配置不一致")
        if hashlib.sha256(live_script.read_bytes()).hexdigest() != saved["script_sha256"]:
            raise RuntimeError("原部署脚本发生变化，不覆盖")
        if live_env.read_bytes() != (directory / "original.env").read_bytes():
            raise RuntimeError("原部署配置发生变化，不覆盖")
    stop_model(directory, saved)
    env = os.environ.copy()
    env.update(saved["environment"])
    env.pop("VLLM_QUANTIZATION", None)
    env.pop("VLLM_QUANTIZATION_CONFIG", None)
    env.pop("VLLM_TEST_FORCE_FP8_MARLIN", None)
    if args.action == "restore":
        live_script.write_bytes((directory / "original-start.sh").read_bytes())
        live_env.write_bytes((directory / "original.env").read_bytes())
        command_script = live_script
    else:
        env.update({"VLLM_MAX_MODEL_LEN": "16384", "VLLM_PREFIX_KEEPALIVE": "false",
                    "VLLM_READY_FILE": str(directory / f"{args.action}.ready")})
        if args.action in ("fp8", "promote"):
            env.update({"VLLM_QUANTIZATION": gate["quantization"] if args.action == "promote" else args.scheme,
                        "VLLM_QUANTIZATION_CONFIG": gate["quantization_config"] if args.action == "promote" else json.dumps(quantization_config, separators=(",", ":")),
                        "VLLM_CACHE_ROOT": str(live_script.parent / "quantization-cache") if args.action == "promote" else str(directory / "vllm-cache"),
                        "VLLM_READY_TIMEOUT_SEC": "600"})
            weight_only = gate["weight_only"] if args.action == "promote" else args.weight_only
            env["VLLM_TEST_FORCE_FP8_MARLIN"] = "1" if weight_only else "0"
        command_script = directory / "start_qwen35_4b_vllm.sh"
        if args.action == "promote":
            live_script.write_bytes(command_script.read_bytes())
            env.update({"VLLM_PREFIX_KEEPALIVE": gate["prefix_keepalive"],
                        "VLLM_READY_FILE": saved["environment"]["VLLM_READY_FILE"]})
            updates = {key: env[key] for key in ("CUDA_VISIBLE_DEVICES", "VLLM_MAX_MODEL_LEN",
                                               "VLLM_QUANTIZATION", "VLLM_QUANTIZATION_CONFIG",
                                               "VLLM_CACHE_ROOT",
                                               "VLLM_TEST_FORCE_FP8_MARLIN",
                                               "VLLM_PREFIX_KEEPALIVE",
                                               "VLLM_READY_TIMEOUT_SEC")}
            update_env(live_env, updates)
            command_script = live_script
    env["WARMUP_SCRIPT"] = str(live_script.parent / "vllm_prefix_warmup.py")
    env["PROBE_SCRIPT"] = str(live_script.parent / "vllm_structured_output_probe.py")
    log = directory / f"model-{args.action}-{int(time.time())}.log"
    with log.open("w") as stream:
        process = subprocess.Popen(["bash", str(command_script)], env=env, cwd=live_script.parent,
                                   stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    (directory / "model-wrapper.pid").write_text(str(process.pid))
    metadata = {"action": args.action, "pid": process.pid, "gpu": 1,
                "max_model_len": env.get("VLLM_MAX_MODEL_LEN"),
                "quantization": env.get("VLLM_QUANTIZATION", "auto"),
                "quantization_config": env.get("VLLM_QUANTIZATION_CONFIG", ""), "log": str(log)}
    metadata["weight_only"] = env.get("VLLM_TEST_FORCE_FP8_MARLIN") == "1"
    metadata["prefix_keepalive"] = env.get("VLLM_PREFIX_KEEPALIVE", "false")
    write_private(directory / "current-model.json", metadata)
    print(json.dumps(metadata), flush=True)


if __name__ == "__main__":
    main()
