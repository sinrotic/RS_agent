#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/bge-runtime.env" ]]; then
  set -a
  source "$SCRIPT_DIR/bge-runtime.env"
  set +a
fi
BGE_M3_VENV="${BGE_M3_VENV:-/home/luo/RS_agent_remote/.venv}"
BGE_M3_MODEL_PATH="${BGE_M3_MODEL_PATH:-/home/luo/RS_agent_java/data/models/BAAI/bge-m3}"
BGE_M3_HOST="${BGE_M3_HOST:-172.21.0.1}"
BGE_M3_PORT="${BGE_M3_PORT:-18115}"
BGE_M3_DEVICE="${BGE_M3_DEVICE:-cuda}"
BGE_M3_DTYPE="${BGE_M3_DTYPE:-auto}"
BGE_RERANK_BATCH_SIZE="${BGE_RERANK_BATCH_SIZE:-8}"
if [[ "$BGE_M3_DEVICE" == "cpu" ]]; then
  CUDA_VISIBLE_DEVICES=""
else
  CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
fi

export CUDA_VISIBLE_DEVICES
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false

for _ in $(seq 1 60); do
  if ip -o address show | grep -Fq " $BGE_M3_HOST/"; then
    break
  fi
  sleep 5
done

if ! ip -o address show | grep -Fq " $BGE_M3_HOST/"; then
  echo "Embedding bind address did not become available: $BGE_M3_HOST" >&2
  exit 1
fi

RERANKER_ARGS=()
if [[ -n "${BGE_M3_GPU_MEMORY_FRACTION:-}" ]]; then
  RERANKER_ARGS+=(--gpu-memory-fraction "$BGE_M3_GPU_MEMORY_FRACTION")
fi
if [[ -n "${BGE_RERANKER_MODEL_PATH:-}" ]]; then
  RERANKER_ARGS+=(--reranker-path "$BGE_RERANKER_MODEL_PATH")
fi

exec "$BGE_M3_VENV/bin/python" \
  "$SCRIPT_DIR/bge_m3_embedding_server.py" \
  --model-path "$BGE_M3_MODEL_PATH" \
  --host "$BGE_M3_HOST" \
  --port "$BGE_M3_PORT" \
  --device "$BGE_M3_DEVICE" \
  --dtype "$BGE_M3_DTYPE" \
  --rerank-batch-size "$BGE_RERANK_BATCH_SIZE" \
  "${RERANKER_ARGS[@]}"
