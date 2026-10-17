"""从 train-only 用户哈希抽样构造有界商品实验，官方 valid 目标不影响候选集合。"""
import argparse
import hashlib
import heapq
import json
from pathlib import Path
import time


def read(path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def key(value):
    return int(hashlib.sha256(("product-pilot-v3:" + value).encode()).hexdigest()[:16], 16)


def write(path, rows):
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--users", type=int, default=10000)
    p.add_argument("--extra-items", type=int, default=5000)
    p.add_argument("--eval-users", type=int, default=1000)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    manifest = json.loads((args.data / "manifest.json").read_text())
    cutoff = manifest["window_policy"]["splits"]["train"]["end_ms"]
    end = manifest["window_policy"]["splits"]["valid"]["end_ms"]
    valid_targets = {}
    for r in read(args.data / "canonical_interactions.valid.jsonl"):
        if r["label_binary"] != 1:
            continue
        if not cutoff <= r["timestamp"] < end:
            raise ValueError("valid outside declared window")
        uid = r["user_id"]
        candidate = (r["timestamp"], r["parent_asin"])
        if uid not in valid_targets or candidate < valid_targets[uid]:
            valid_targets[uid] = candidate
    heaps, eval_heap = [], []
    eligible = 0; lines = 0
    for r in read(args.data / "user_sequences.train.jsonl"):
        lines += 1
        ids = r["recent_positive_item_sequence"]
        ts = r["recent_positive_timestamp_sequence"]
        if len(ids) != len(ts):
            raise ValueError("sequence alignment mismatch")
        if len(ids) < 3:
            continue
        if not all(t < cutoff for t in ts):
            raise ValueError("future event in train sequence")
        eligible += 1
        value = (-key(r["user_id"]), r["user_id"], list(zip(ids, ts)))
        if r["user_id"] in valid_targets:
            if len(eval_heap) < args.eval_users:
                heapq.heappush(eval_heap, value)
            elif value[:2] > eval_heap[0][:2]:
                heapq.heapreplace(eval_heap, value)
        if len(heaps) < args.users:
            heapq.heappush(heaps, value)
        elif value[:2] > heaps[0][:2]:
            heapq.heapreplace(heaps, value)
    users = {uid: sorted(history, key=lambda x: (x[1], x[0])) for _, uid, history in heaps}
    eval_users = {uid: sorted(history, key=lambda x: (x[1], x[0])) for _, uid, history in eval_heap}
    required = {item for hist in list(users.values()) + list(eval_users.values()) for item, _ in hist}
    print("TRAIN_USERS", len(users), "history_items", len(required), flush=True)
    # 候选库只使用训练期历史和 train 商品哈希子集；不加入 valid 目标商品补齐覆盖。
    item_heap, retained = [], {}
    for r in read(args.data / "canonical_items.jsonl"):
        iid = r["parent_asin"]
        if iid in required:
            retained[iid] = r
        entry = (-key(iid), iid, r)
        if len(item_heap) < args.extra_items:
            heapq.heappush(item_heap, entry)
        elif entry[:2] > item_heap[0][:2]:
            heapq.heapreplace(item_heap, entry)
    retained.update({iid: r for _, iid, r in item_heap})
    if required - retained.keys():
        raise ValueError("training history missing metadata")
    item_ids = sorted(retained)
    indices = {iid: i for i, iid in enumerate(item_ids)}
    cleaned = []
    for iid in item_ids:
        r = retained[iid]
        facts = [{"field": "title_clean", "text": r.get("title_clean", "").strip()[:400]}]
        for field in ["features_text", "description_text"]:
            if r.get(field, "").strip():
                facts.append({"field": field, "text": r[field].strip()[:700]})
        cleaned.append({"index": indices[iid], "item_id": iid, "text": "\n".join(f["text"] for f in facts), "category": r.get("category", ""), "facts": facts})
    write(args.output / "items.jsonl", cleaned)
    # 对目标和历史均记录时间；后续绝不以 valid 行为刷新历史。
    train = []
    for uid, hist in users.items():
        known = sorted({indices[iid] for iid, _ in hist})
        per_user = []
        for offset, (iid, ts) in enumerate(hist[1:], 1):
            prefix = [(indices[j], t) for j, t in hist[:offset] if t < ts][-50:]
            if prefix:
                per_user.append({"user_hash": hashlib.sha256(uid.encode()).hexdigest(), "history": [j for j, _ in prefix], "history_ts": [t for _, t in prefix], "target": indices[iid], "target_ts": ts, "known_train_positives": known, "explicit_negatives": []})
        train.extend(per_user[-20:])
    valid = []
    for uid, (ts, iid) in sorted(valid_targets.items()):
        if uid not in eval_users:
            continue
        hist = eval_users[uid][-50:]
        if iid in {j for j, _ in hist}:
            raise ValueError("validation target repeats history item")
        valid.append({"user_hash": hashlib.sha256(uid.encode()).hexdigest(), "history": [indices[j] for j, _ in hist], "history_ts": [t for _, t in hist], "target": indices.get(iid, -1), "target_ts": ts, "known_train_positives": [indices[j] for j, _ in hist], "explicit_negatives": []})
    write(args.output / "rec_train.jsonl", train)
    write(args.output / "rec_valid.jsonl", valid)
    result = {"scope": "BOUNDED_TRAIN_CANDIDATES_OFFICIAL_TIME_VALID_NOT_FULL_CATALOG", "source": str(args.data), "train_user_selection": "bottom stable hash of train users with >=3 retained positive events; no valid information", "eval_user_selection": "bottom stable hash among train-eligible users with >=1 positive event in official valid; does not use target identity or coverage", "candidate_selection": "training-period histories of train/eval cohorts plus hash subset of train catalog; no validation targets added", "train_eval_user_overlap": len(users.keys() & eval_users.keys()), "train_sequence_rows": lines, "eligible_train_users": eligible, "sampled_users": len(users), "candidate_count": len(cleaned), "train_examples": len(train), "valid_users": len(valid), "covered_valid_targets": sum(r["target"] >= 0 for r in valid), "target_policy": "first positive in official valid among selected users; others outside this positive-event estimand", "train_cutoff": cutoff, "valid_end": end, "limitations": ["bounded candidate universe, missing targets retained as misses", "eval cohort requires a positive validation event; not all-user traffic", "source sequence truncation max50 means older positives unavailable for masking", "metadata retrospective snapshot", "source user-item dedup inherits upstream policy", "not production queryv2 comparison"], "seconds": time.perf_counter() - start}
    result["artifact_sha256"] = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in args.output.glob("*.jsonl")}
    (args.output / "data_manifest.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
