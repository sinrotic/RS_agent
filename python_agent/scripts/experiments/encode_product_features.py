"""为商品残差实验生成固定版本的 BGE 缓存，不修改训练网络。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
import torch
from sentence_transformers import SentenceTransformer


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--model", default="/home/luo/RS_agent_java/data/models/BAAI/bge-m3")
    args = p.parse_args()
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "2":
        raise RuntimeError("reserve GPU 2")
    destination = args.data / "item_features.npy"
    if destination.exists():
        raise FileExistsError(destination)
    torch.cuda.set_per_process_memory_fraction(.5)
    started = time.perf_counter()
    model = SentenceTransformer(args.model, device="cuda", local_files_only=True)
    model.half(); model.max_seq_length = 256
    with (args.data / "items.jsonl").open() as stream:
        items = [json.loads(line) for line in stream]
    features = np.lib.format.open_memmap(destination, mode="w+", dtype="float32", shape=(len(items), 1024))
    for start in range(0, len(items), 2048):
        batch = items[start:start + 2048]
        encoded = model.encode([r["text"] for r in batch], batch_size=32, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        features[start:start + len(batch)] = encoded.astype("float32")
        features.flush()
        print("ENCODED", start + len(batch), "/", len(items), flush=True)
    result = {"model": args.model, "max_seq_length": 256, "batch_size": 32, "dtype": "fp16 inference, float32 cache", "item_count": len(items), "seconds": time.perf_counter() - started, "peak_cuda_allocated_gib": torch.cuda.max_memory_allocated() / 2**30, "item_text_sha256": hashlib.sha256((args.data / "items.jsonl").read_bytes()).hexdigest(), "feature_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (args.data / "encoding_metrics.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
