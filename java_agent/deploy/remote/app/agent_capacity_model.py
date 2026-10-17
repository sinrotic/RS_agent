#!/usr/bin/env python3
"""保留并恢复已有模型启动参数；只操作核验过的 GPU 1 模型 wrapper。"""
import argparse
import json
import os
import pathlib
import signal
import subprocess
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["capture", "restart", "restore"])
    parser.add_argument("--directory", required=True)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--max-len", type=int, default=16384)
    args = parser.parse_args()
    directory = pathlib.Path(args.directory)
    backup = directory / "original-model.json"
    pid_file = directory / "model-wrapper.pid"
    if args.action == "capture":
        if backup.exists():
            raise RuntimeError("模型参数备份已存在，不覆盖")
        raw = pathlib.Path(f"/proc/{args.pid}/environ").read_bytes().split(b"\0")
        env = {}
        for entry in raw:
            key, sep, value = entry.partition(b"=")
            if sep and (key.startswith(b"VLLM_") or key.decode() in ("CUDA_VISIBLE_DEVICES", "MODEL_PATH", "SERVED_MODEL_NAME")):
                env[key.decode()] = value.decode()
        command = pathlib.Path(f"/proc/{args.pid}/cmdline").read_bytes().split(b"\0")
        if env.get("CUDA_VISIBLE_DEVICES") != "1" or b"start_qwen35_4b_vllm.sh" not in b" ".join(command):
            raise RuntimeError("目标不符合 GPU 1 模型启动器")
        script = command[1].decode()
        saved = {"original_pid": args.pid, "script": script, "environment": env}
        backup.write_text(json.dumps(saved, indent=2))
        backup.chmod(0o600)
        pid_file.write_text(str(args.pid))
        print(json.dumps({"captured_pid": args.pid, "original_max_len": env.get("VLLM_MAX_MODEL_LEN")}))
        return
    saved = json.loads(backup.read_text())
    pid = int(pid_file.read_text())
    cmdline = pathlib.Path(f"/proc/{pid}/cmdline").read_bytes()
    if saved["script"].encode() not in cmdline:
        raise RuntimeError("PID 与模型启动器不匹配")
    with urllib.request.urlopen("http://127.0.0.1:18082/metrics", timeout=5) as response:
        for line in response.read().decode().splitlines():
            if line.startswith(("vllm:num_requests_running{", "vllm:num_requests_waiting{")) and float(line.rsplit(None, 1)[1]) > 0:
                raise RuntimeError("模型仍有正在执行或等待的请求，暂不重启")
    os.kill(pid, signal.SIGTERM)
    for _ in range(90):
        try:
            urllib.request.urlopen("http://127.0.0.1:18082/v1/models", timeout=1)
        except OSError:
            break
        time.sleep(.5)
    else:
        raise RuntimeError("旧模型未停止")
    time.sleep(3)
    env = os.environ.copy()
    env.update(saved["environment"])
    if args.action == "restart":
        env.update({"VLLM_MAX_MODEL_LEN": str(args.max_len), "VLLM_PREFIX_KEEPALIVE": "false",
                    "VLLM_READY_FILE": str(directory / "model.ready")})
    log = directory / ("model-restored.log" if args.action == "restore" else "model-expanded.log")
    with log.open("w") as stream:
        process = subprocess.Popen(["bash", saved["script"]], env=env, cwd=str(pathlib.Path(saved["script"]).parent),
                                   stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    pid_file.write_text(str(process.pid))
    print(json.dumps({"launched_pid": process.pid, "max_len": env.get("VLLM_MAX_MODEL_LEN"), "log": str(log)}), flush=True)


if __name__ == "__main__":
    main()
