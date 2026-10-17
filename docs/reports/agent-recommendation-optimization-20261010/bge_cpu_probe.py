"""测真实 BGE CPU 推理成本；不将合成商品文本当作完整业务压测。"""
import argparse
import importlib.util
import json
import os
import resource
import time
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--embedding", required=True)
    parser.add_argument("--reranker", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    import torch
    torch.set_num_threads(4)
    torch.set_num_interop_threads(2)
    spec = importlib.util.spec_from_file_location("bge_runtime_probe", args.runtime)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    started = time.perf_counter()
    runtime = module.EmbeddingRuntime(args.embedding, "cpu", args.reranker)
    load_seconds = time.perf_counter() - started
    rows = []
    for index, count in enumerate((8, 32, 96)):
        query = f"推荐预算 {200 + index * 50} 美元以内的双肩包"
        texts = [f"Backpack item {i}. Category: backpacks. Price: {30 + i}. "
                 "Laptop compartment and adjustable shoulder straps." for i in range(count)]
        started = time.perf_counter()
        runtime.encode([query], normalize=True, batch_size=1)
        embed_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        scores = runtime.rank(query, texts)
        rank_ms = (time.perf_counter() - started) * 1000
        rows.append({"candidates": count, "embedding_ms": embed_ms, "rerank_ms": rank_ms,
                     "combined_ms": embed_ms + rank_ms, "scores": len(scores)})
        print(json.dumps(rows[-1]), flush=True)
    result = {"device": "cpu", "torch_threads": 4, "load_seconds": load_seconds, "samples": rows,
              "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
              "scope": "真实本地权重的 CPU 分段推理，合成短商品文本，不含业务服务/数据库/网络",
              "gpu_used": False}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
