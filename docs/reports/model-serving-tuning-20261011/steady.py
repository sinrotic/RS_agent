"""分开记录首次批次与形状预热后的短工具调用，避免把 JIT 当作稳态速度。"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time

from benchmark_core import measure, payload


def append_steady(artifact: Path, base_url: str) -> None:
    result = {}
    for concurrency in (1, 4, 8):
        rounds = []
        for repeat in range(4):
            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = [executor.submit(measure, base_url, payload("qwen35-4b", tool=True),
                                           f"steady_tool_c{concurrency}") for _ in range(concurrency)]
                records = [future.result() for future in futures]
            rounds.append({"repeat": repeat, "warmup": repeat == 0,
                           "batch_seconds": round(time.perf_counter()-started, 6), "records": records})
        result[str(concurrency)] = rounds
    report = json.loads(artifact.read_text())
    report["steady_tool_rounds"] = result
    artifact.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
