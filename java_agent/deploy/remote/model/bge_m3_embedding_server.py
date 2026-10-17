#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


LOGGER = logging.getLogger("bge_m3_embedding_server")
MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_TEXTS_PER_REQUEST = 128


class BgeHTTPServer(ThreadingHTTPServer):
    # The default backlog of five can add TCP retransmission delays at eight callers.
    request_queue_size = 128


class EmbeddingRuntime:
    def __init__(self, model_path: str, device: str, reranker_path: str | None = None, *,
                 dtype: str = "auto", rerank_batch_size: int = 8,
                 gpu_memory_fraction: float | None = None) -> None:
        if dtype not in ("auto", "float16") or not 1 <= rerank_batch_size <= 64:
            raise ValueError("invalid dtype or rerank_batch_size")
        if dtype == "float16" and not device.startswith("cuda"):
            raise ValueError("float16 requires CUDA")
        if gpu_memory_fraction is not None:
            if not device.startswith("cuda") or not 0 < gpu_memory_fraction <= 1:
                raise ValueError("invalid CUDA memory fraction")
            import torch
            memory_device = torch.cuda.current_device() if device == "cuda" else device
            torch.cuda.set_per_process_memory_fraction(gpu_memory_fraction, memory_device)
        from sentence_transformers import SentenceTransformer

        self.model_path = model_path
        self.device = device
        self.dtype = dtype
        self.rerank_batch_size = rerank_batch_size
        load_device = "cpu" if dtype == "float16" else device
        self.model = SentenceTransformer(model_path, device=load_device, local_files_only=True)
        self.lock = threading.Lock()
        self.reranker = None
        if reranker_path:
            from sentence_transformers import CrossEncoder

            self.reranker = CrossEncoder(reranker_path, device=load_device, local_files_only=True)
        if dtype == "float16":
            # Avoid temporarily loading full-precision weights into a shared GPU.
            self.model.half().to(device)
            if self.reranker is not None:
                self.reranker.model.half().to(device)
        self.dimension = int(
            self.model.encode(
                ["embedding runtime warmup"],
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            ).shape[1]
        )

    def encode(self, texts: list[str], *, normalize: bool, batch_size: int) -> list[list[float]]:
        with self.lock:
            vectors = self.model.encode(
                texts,
                batch_size=batch_size,
                convert_to_numpy=True,
                normalize_embeddings=normalize,
                show_progress_bar=False,
            )
        return [[float(value) for value in vector] for vector in vectors]

    def rank(self, query: str, texts: list[str]) -> list[float]:
        if self.reranker is None:
            raise RuntimeError("reranker_not_configured")
        with self.lock:
            batch_size = self.rerank_batch_size
            while True:
                try:
                    scores = self.reranker.predict([(query, text) for text in texts], batch_size=batch_size, show_progress_bar=False)
                    break
                except RuntimeError as error:
                    import torch
                    if not isinstance(error, torch.cuda.OutOfMemoryError) or batch_size <= 8:
                        raise
                    batch_size = max(8, batch_size // 2)
                    torch.cuda.empty_cache()
                    LOGGER.warning("Reranker exceeded GPU budget; retrying all pairs with batch_size=%d", batch_size)
        return [float(score) for score in scores]


class EmbeddingRequestHandler(BaseHTTPRequestHandler):
    runtime: EmbeddingRuntime

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        self._write_json(
            HTTPStatus.OK,
            {
                "status": "UP",
                "model_path": self.runtime.model_path,
                "device": self.runtime.device,
                "dimension": self.runtime.dimension,
                "capabilities": ["embed"] + (["rank"] if self.runtime.reranker is not None else []),
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/internal/model/rank":
            self._rank()
            return
        if self.path != "/internal/model/embed":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        try:
            request = self._read_json()
            inputs = request.get("inputs")
            texts = inputs.get("texts") if isinstance(inputs, dict) else None
            if not isinstance(texts, list) or not texts or not all(isinstance(text, str) for text in texts):
                raise ValueError("inputs.texts must be a non-empty string list")
            if len(texts) > MAX_TEXTS_PER_REQUEST:
                raise ValueError(f"inputs.texts exceeds limit {MAX_TEXTS_PER_REQUEST}")

            options = request.get("options") if isinstance(request.get("options"), dict) else {}
            normalize = bool(options.get("normalize", True))
            batch_size = max(1, min(int(options.get("batch_size", 32)), 64))
            started = time.perf_counter()
            vectors = self.runtime.encode(texts, normalize=normalize, batch_size=batch_size)
            latency_ms = round((time.perf_counter() - started) * 1000)
            response_vectors = [
                {
                    "id": f"text_{index}",
                    "vector": vector,
                    "metadata": {"normalized": normalize},
                }
                for index, vector in enumerate(vectors)
            ]
            self._write_json(
                HTTPStatus.OK,
                {
                    "request_id": str(request.get("request_id") or ""),
                    "model_key": str(request.get("model_key") or "bge-m3"),
                    "model_version": "local",
                    "runtime": "sentence_transformers",
                    "latency_ms": latency_ms,
                    "vectors": response_vectors,
                    "usage": {"dimension": self.runtime.dimension, "count": len(response_vectors)},
                },
            )
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            LOGGER.warning(
                "Invalid embedding request: %s content_length=%s transfer_encoding=%s",
                exc,
                self.headers.get("Content-Length"),
                self.headers.get("Transfer-Encoding"),
            )
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Embedding request failed")
            self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "embedding_failed", "message": str(exc)})

    def _rank(self) -> None:
        if self.runtime.reranker is None:
            self._write_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "reranker_not_configured"})
            return
        try:
            request = self._read_json()
            inputs = request.get("inputs", {})
            if not isinstance(inputs, dict):
                raise ValueError("inputs must be an object")
            query, candidates = inputs.get("query"), inputs.get("candidates")
            if not isinstance(query, str) or not query.strip():
                raise ValueError("inputs.query must be non-empty")
            if not isinstance(candidates, list) or not 1 <= len(candidates) <= MAX_TEXTS_PER_REQUEST:
                raise ValueError("inputs.candidates must contain 1 to 128 entries")
            if any(not isinstance(item, dict) or not isinstance(item.get("item_id"), str)
                   or not item["item_id"] or not isinstance(item.get("text"), str) for item in candidates):
                raise ValueError("each candidate requires item_id and text")
            if len({item["item_id"] for item in candidates}) != len(candidates):
                raise ValueError("candidate item_id must be unique")
            options = request.get("options", {})
            if not isinstance(options, dict):
                raise ValueError("options must be an object")
            limit = max(1, min(int(options.get("top_k", len(candidates))), len(candidates)))
            started = time.perf_counter()
            scores = self.runtime.rank(query, [item["text"] for item in candidates])
            if len(scores) != len(candidates):
                raise RuntimeError("reranker returned an incorrect score count")
            order = sorted(range(len(candidates)), key=lambda index: (-scores[index], index))[:limit]
            self._write_json(HTTPStatus.OK, {
                "request_id": str(request.get("request_id") or ""),
                "model_key": str(request.get("model_key") or "bge-reranker-v2-m3"),
                "model_version": "local", "runtime": "sentence_transformers",
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "items": [{"item_id": candidates[index]["item_id"], "score": scores[index],
                           "rank": rank, "metadata": {}} for rank, index in enumerate(order, 1)],
                "usage": {"candidate_count": len(candidates)},
            })
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "message": str(exc)})
        except Exception:  # noqa: BLE001
            LOGGER.exception("Reranking request failed")
            self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "reranking_failed"})

    def _read_json(self) -> dict[str, Any]:
        transfer_encoding = self.headers.get("Transfer-Encoding", "").lower()
        if transfer_encoding == "chunked":
            body = self._read_chunked_body()
        else:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
                raise ValueError("invalid request body size")
            body = self.rfile.read(content_length)
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _read_chunked_body(self) -> bytes:
        body = bytearray()
        while True:
            size_line = self.rfile.readline().strip()
            if not size_line:
                raise ValueError("invalid chunked request body")
            chunk_size = int(size_line.split(b";", 1)[0], 16)
            if chunk_size == 0:
                while self.rfile.readline().strip():
                    pass
                break
            if len(body) + chunk_size > MAX_REQUEST_BYTES:
                raise ValueError("request body exceeds size limit")
            body.extend(self.rfile.read(chunk_size))
            if self.rfile.read(2) != b"\r\n":
                raise ValueError("invalid chunk terminator")
        return bytes(body)

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, message: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), message % args)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18115)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--reranker-path", default=None)
    parser.add_argument("--dtype", choices=("auto", "float16"), default="auto")
    parser.add_argument("--rerank-batch-size", type=int, default=8)
    parser.add_argument("--gpu-memory-fraction", type=float, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    LOGGER.info("Loading embedding model from %s on %s", args.model_path, args.device)
    EmbeddingRequestHandler.runtime = EmbeddingRuntime(args.model_path, args.device, args.reranker_path,
            dtype=args.dtype, rerank_batch_size=args.rerank_batch_size, gpu_memory_fraction=args.gpu_memory_fraction)
    server = BgeHTTPServer((args.host, args.port), EmbeddingRequestHandler)
    LOGGER.info(
        "Embedding runtime ready on http://%s:%s with dimension %s",
        args.host,
        args.port,
        EmbeddingRequestHandler.runtime.dimension,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
