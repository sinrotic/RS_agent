"""GPU 1 的临时隔离测量；保留原服务，限制 PyTorch 显存，不冒充业务验收。"""
import argparse
import concurrent.futures
import importlib.util
import json
import os
import time
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"


def main():
    parser = argparse.ArgumentParser()
    for name in ("runtime", "embedding", "reranker", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    import torch
    torch.set_num_threads(4)
    torch.set_num_interop_threads(2)
    free, total = torch.cuda.mem_get_info()
    allocator_fraction = .11
    print(json.dumps({"free_mib_after_cuda_init": free / 1024 ** 2,
                      "allocator_budget_mib": total * allocator_fraction / 1024 ** 2}), flush=True)
    if free < total * allocator_fraction + 512 * 1024 ** 2:
        raise RuntimeError("GPU 1 free memory is below the probe budget")
    torch.cuda.set_per_process_memory_fraction(allocator_fraction)
    spec = importlib.util.spec_from_file_location("bge_runtime_probe", args.runtime)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime = module.EmbeddingRuntime(args.embedding, "cpu", args.reranker)
    query = "推荐200美元以内的双肩包"
    texts = [f"Backpack item {i}. Category: backpacks. Price: {30 + i}. "
             "Laptop compartment and adjustable shoulder straps." for i in range(96)]
    reference_vector = runtime.encode([query], normalize=True, batch_size=1)[0]
    reference_scores = runtime.rank(query, texts)
    # Convert on CPU first, avoiding temporary full-precision allocations on GPU.
    runtime.model.half().to("cuda")
    runtime.reranker.model.half().to("cuda")
    runtime.device = "cuda"
    runtime.rank(query, texts[:8])
    vector = runtime.encode([query], normalize=True, batch_size=1)[0]
    scores = runtime.rank(query, texts)
    a, b = torch.tensor(reference_vector), torch.tensor(vector)
    cosine = torch.nn.functional.cosine_similarity(a[None], b[None]).item()
    rows = []
    for count in (8, 32, 96):
        for repetition in range(3):
            started = time.perf_counter()
            runtime.encode([query + f"，请求{count}_{repetition}"], normalize=True, batch_size=1)
            embed_ms = (time.perf_counter() - started) * 1000
            started = time.perf_counter()
            runtime.rank(query + f"，请求{count}_{repetition}", texts[:count])
            rank_ms = (time.perf_counter() - started) * 1000
            rows.append({"candidates": count, "embedding_ms": embed_ms, "rerank_ms": rank_ms,
                         "combined_ms": embed_ms + rank_ms})
    def call(index):
        started = time.perf_counter()
        runtime.encode([query + f"，并发请求{index}"], normalize=True, batch_size=1)
        runtime.rank(query + f"，并发请求{index}", texts)
        return (time.perf_counter() - started) * 1000
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as workers:
        concurrent_ms = list(workers.map(call, range(8)))
    batch_samples = []
    for batch_size in (8, 32, 64):
        pairs = [(query + f"，批量请求{index}", text) for index in range(8) for text in texts]
        started = time.perf_counter()
        try:
            batch_scores = runtime.reranker.predict(pairs, batch_size=batch_size, show_progress_bar=False)
            batch_samples.append({"batch_size": batch_size, "pairs": len(pairs), "scores": len(batch_scores),
                                  "combined_rerank_ms": (time.perf_counter() - started) * 1000})
        except torch.cuda.OutOfMemoryError:
            batch_samples.append({"batch_size": batch_size, "status": "allocator_budget_exceeded"})
            torch.cuda.empty_cache()
    long_samples = []
    for text_length in (400, 1200):
        long_texts = [(text + " Adjustable straps, padded laptop compartment, polyester material.") * 20
                      for text in texts]
        long_texts = [text[:text_length] for text in long_texts]
        started = time.perf_counter()
        try:
            runtime.rank(query, long_texts)
            long_samples.append({"text_chars": text_length, "candidates": 96,
                                 "rerank_ms": (time.perf_counter() - started) * 1000})
        except torch.cuda.OutOfMemoryError:
            long_samples.append({"text_chars": text_length, "status": "allocator_budget_exceeded"})
            torch.cuda.empty_cache()
    result = {"device": "GPU 1", "dtype": "float16", "allocator_fraction_cap": allocator_fraction,
              "samples": rows, "concurrent_8_ms": concurrent_ms,
              "bulk_batch_samples": batch_samples, "long_text_samples": long_samples,
              "embedding_cosine_to_cpu_fp32": cosine,
              "max_score_difference_to_cpu_fp32": max(abs(x - y) for x, y in zip(reference_scores, scores)),
              "peak_allocated_mib": torch.cuda.max_memory_allocated() / 1024 ** 2,
              "peak_reserved_mib": torch.cuda.max_memory_reserved() / 1024 ** 2,
              "scope": "真实权重与现有推理锁，合成短商品文本；不含业务服务、数据库、网络和浏览器；小样本不是质量门禁"}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
