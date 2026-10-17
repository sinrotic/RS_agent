#!/usr/bin/env python3
"""只管理本脚本创建的 GPU 2 / 18092 对照实例，保留正式服务。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from benchmark import measure, payload, metrics


ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "model"
BASE = "http://127.0.0.1:18092/v1"


def gpu_memory() -> int:
    return int(subprocess.check_output([
        "nvidia-smi", "-i", "2", "--query-gpu=memory.used", "--format=csv,noheader,nounits",
    ], text=True).strip())


def stop_owned(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    for _ in range(20):
        if gpu_memory() < 512:
            return
        time.sleep(1)
    raise RuntimeError("对照实例退出后 GPU 2 仍有占用；停止后续试验，不清理其他进程")


def benchmark_variant(name: str) -> dict:
    artifact = ROOT / (name + ".json")
    subprocess.run([sys.executable, str(ROOT / "benchmark.py"), "--base-url", BASE, "--output", str(artifact)], check=True)
    report = json.loads(artifact.read_text())
    # 补充匹配当前应用 8 路额度的突发样本，以及长短混合场景。
    extra = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(measure, BASE, payload("qwen35-4b", tool=True), "named_tool_concurrency8") for _ in range(16)]
        extra += [future.result() for future in futures]
    report["concurrency8_batch_seconds"] = round(time.perf_counter() - started, 4)
    prefix = "批次 " + name + "\n" + "\n".join(
        f"资料{i:03d}：虚构占位资料用于测试，不得作为商品事实。" for i in range(220)
    )
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(measure, BASE, payload("qwen35-4b", prefix), "mixed_long"),
            *[executor.submit(measure, BASE, payload("qwen35-4b", tool=True), "mixed_short") for _ in range(3)],
        ]
        extra += [future.result() for future in futures]
    report["mixed_batch_seconds"] = round(time.perf_counter() - started, 4)
    report["extra_records"] = extra
    report["final_metrics"] = metrics(BASE)
    artifact.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    return {"artifact": artifact.name, "extra_samples": len(extra), "summaries": report["summaries"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=["baseline", "text_only", "text_only_batch", "json_compact"])
    parser.add_argument("--label", choices=["baseline_repeat", "text_only_batch_retry"])
    args = parser.parse_args()
    lock = open("/tmp/rs-serving-tuning-gpu2.lock", "a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    result = {"started_at": datetime.now(timezone.utc).isoformat(), "variants": {}}
    variants = {
        "baseline": {},
        "text_only": {"VLLM_LANGUAGE_MODEL_ONLY": "true"},
        "text_only_batch": {"VLLM_LANGUAGE_MODEL_ONLY": "true", "VLLM_MAX_NUM_SEQS": "16", "VLLM_MAX_NUM_BATCHED_TOKENS": "4096"},
        "json_compact": {"VLLM_JSON_COMPACT_OUTPUT": "true"},
    }
    if args.variant:
        variants = {args.label or args.variant: variants[args.variant]}
    result_file = ROOT / ((args.label + "_tuning.json") if args.label else "tuning.json")
    for name, options in variants.items():
        if gpu_memory() >= 512:
            raise RuntimeError("GPU 2 不是空闲状态；不启动额外模型")
        import socket
        with socket.socket() as connection:
            if connection.connect_ex(("127.0.0.1", 18092)) == 0:
                raise RuntimeError("对照端口已使用")
        env = {**os.environ,
            "VLLM_VENV": "/mnt/data/luo/venvs/rsagent-vllm",
            "PYTHON_BIN": sys.executable,
            "MODEL_PATH": "/mnt/data/luo/models/Qwen3.5-4B",
            "CUDA_VISIBLE_DEVICES": "2", "VLLM_PORT": "18092",
            "VLLM_MAX_MODEL_LEN": "16384", "VLLM_GPU_MEMORY_UTILIZATION": "0.78",
            "VLLM_QUANTIZATION": "auto", "VLLM_QUANTIZATION_CONFIG": "",
            "VLLM_LANGUAGE_MODEL_ONLY": "false", "VLLM_SPECULATIVE_CONFIG": "",
            "VLLM_JSON_COMPACT_OUTPUT": "false",
            "VLLM_MAX_NUM_SEQS": "", "VLLM_MAX_NUM_BATCHED_TOKENS": "",
            "VLLM_READY_FILE": str(ROOT / (name + ".ready")),
            "VLLM_PREFIX_KEEPALIVE": "false", "VLLM_DELAY_AFTER_WARMUP_SEC": "0",
            "VLLM_CACHE_ROOT": str(ROOT / "cache"), "VLLM_READY_TIMEOUT_SEC": "600",
            "VLLM_STRUCTURED_OUTPUT_PROBE": "true", "VLLM_ENFORCE_STRICT_TOOL_CALLING": "true",
            **options,
        }
        print("START", name, json.dumps(options), flush=True)
        Path(env["VLLM_READY_FILE"]).unlink(missing_ok=True)
        log = open(ROOT / (name + ".log"), "w")
        process = subprocess.Popen(["bash", str(MODEL_DIR / "start_qwen35_4b_vllm.sh")], env=env,
                                   cwd=MODEL_DIR, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        started = time.monotonic()
        try:
            while not Path(env["VLLM_READY_FILE"]).exists():
                if process.poll() is not None:
                    raise RuntimeError("模型启动失败：" + name)
                if time.monotonic() - started > 600:
                    raise TimeoutError("模型预热超时：" + name)
                time.sleep(2)
            record = benchmark_variant(name)
            record["options"] = options
            record["gpu_memory_mib"] = gpu_memory()
            result["variants"][name] = record
            print("PASS", name, flush=True)
        except Exception as error:
            result["variants"][name] = {"error": str(error), "options": options}
            print("FAIL", name, str(error), flush=True)
        finally:
            stop_owned(process)
            log.close()
            result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")


if __name__ == "__main__":
    main()
