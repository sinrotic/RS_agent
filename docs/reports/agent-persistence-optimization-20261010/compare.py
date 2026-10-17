"""同一真实环境中交替测量存储优化前后；不把冷启动混入预热结果。"""
import concurrent.futures
import json
from pathlib import Path
import probe

users = probe.accounts()
results = {"before_warm": [], "after_warm": [], "before_concurrent_8": [], "after_concurrent_8": []}
for index in range(8):
    routes = ("baseline", "fast") if index % 2 else ("fast", "baseline")
    for route in routes:
        key = "before_warm" if route == "baseline" else "after_warm"
        results[key].append(probe.one(users[0], "推荐鼠标", route, key + "-" + str(index)))
        (probe.ROOT / "comparison.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))

for route in ("baseline", "fast"):
    # 每个画像先预热；这些样本保留在单独文件，不计入稳态并发范围。
    warmups = [probe.one(user, "推荐鼠标", route, "profile-warmup") for user in users]
    (probe.ROOT / (route + "-profile-warmups.json")).write_text(json.dumps(warmups, ensure_ascii=False, indent=2))
    key = "before_concurrent_8" if route == "baseline" else "after_concurrent_8"
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results[key] = list(pool.map(lambda user: probe.one(user, "推荐鼠标", route, key), users))
    (probe.ROOT / "comparison.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))

for key, rows in results.items():
    assert len(rows) == 8 and all(row["response"] and not row["error"] for row in rows), key
    times = sorted(row["complete_with_catalog_ms"] for row in rows)
    print(key, "n=", len(times), "min=", times[0], "median=", (times[3] + times[4]) / 2, "max=", times[-1], flush=True)
