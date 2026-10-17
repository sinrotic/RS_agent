#!/usr/bin/env python3
"""从原始压测 JSON 生成中文指标汇总；不将筛选结果解释为生产容量。"""
import argparse
import csv
import json
import pathlib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    args = parser.parse_args()
    directory = pathlib.Path(args.directory)
    rows = []
    reports = []
    audits = {}
    for path in directory.glob("*tool-audit.json"):
        audit = json.loads(path.read_text(encoding="utf-8"))
        audits[pathlib.Path(audit["source"]).name] = audit
    for path in sorted(directory.glob("*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        if "phases" not in report:
            continue
        reports.append((path, report))
        for phase in report["phases"]:
            audit = audits.get(path.name)
            audited_rows = [row for row in audit["requests_detail"] if row["concurrency"] == phase["concurrency"]] if audit else []
            available = sum(row["trace_available"] for row in audited_rows)
            healthy = sum(row["trace_available"] and row.get("failed_tools", 0) == 0 for row in audited_rows)
            clean_rate = round(100 * healthy / phase["requests"], 2) if audited_rows else None
            rows.append({"file": path.name, "concurrency": phase["concurrency"],
                         "requests": phase["requests"], "successful": phase["successful"],
                         "success_rate": round(100 * phase["success_rate"], 2),
                         "p50_s": phase["p50_s"], "p95_s": phase["p95_s"], "p99_s": phase["p99_s"],
                         "first_answer_p95_s": phase["first_answer_p95_s"],
                         "successful_turns_per_s": phase["successful_turns_per_s"],
                         "passes": phase["passes"], "elapsed_s": phase["elapsed_s"],
                         "tool_audit_available": available if audit else None,
                         "tool_clean_rate": clean_rate})
    if not rows:
        raise RuntimeError("没有压测结果")
    with (directory / "summary.csv").open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    text = ["# Agent 并发实测指标汇总", "",
            "日期：2026-10-09。只统计实际请求结果，HTTP 200 不等于成功。", "",
            "通过条件：有非空可见回答、无 SSE error、以 FINAL_ANSWER 结束；该档成功率至少 99%，成功轮次 P95 ≤ 30 秒。",
            "延迟分位数仅基于成功请求；失败率独立列出，不能用失败的快速返回提高吞吐指标。吞吐为成功轮次/整档墙钟时间。", "",
            "轮次完成不代表所有工具成功。已审计档位另列工具无失败率，分母为该档全部请求；未审计档位标为未核验。工具记录中的初始 recommend_candidates 在本次测试中来自固定候选，不是在线召回。", "",
            "范围：当前 Java Agent + GPU 1 上本地 Qwen3.5-4B；内存会话与固定候选；不包含网关、真实推荐、Redis、MySQL、Scylla。每次请求使用新会话；重复轮次以屏障同时发起，等待该批全部结束再发下一批。", "",
            "## 每档结果", "",
            "| 原始文件 | 并发 | 完成/总数 | 完成率 | P50 秒 | P95 秒 | P99 秒 | 首回答 P95 秒 | 完成轮次/秒 | SSE/延迟通过 | 工具无失败率 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|"]
    for row in rows:
        clean = str(row['tool_clean_rate']) + "%" if row['tool_clean_rate'] is not None else "未核验"
        text.append(f"| [{row['file']}]({row['file']}) | {row['concurrency']} | {row['successful']}/{row['requests']} | {row['success_rate']}% | {row['p50_s']} | {row['p95_s']} | {row['p99_s']} | {row['first_answer_p95_s']} | {row['successful_turns_per_s']} | {'是' if row['passes'] else '否'} | {clean} |")
    text.extend(["", "## 资源采样", "", "每约 2 秒采样一次，峰值可能漏过更短的瞬时变化。", "",
                 "| 原始文件 | GPU 显存峰值 MiB | GPU 利用率均值 % | GPU 温度峰值 ℃ | Agent RSS 峰值 MiB | 模型执行峰值 | 模型排队峰值 |",
                 "|---|---:|---:|---:|---:|---:|---:|"])
    for path, report in reports:
        samples = [sample for sample in report.get("samples", []) if "error" not in sample]
        if not samples:
            continue
        peak = lambda key: max(sample.get(key, 0) for sample in samples)
        metric = lambda key: max(sample.get("model_metrics", {}).get(key, 0) for sample in samples)
        mean_util = round(sum(sample.get("utilization_pct", 0) for sample in samples) / len(samples), 1)
        text.append(f"| {path.name} | {peak('memory_mib')} | {mean_util} | {peak('temperature_c')} | {peak('agent_rss_mib')} | {metric('vllm:num_requests_running')} | {metric('vllm:num_requests_waiting')} |")
    text.extend(["", "## 判读限制", "",
                 "- 单档筛选只有少量批次；稳定性结论应优先查看 sustain 文件。没有进行小时级稳态、长会话、故障恢复或在线推荐容量验证。",
                 "- 测试使用温度 0、最多 1024 输出 token、prefix caching、strict 工具参数与禁用 thinking；真实输入长度、工具链和生成长度改变后，容量会变化。",
                 "- 首可见回答通常是完整 answer_block，不能等同于底层模型的首 token 延迟。",
                 "- 原模型上下文为 4096；兼容测试临时改为 16384。原配置失败和调整后的容量必须分开解释。",
                 "- 最后一档通过只能给出已测下界；某档失败也不能证明更高所有档位都失败。临界附近需要重复验证。", ""])
    text.extend(["- boundary-shared.json 包含已确认的其他 GPU 进程干扰；raised-sweep.json 的 128 档出现额外显存占用。这些数据不能直接与独占复测混合推断容量。",
                 "- comparison 文件全部出现 RAG 委派工具失败，耗时包含失败后的继续生成，属于依赖降级样本，不是正常长回答容量。", ""])
    (directory / "metrics.md").write_text("\n".join(text), encoding="utf-8")
    print(json.dumps({"reports": len(reports), "phases": len(rows),
                      "requests": sum(row["requests"] for row in rows),
                      "successful": sum(row["successful"] for row in rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
