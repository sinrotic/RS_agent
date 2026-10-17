#!/usr/bin/env python3
"""实际 Agent 回归：三条普通建议必须完整，且不能出现 FAILED 工具。"""
import argparse
import json
import re
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
import urllib.request
import uuid

from agent_capacity_probe import PROMPTS, model_metrics, request_one


def advice_complete(blocks):
    answer = "\n".join(block.get("content", "") for block in blocks)
    topic_groups = [("肩带", "背负", "舒适"), ("容量", "分区", "收纳", "电脑"),
                    ("面料", "防水", "耐用", "耐磨", "防护"), ("预算", "价格")]
    topics = sum(any(word in answer for word in group) for group in topic_groups)
    numbered = len(re.findall(r"(?:^|\n|\s)[1-3一二三][.、．）)]", answer))
    return topics >= 3 or numbered >= 3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:18204")
    parser.add_argument("--model-base", default="http://127.0.0.1:18082")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--audit-report", help="离线检查压测中普通建议回答的完整性")
    args = parser.parse_args()
    if args.audit_report:
        source = json.loads(Path(args.audit_report).read_text())
        rows = [{"session_id": row["session_id"], "concurrency": phase["concurrency"],
                 "answer": row.get("answer", []), "answer_complete": advice_complete(row.get("answer", []))}
                for phase in source["phases"] for row in phase["requests_detail"] if row["prompt"] == PROMPTS[1]]
        result = {"label": args.label, "source": args.audit_report, "advice_requests": len(rows),
                  "complete": sum(row["answer_complete"] for row in rows), "results": rows}
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps({key: value for key, value in result.items() if key != "results"}))
        return
    request_args = SimpleNamespace(base=args.base, run_id=uuid.uuid4().hex[:10], timeout=60)
    rows = []
    for number in range(args.rounds):
        before = model_metrics(args.model_base)
        row = request_one(request_args, 1, number, Barrier(1), PROMPTS[1])
        after = model_metrics(args.model_base)
        row["model_calls"] = after.get("vllm:request_success_total", 0) - before.get("vllm:request_success_total", 0)
        try:
            request = urllib.request.Request(args.base + "/api/agent/sessions/" + row["session_id"] + "/turns",
                                             headers={"X-Profile-User-Id": f"capacity-{number}"})
            with urllib.request.urlopen(request, timeout=10) as response:
                trace = json.load(response)
            row["tools"] = [{"name": tool.get("tool_name"), "status": tool.get("status")}
                            for turn in trace.get("turns", []) for tool in turn.get("tool_calls", [])]
            row["trace_available"] = bool(trace.get("turns"))
        except Exception as error:
            row["trace_available"] = False
            row["audit_error"] = str(error)
        row["failed_tools"] = sum(str(tool["status"]).upper() == "FAILED" for tool in row.get("tools", []))
        row["answer_complete"] = advice_complete(row.get("answer", []))
        row["passed"] = row["success"] and row["trace_available"] and row["failed_tools"] == 0 and row["answer_complete"]
        rows.append(row)
        print(json.dumps({key: row[key] for key in ("passed", "latency_s", "model_calls", "failed_tools", "answer_complete")}), flush=True)
    result = {"label": args.label, "passed": all(row["passed"] for row in rows), "results": rows}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
