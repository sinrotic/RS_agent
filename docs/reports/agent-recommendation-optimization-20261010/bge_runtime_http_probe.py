"""在临时 localhost 端口验证优化后的真实 BGE HTTP 推理；结束即关闭。"""
import argparse
import concurrent.futures
import importlib.util
import json
import os
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
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
    if free < total * .11 + 512 * 1024 ** 2:
        raise RuntimeError("insufficient GPU 1 probe memory")
    spec = importlib.util.spec_from_file_location("bge_optimized_runtime_probe", args.runtime)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime = module.EmbeddingRuntime(args.embedding, "cuda", args.reranker, dtype="float16",
                                      rerank_batch_size=64, gpu_memory_fraction=.11)
    class Handler(module.EmbeddingRequestHandler):
        def log_message(self, *_):
            pass
    Handler.runtime = runtime
    server = module.BgeHTTPServer(("127.0.0.1", 0), Handler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    url = f"http://127.0.0.1:{server.server_port}"
    texts = [f"Backpack item {i}. Category: backpacks. Price: {30 + i}. "
             "Laptop compartment and adjustable shoulder straps." for i in range(96)]
    def post(path, inputs):
        req = urllib.request.Request(url + path, json.dumps({"inputs": inputs}).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.load(response)
    def call(index, length=None):
        query = f"推荐{200 + index}美元以内的双肩包"
        started = time.perf_counter()
        embedding = post("/internal/model/embed", {"texts": [query]})
        if len(embedding["vectors"]) != 1:
            raise AssertionError("invalid query vector")
        actual_texts = texts if length is None else [(text * 20)[:length] for text in texts]
        rank = post("/internal/model/rank", {"query": query, "candidates": [
            {"item_id": f"item-{i}", "text": text} for i, text in enumerate(actual_texts)]})
        if {row["item_id"] for row in rank["items"]} != {f"item-{i}" for i in range(96)}:
            raise AssertionError("candidate identity or score count changed")
        return (time.perf_counter() - started) * 1000
    try:
        call(-1)
        singles = [call(index) for index in range(3)]
        barrier = threading.Barrier(8)
        def concurrent_call(index):
            barrier.wait(timeout=10)
            return call(100 + index)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as workers:
            concurrent_ms = list(workers.map(concurrent_call, range(8)))
        long_ms = call(1000, 1200)
        result = {"device": "GPU 1", "dtype": "float16", "rerank_batch_size": 64,
                  "single_ms": singles, "concurrent_8_ms": concurrent_ms,
                  "long_text_1200_chars_ms": long_ms,
                  "peak_allocated_mib": torch.cuda.max_memory_allocated() / 1024 ** 2,
                  "peak_reserved_mib": torch.cuda.max_memory_reserved() / 1024 ** 2,
                  "scope": "真实更新后的 BGE HTTP runtime、真实模型、临时端口、不同查询、未缓存、96个候选；不含业务召回、排序、持久化、浏览器及模型并行负载"}
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        server.shutdown()
        server.server_close()
        serving.join(timeout=3)


if __name__ == "__main__":
    main()
