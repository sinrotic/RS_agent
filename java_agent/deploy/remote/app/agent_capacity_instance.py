#!/usr/bin/env python3
"""启动/停止本次独立压测实例，不替换部署产物或修改模型进程。"""
import argparse
import hashlib
import json
import os
import pathlib
import signal
import subprocess
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop"])
    parser.add_argument("--directory", required=True)
    parser.add_argument("--streams", type=int, default=8)
    parser.add_argument("--loops", type=int, default=32)
    parser.add_argument("--model-wait-ms", type=int, default=200)
    parser.add_argument("--port", type=int, default=18204)
    parser.add_argument("--max-tokens", type=int, default=1024)
    args = parser.parse_args()
    directory = pathlib.Path(args.directory).resolve()
    pid_file = directory / "agent.pid"
    jar = directory / "agent.jar"
    if args.action == "stop":
        if not pid_file.exists():
            return
        pid = int(pid_file.read_text())
        try:
            cmdline = pathlib.Path(f"/proc/{pid}/cmdline").read_bytes()
        except FileNotFoundError:
            pid_file.unlink()
            return
        if str(jar).encode() not in cmdline:
            raise RuntimeError("PID 不属于本次压测实例，拒绝停止")
        os.kill(pid, signal.SIGTERM)
        for _ in range(60):
            if not pathlib.Path(f"/proc/{pid}/cmdline").exists() or not pathlib.Path(f"/proc/{pid}/cmdline").read_bytes():
                break
            time.sleep(.5)
        else:
            raise RuntimeError("实例未在 30 秒内停止")
        pid_file.unlink()
        print(json.dumps({"stopped_pid": pid}))
        return
    if pid_file.exists():
        raise RuntimeError("先停止已有测试实例")
    env = os.environ.copy()
    env.update({
        "RS_AGENT_LOCAL_MODEL_BASE_URL": "http://127.0.0.1:18082/v1",
        "RS_AGENT_LOCAL_MODEL_NAME": "qwen35-4b",
        "RS_AGENT_LOCAL_MODEL_API_KEY": "local-unused",
        "RS_AGENT_LOCAL_MODEL_MAX_TOKENS": str(args.max_tokens),
        "RS_AGENT_SESSION_PERSISTENCE_ENABLED": "false",
        "RS_AGENT_SESSION_STORE_TYPE": "memory", "RS_AGENT_RECOMMENDATION_TYPE": "memory",
        "RS_AGENT_TRACE_ENABLED": "false", "RS_AGENT_MAX_MODEL_STREAMS": str(args.streams),
        "RS_AGENT_MAX_ACTIVE_LOOPS": str(args.loops), "RS_AGENT_MODEL_STREAM_ACQUIRE_TIMEOUT_MS": str(args.model_wait_ms),
        "SPRING_CLOUD_NACOS_DISCOVERY_ENABLED": "false",
    })
    command = ["java", "-Xms256m", "-Xmx2g", "-jar", str(jar),
               "--spring.profiles.active=local-qwen", f"--server.port={args.port}",
               "--server.address=127.0.0.1", "--spring.cloud.nacos.discovery.enabled=false",
               "--spring.cloud.nacos.config.enabled=false", "--spring.ai.openai.chat.completions-path=/chat/completions",
               "--spring.mvc.async.request-timeout=180000"]
    log_path = directory / f"agent-streams-{args.streams}-loops-{args.loops}-wait-{args.model_wait_ms}-tokens-{args.max_tokens}.log"
    with log_path.open("w") as log:
        process = subprocess.Popen(command, cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    pid_file.write_text(str(process.pid))
    metadata = {"pid": process.pid, "jar_sha256": hashlib.sha256(jar.read_bytes()).hexdigest(),
                "streams": args.streams, "loops": args.loops, "model_wait_ms": args.model_wait_ms, "max_tokens": args.max_tokens,
                "command": command, "scope": "isolated-memory-agent", "log": str(log_path)}
    (directory / "instance.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
    for _ in range(90):
        if process.poll() is not None:
            raise RuntimeError(f"实例退出，检查 {log_path}")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{args.port}/api/agent/chat/stream", timeout=2)
        except urllib.error.HTTPError as error:
            if error.code in (400, 405):
                print(json.dumps(metadata, ensure_ascii=False), flush=True)
                return
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError("实例未就绪")


if __name__ == "__main__":
    main()
