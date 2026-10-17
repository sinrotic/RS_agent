"""比较同一最终回答请求的 JSON 排版提示；不执行生成的工具调用。"""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path

from benchmark_core import metrics
from replay import replay


ROOT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:18082/v1"
INSTRUCTION = "工具调用参数使用单行紧凑 JSON，不缩进，不插入排版换行；字符串内的必要空格和内容保持完整。"


if __name__ == "__main__":
    before = metrics(BASE)
    if before.get("num_requests_running") or before.get("num_requests_waiting"):
        raise RuntimeError("模型有请求，暂不测排版优化")
    original = json.loads((ROOT / "replay-payloads.private.json").read_text())
    compact = copy.deepcopy(original)
    for record in compact:
        record["payload"]["messages"][0]["content"] += "\n" + INSTRUCTION
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "instruction": INSTRUCTION,
              "baseline": replay(BASE, original), "compact": replay(BASE, compact),
              "scope": "真实测试请求的模型直连排版对照，不执行工具，不代表完整业务。"}
    (ROOT / "format-comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({name: [(r["profile"], r["repeat"], r["elapsed_ms"], r["usage"]["completion_tokens"]) for r in report[name]]
                      for name in ("baseline", "compact")}, ensure_ascii=False))
