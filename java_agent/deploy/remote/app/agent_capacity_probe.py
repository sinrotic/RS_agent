#!/usr/bin/env python3
"""真实 Java Agent SSE 并发探针；HTTP 200 不能替代业务成功。仅使用标准库。"""
import argparse
import concurrent.futures
import collections
import json
import math
import os
import pathlib
import subprocess
import threading
import time
import urllib.error
import urllib.request
import urllib.parse
import uuid

PROMPTS = [
    "我想买一个日常通勤双肩包，但还没确定预算。请先问我一个最关键的澄清问题，暂时不要检索商品。",
    "选购通勤双肩包时，应该考虑哪些方面？请给出三条简短的一般建议，不推荐具体商品，不查询商品或用户历史。",
    "我每天背电脑通勤，想买双肩包，但不知道应该选多大。请先问我电脑尺寸，用一个简短问题回答，暂时不要检索商品。",
]
COMPARISON_PROMPT = "请比较通勤双肩包的三种选择思路：轻量型、电脑保护型、防雨型。从重量、保护、收纳、舒适度、使用场景五个方面给出一般性的比较，最后给出简短选购建议。不推荐具体商品，不查询商品或用户历史，不编造价格。"


def fetch(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode()


def percentile(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * quantile) - 1)], 3)


def model_metrics(url):
    try:
        values = collections.defaultdict(float)
        for line in fetch(url + "/metrics").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            key, value = line.rsplit(None, 1)
            name = key.split("{")[0]
            if any(part in name for part in ["num_requests", "tokens_total", "request_success", "preemption", "prefix_cache", "kv_cache_usage"]):
                values[name] += float(value)
        return dict(values)
    except Exception as error:
        return {"error": type(error).__name__}


def gpu_sample(index, pid):
    result = {"time": time.time()}
    try:
        fields = subprocess.check_output([
            "nvidia-smi", "-i", str(index),
            "--query-gpu=index,memory.used,utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits",
        ], timeout=5, text=True).strip().split(",")
        result.update(zip(["gpu_index", "memory_mib", "utilization_pct", "temperature_c"], map(int, fields)))
        processes = subprocess.check_output([
            "nvidia-smi", "-i", str(index), "--query-compute-apps=pid,used_gpu_memory",
            "--format=csv,noheader,nounits",
        ], timeout=5, text=True)
        result["gpu_processes"] = [{"pid": int(line.split(",")[0]), "memory_mib": int(line.split(",")[1])}
                                   for line in processes.splitlines() if line.strip()]
        if pid:
            status = pathlib.Path(f"/proc/{pid}/status").read_text()
            for line in status.splitlines():
                if line.startswith("VmRSS:"):
                    result["agent_rss_mib"] = round(int(line.split()[1]) / 1024, 2)
    except Exception as error:
        result["error"] = type(error).__name__
    return result


def request_one(args, phase, number, barrier, prompt):
    session = f"capacity-{args.run_id}-{phase}-{number}-{uuid.uuid4().hex[:8]}"
    body = {"session_id": session, "profile_user_id": f"capacity-{number}",
            "user_message": prompt, "limit": 3, "context": {"scene": "capacity-probe"}}
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream",
               "X-Account-Id": f"capacity-account-{number}", "X-Profile-User-Id": f"capacity-{number}"}
    barrier.wait(timeout=30)
    started = time.monotonic()
    result = {"number": number, "prompt": prompt, "session_id": session, "success": False,
              "events": {}, "answer": [], "errors": [], "finish_reason": None, "started_at": time.time()}
    first_event = None
    first_answer = None
    event_name = "message"
    event_data = []

    def consume():
        nonlocal first_event, first_answer
        if not event_data:
            return
        payload = json.loads("\n".join(event_data))
        elapsed = time.monotonic() - started
        if first_event is None:
            first_event = elapsed
        result["events"][event_name] = result["events"].get(event_name, 0) + 1
        if event_name in ("answer_block", "token"):
            if first_answer is None:
                first_answer = elapsed
            result["answer"].append(payload)
        if event_name == "error":
            result["errors"].append(payload)
        if event_name == "done":
            result["finish_reason"] = payload.get("finish_reason")

    try:
        request = urllib.request.Request(args.base + "/api/agent/chat/stream", json.dumps(body).encode(), headers)
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            result["http_status"] = response.status
            for raw in response:
                if time.monotonic() - started > args.timeout:
                    raise TimeoutError("total request deadline")
                line = raw.decode().rstrip("\r\n")
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    event_data.append(line[5:].strip())
                elif not line:
                    consume()
                    event_data = []
                    event_name = "message"
            consume()
        reason = str(result["finish_reason"] or "").upper()
        visible = any(block.get("content") or block.get("delta") or block.get("item_ids") for block in result["answer"])
        result["success"] = visible and not result["errors"] and reason == "FINAL_ANSWER"
        if not result["success"] and not result["errors"]:
            result["errors"].append({"error_code": "INCOMPLETE_OR_UNSUCCESSFUL_TURN"})
    except Exception as error:
        result["errors"].append({"error_code": type(error).__name__, "message": str(error)[:200]})
        if isinstance(error, urllib.error.HTTPError):
            result["http_status"] = error.code
    result["latency_s"] = round(time.monotonic() - started, 3)
    result["first_event_s"] = round(first_event, 3) if first_event is not None else None
    result["first_answer_s"] = round(first_answer, 3) if first_answer is not None else None
    return result


def audit_report(args):
    source = json.loads(pathlib.Path(args.audit_report).read_text())
    results = []

    def audit(phase, row):
        result = {"concurrency": phase["concurrency"], "number": row["number"], "session_id": row["session_id"]}
        if not row["session_id"].startswith("capacity-"):
            raise ValueError("只审计本探针创建的会话")
        try:
            request = urllib.request.Request(args.base + "/api/agent/sessions/"
                                            + urllib.parse.quote(row["session_id"], safe="") + "/turns",
                                            headers={"X-Profile-User-Id": f"capacity-{row['number']}"})
            with urllib.request.urlopen(request, timeout=10) as response:
                trace = json.load(response)
            result["tools"] = [{"name": tool.get("tool_name"), "status": tool.get("status"),
                                "message": (tool.get("metadata") or {}).get("message")}
                               for turn in trace.get("turns", []) for tool in turn.get("tool_calls", [])]
            result["failed_tools"] = sum(str(tool["status"]).upper() == "FAILED" for tool in result["tools"])
            result["trace_available"] = bool(trace.get("turns"))
        except Exception as error:
            result["trace_available"] = False
            result["error"] = type(error).__name__
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(audit, phase, row) for phase in source["phases"]
                   for row in phase["requests_detail"] if row["success"]]
        results = [future.result() for future in futures]
    summary = {"source": args.audit_report, "requests": len(results),
               "trace_available": sum(row["trace_available"] for row in results),
               "requests_with_failed_tools": sum(row.get("failed_tools", 0) > 0 for row in results),
               "failed_tools": sum(row.get("failed_tools", 0) for row in results),
               "requests_detail": results}
    pathlib.Path(args.output).write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in summary.items() if key != "requests_detail"}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:18204")
    parser.add_argument("--model-base", default="http://127.0.0.1:18082")
    parser.add_argument("--gpu", type=int, default=1)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--levels", default="1,2,4,6,8,9,12,16,32")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--p95-budget", type=float, default=30)
    parser.add_argument("--output", required=True)
    parser.add_argument("--label", default="default")
    parser.add_argument("--prompt", choices=["mixed", "clarify", "advice", "comparison"], default="mixed")
    parser.add_argument("--stop-after-failed-levels", type=int, default=2)
    parser.add_argument("--require-exclusive-gpu", action="store_true")
    parser.add_argument("--audit-report", help="只检查已完成探针会话的工具失败，不发起模型请求")
    args = parser.parse_args()
    if args.audit_report:
        audit_report(args)
        return
    args.run_id = uuid.uuid4().hex[:10]
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"config": vars(args), "model": json.loads(fetch(args.model_base + "/v1/models")),
              "started_at": time.time(), "scope": "真实 Java Agent/模型；内存会话和固定候选；不包含网关、数据库与在线推荐", "phases": []}
    instance = output.parent / "instance.json"
    if instance.exists():
        report["instance"] = json.loads(instance.read_text())
    report["host_cpu_count"] = os.cpu_count()
    samples = []
    stop = threading.Event()

    def monitor():
        while not stop.is_set():
            sample = gpu_sample(args.gpu, args.pid)
            sample["model_metrics"] = model_metrics(args.model_base)
            samples.append(sample)
            stop.wait(2)

    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    failed_levels = 0
    try:
        for concurrency in map(int, args.levels.split(",")):
            if concurrency < 1 or concurrency > 256:
                raise ValueError("concurrency must be between 1 and 256")
            before = model_metrics(args.model_base)
            rows = []
            started = time.monotonic()
            phase_started_at = time.time()
            for round_index in range(args.rounds):
                barrier = threading.Barrier(concurrency)
                with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                    futures = []
                    for index in range(concurrency):
                        number = round_index * concurrency + index
                        prompt = (PROMPTS[number % len(PROMPTS)] if args.prompt == "mixed"
                                  else COMPARISON_PROMPT if args.prompt == "comparison"
                                  else PROMPTS[0 if args.prompt == "clarify" else 1])
                        futures.append(pool.submit(request_one, args, concurrency, number, barrier, prompt))
                    rows.extend(f.result() for f in futures)
                progress = {"concurrency": concurrency, "completed_rounds": round_index + 1,
                            "total_rounds": args.rounds, "completed_requests": len(rows),
                            "successful": sum(row["success"] for row in rows),
                            "elapsed_s": round(time.monotonic() - started, 3)}
                output.with_suffix(".progress.json").write_text(json.dumps(progress))
                if args.rounds > 3 and (round_index + 1) % 10 == 0:
                    print(json.dumps({"progress": progress}), flush=True)
            elapsed = time.monotonic() - started
            successes = [row for row in rows if row["success"]]
            latencies = [row["latency_s"] for row in successes]
            phase = {"concurrency": concurrency, "requests": len(rows), "successful": len(successes),
                     "success_rate": len(successes) / len(rows), "elapsed_s": round(elapsed, 3),
                     "successful_turns_per_s": round(len(successes) / elapsed, 3),
                     "p50_s": percentile(latencies, .5), "p95_s": percentile(latencies, .95),
                     "p99_s": percentile(latencies, .99),
                     "first_answer_p95_s": percentile([r["first_answer_s"] for r in successes if r["first_answer_s"] is not None], .95),
                     "before_model_metrics": before, "after_model_metrics": model_metrics(args.model_base), "requests_detail": rows}
            phase["passes"] = phase["success_rate"] >= .99 and phase["p95_s"] is not None and phase["p95_s"] <= args.p95_budget
            phase_samples = [sample for sample in samples if sample["time"] >= phase_started_at]
            phase["gpu_process_count_peak"] = max((len(sample.get("gpu_processes", [])) for sample in phase_samples), default=0)
            phase["shared_gpu_detected"] = phase["gpu_process_count_peak"] > 1
            phase["started_at"] = phase_started_at
            phase["finished_at"] = time.time()
            phase["model_counter_deltas"] = {key: round(value - before.get(key, value), 3)
                                               for key, value in phase["after_model_metrics"].items()
                                               if key.endswith("_total") and isinstance(value, (int, float))}
            report["phases"].append(phase)
            report["samples"] = samples
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps({k: v for k, v in phase.items() if k not in ("requests_detail", "before_model_metrics", "after_model_metrics")}, ensure_ascii=False), flush=True)
            if samples and samples[-1].get("memory_mib", 0) > 24000:
                report["stopped_reason"] = "GPU memory stop threshold"
                break
            if args.require_exclusive_gpu and phase["shared_gpu_detected"]:
                report["stopped_reason"] = "another GPU process detected; current level is contaminated"
                break
            failed_levels = failed_levels + 1 if not phase["passes"] else 0
            if args.stop_after_failed_levels and failed_levels >= args.stop_after_failed_levels:
                report["stopped_reason"] = "consecutive failed levels"
                break
            time.sleep(2)
    finally:
        stop.set()
        watcher.join(timeout=7)
        report["samples"] = samples
        report["finished_at"] = time.time()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
