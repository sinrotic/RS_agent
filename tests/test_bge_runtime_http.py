"""模型 HTTP 契约；使用轻量运行时替身，不加载 GPU 模型。"""
import importlib.util
import json
import threading
import types
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path


def test_reranker_preserves_candidate_ids_and_reports_missing_capability():
    path = Path(__file__).resolve().parents[1] / "java_agent/deploy/remote/model/bge_m3_embedding_server.py"
    spec = importlib.util.spec_from_file_location("bge_runtime_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Runtime:
        reranker = None
        model_path, device, dimension = "test", "cpu", 1024

        def rank(self, query, texts):
            assert query == "headphones"
            assert texts == ["first", "second"]
            return [0.1, 0.9]

    handler = type("Handler", (module.EmbeddingRequestHandler,), {"runtime": Runtime()})
    server = module.BgeHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"

    def request_rank():
        body = {"request_id": "request", "inputs": {"query": "headphones", "candidates": [
            {"item_id": "REAL-A#0", "text": "first"}, {"item_id": "REAL-B#1", "text": "second"}
        ]}, "options": {"top_k": 1}}
        return urllib.request.urlopen(urllib.request.Request(
            url + "/internal/model/rank", json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=3)

    try:
        try:
            request_rank()
            raise AssertionError("missing reranker must return 503")
        except urllib.error.HTTPError as error:
            assert error.code == 503
        handler.runtime.reranker = object()
        with request_rank() as response:
            payload = json.load(response)
        assert payload["items"] == [{"item_id": "REAL-B#1", "rank": 1, "score": 0.9, "metadata": {}}]
        with urllib.request.urlopen(url + "/health", timeout=3) as response:
            assert json.load(response)["capabilities"] == ["embed", "rank"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_larger_rerank_batch_retries_same_pairs_on_allocator_oom(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "java_agent/deploy/remote/model/bge_m3_embedding_server.py"
    spec = importlib.util.spec_from_file_location("bge_runtime_batch_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    class OutOfMemoryError(RuntimeError):
        pass
    cleaned = []
    monkeypatch.setitem(__import__("sys").modules, "torch", types.SimpleNamespace(cuda=types.SimpleNamespace(
        OutOfMemoryError=OutOfMemoryError, empty_cache=lambda: cleaned.append(True))))
    batches = []
    class Reranker:
        def predict(self, pairs, batch_size, show_progress_bar):
            assert pairs == [("query", "first"), ("query", "second")]
            batches.append(batch_size)
            if batch_size > 8:
                raise OutOfMemoryError("limited probe memory")
            return [.1, .9]
    runtime = module.EmbeddingRuntime.__new__(module.EmbeddingRuntime)
    runtime.lock, runtime.reranker, runtime.rerank_batch_size = threading.Lock(), Reranker(), 64
    assert runtime.rank("query", ["first", "second"]) == [.1, .9]
    assert batches == [64, 32, 16, 8]
    assert len(cleaned) == 3


def test_runtime_rejects_unsupported_gpu_settings_before_loading_models():
    path = Path(__file__).resolve().parents[1] / "java_agent/deploy/remote/model/bge_m3_embedding_server.py"
    spec = importlib.util.spec_from_file_location("bge_runtime_settings_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import pytest
    for kwargs in ({"dtype": "float16"}, {"gpu_memory_fraction": .1}, {"rerank_batch_size": 0}):
        with pytest.raises(ValueError):
            module.EmbeddingRuntime("not-loaded", "cpu", **kwargs)
