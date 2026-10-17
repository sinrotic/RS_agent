#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VLLM_VENV="${VLLM_VENV:-/mnt/data/luo/venvs/rsagent-vllm}"
MODEL_PATH="${MODEL_PATH:-/mnt/data/luo/models/Qwen3.5-4B}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-qwen35-4b}"
HOST="${VLLM_HOST:-127.0.0.1}"
PORT="${VLLM_PORT:-18082}"
MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-16384}"
GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.85}"
VLLM_QUANTIZATION="${VLLM_QUANTIZATION:-auto}"
VLLM_QUANTIZATION_CONFIG="${VLLM_QUANTIZATION_CONFIG:-}"
VLLM_LANGUAGE_MODEL_ONLY="${VLLM_LANGUAGE_MODEL_ONLY:-false}"
VLLM_MAX_NUM_BATCHED_TOKENS="${VLLM_MAX_NUM_BATCHED_TOKENS:-}"
VLLM_MAX_NUM_SEQS="${VLLM_MAX_NUM_SEQS:-}"
VLLM_SPECULATIVE_CONFIG="${VLLM_SPECULATIVE_CONFIG:-}"
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-2}"
VLLM_USE_FLASHINFER_SAMPLER="${VLLM_USE_FLASHINFER_SAMPLER:-0}"
VLLM_ENABLE_AUTO_TOOL_CHOICE="${VLLM_ENABLE_AUTO_TOOL_CHOICE:-true}"
VLLM_TOOL_CALL_PARSER="${VLLM_TOOL_CALL_PARSER:-qwen3_xml}"
VLLM_ENFORCE_STRICT_TOOL_CALLING="${VLLM_ENFORCE_STRICT_TOOL_CALLING:-true}"
VLLM_STRUCTURED_OUTPUTS_BACKEND="${VLLM_STRUCTURED_OUTPUTS_BACKEND:-xgrammar}"
VLLM_JSON_COMPACT_OUTPUT="${VLLM_JSON_COMPACT_OUTPUT:-false}"
VLLM_STRUCTURED_OUTPUT_PROBE="${VLLM_STRUCTURED_OUTPUT_PROBE:-true}"
VLLM_EXTRA_WARMUP_CONCURRENCY="${VLLM_EXTRA_WARMUP_CONCURRENCY:-0}"
VLLM_PREFIX_KEEPALIVE="${VLLM_PREFIX_KEEPALIVE:-true}"
VLLM_KEEPALIVE_INTERVAL_SEC="${VLLM_KEEPALIVE_INTERVAL_SEC:-300}"
VLLM_KERNEL_WARMUP="${VLLM_KERNEL_WARMUP:-false}"
VLLM_KERNEL_WARMUP_BATCH_SIZES="${VLLM_KERNEL_WARMUP_BATCH_SIZES:-1 4 8 16}"
READY_FILE="${VLLM_READY_FILE:-/tmp/rs_agent_latency/vllm_qwen35_4b.ready}"

mkdir -p "$(dirname "$READY_FILE")"
rm -f "$READY_FILE"

if [[ ! "$MAX_MODEL_LEN" =~ ^[0-9]+$ ]] || (( MAX_MODEL_LEN < 16384 )); then
  echo "Agent 要求 VLLM_MAX_MODEL_LEN >= 16384，拒绝启动不兼容的上下文配置" >&2
  exit 2
fi

if [[ ! "$VLLM_EXTRA_WARMUP_CONCURRENCY" =~ ^(0|[1-9]|1[0-6])$ ]]; then
  echo "额外并发预热必须为 0 到 16，0 表示关闭" >&2
  exit 2
fi

if [[ "$VLLM_KERNEL_WARMUP" != "true" && "$VLLM_KERNEL_WARMUP" != "false" ]]; then
  echo "VLLM_KERNEL_WARMUP 必须为 true 或 false" >&2
  exit 2
fi

export CUDA_VISIBLE_DEVICES
export VLLM_USE_FLASHINFER_SAMPLER
export VLLM_ENFORCE_STRICT_TOOL_CALLING
export VLLM_BASE_URL="http://${HOST}:${PORT}/v1"
export VLLM_MODEL="$SERVED_MODEL_NAME"
export VLLM_PREFIX_KEEPALIVE
export VLLM_KEEPALIVE_INTERVAL_SEC
export VLLM_KERNEL_WARMUP
export VLLM_KERNEL_WARMUP_BATCH_SIZES
export PATH="${VLLM_VENV}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

VLLM_BIN="${VLLM_BIN:-${VLLM_VENV}/bin/vllm}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
WARMUP_SCRIPT="${WARMUP_SCRIPT:-${SCRIPT_DIR}/vllm_prefix_warmup.py}"
PROBE_SCRIPT="${PROBE_SCRIPT:-${SCRIPT_DIR}/vllm_structured_output_probe.py}"

if [[ ! -x "$VLLM_BIN" ]]; then
  echo "vLLM binary not found or not executable: $VLLM_BIN" >&2
  exit 1
fi

if [[ ! -f "$WARMUP_SCRIPT" ]]; then
  echo "warmup script not found: $WARMUP_SCRIPT" >&2
  exit 1
fi

if [[ "$VLLM_STRUCTURED_OUTPUT_PROBE" == "true" && ! -f "$PROBE_SCRIPT" ]]; then
  echo "structured-output probe not found: $PROBE_SCRIPT" >&2
  exit 1
fi

if [[ "$VLLM_ENFORCE_STRICT_TOOL_CALLING" != "true" && "$VLLM_STRUCTURED_OUTPUT_PROBE" == "true" ]]; then
  echo "strict tool enforcement is required for constrained-decoding readiness" >&2
  exit 1
fi

cleanup() {
  if [[ -n "${WARMUP_PID:-}" ]]; then
    kill "$WARMUP_PID" 2>/dev/null || true
  fi
  if [[ -n "${KEEPALIVE_PID:-}" ]]; then
    kill "$KEEPALIVE_PID" 2>/dev/null || true
  fi
  if [[ -n "${VLLM_PID:-}" ]]; then
    kill "$VLLM_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

STRUCTURED_OUTPUTS_CONFIG="{\"backend\":\"${VLLM_STRUCTURED_OUTPUTS_BACKEND}\"}"
if [[ "$VLLM_JSON_COMPACT_OUTPUT" == "true" ]]; then
  STRUCTURED_OUTPUTS_CONFIG="{\"backend\":\"${VLLM_STRUCTURED_OUTPUTS_BACKEND}\",\"disable_any_whitespace\":true}"
elif [[ "$VLLM_JSON_COMPACT_OUTPUT" != "false" ]]; then
  echo "VLLM_JSON_COMPACT_OUTPUT 必须为 true 或 false" >&2
  exit 2
fi

VLLM_ARGS=(
  serve "$MODEL_PATH"
  --host "$HOST"
  --port "$PORT"
  --served-model-name "$SERVED_MODEL_NAME"
  --trust-remote-code
  --enable-prefix-caching
  --max-model-len "$MAX_MODEL_LEN"
  --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION"
  --structured-outputs-config "$STRUCTURED_OUTPUTS_CONFIG"
)

if [[ "$VLLM_QUANTIZATION" != "auto" && -n "$VLLM_QUANTIZATION" ]]; then
  VLLM_ARGS+=(--quantization "$VLLM_QUANTIZATION")
fi

if [[ -n "$VLLM_QUANTIZATION_CONFIG" ]]; then
  VLLM_ARGS+=(--quantization-config "$VLLM_QUANTIZATION_CONFIG")
fi

if [[ "$VLLM_LANGUAGE_MODEL_ONLY" == "true" ]]; then
  VLLM_ARGS+=(--language-model-only)
elif [[ "$VLLM_LANGUAGE_MODEL_ONLY" != "false" ]]; then
  echo "VLLM_LANGUAGE_MODEL_ONLY 必须为 true 或 false" >&2
  exit 2
fi

for budget in "$VLLM_MAX_NUM_BATCHED_TOKENS" "$VLLM_MAX_NUM_SEQS"; do
  if [[ -n "$budget" && ( ! "$budget" =~ ^[0-9]+$ || "$budget" =~ ^0+$ ) ]]; then
    echo "模型批次限制必须为空或正整数" >&2
    exit 2
  fi
done
if [[ -n "$VLLM_MAX_NUM_BATCHED_TOKENS" ]]; then
  VLLM_ARGS+=(--max-num-batched-tokens "$VLLM_MAX_NUM_BATCHED_TOKENS")
fi
if [[ -n "$VLLM_MAX_NUM_SEQS" ]]; then
  VLLM_ARGS+=(--max-num-seqs "$VLLM_MAX_NUM_SEQS")
fi
if [[ -n "$VLLM_SPECULATIVE_CONFIG" ]]; then
  VLLM_ARGS+=(--speculative-config "$VLLM_SPECULATIVE_CONFIG")
fi

if [[ "$VLLM_ENABLE_AUTO_TOOL_CHOICE" == "true" ]]; then
  VLLM_ARGS+=(
    --enable-auto-tool-choice
    --tool-call-parser "$VLLM_TOOL_CALL_PARSER"
  )
fi

"$VLLM_BIN" "${VLLM_ARGS[@]}" &
VLLM_PID=$!

"$PYTHON_BIN" "$WARMUP_SCRIPT" --no-kernel-warmup &
WARMUP_PID=$!
wait "$WARMUP_PID"
unset WARMUP_PID
if [[ "$VLLM_STRUCTURED_OUTPUT_PROBE" == "true" ]]; then
  "$PYTHON_BIN" "$PROBE_SCRIPT" --timeout "${VLLM_PROBE_TIMEOUT_SEC:-30}" \
    --warmup-concurrency "${VLLM_WARMUP_CONCURRENCY:-8}" \
    --report-file "${VLLM_PROBE_REPORT_FILE:-${READY_FILE}.structured-output.json}"
  if (( VLLM_EXTRA_WARMUP_CONCURRENCY > 0 )); then
    # 保留原探针报告；额外覆盖常见突发形状，通过后才发布 ready。
    "$PYTHON_BIN" "$PROBE_SCRIPT" --timeout "${VLLM_PROBE_TIMEOUT_SEC:-30}" \
      --warmup-concurrency "$VLLM_EXTRA_WARMUP_CONCURRENCY" \
      --report-file "${READY_FILE}.extra-warmup.json"
  fi
fi
# 先覆盖部分缓存命中和解码批次，再补回真实前缀。仅启动执行，失败不发布 ready。
if [[ "$VLLM_KERNEL_WARMUP" == "true" || "$VLLM_EXTRA_WARMUP_CONCURRENCY" != "0" ]]; then
  "$PYTHON_BIN" "$WARMUP_SCRIPT" &
  WARMUP_PID=$!
  wait "$WARMUP_PID"
  unset WARMUP_PID
fi
touch "$READY_FILE"
echo "vLLM warmup and output validation complete; ready file: $READY_FILE"

if [[ "$VLLM_PREFIX_KEEPALIVE" == "true" ]]; then
  "$PYTHON_BIN" "$WARMUP_SCRIPT" --keepalive --skip-ready-wait --delay-after-warmup-sec 0 &
  KEEPALIVE_PID=$!
  echo "vLLM prefix keepalive started: pid=$KEEPALIVE_PID interval=${VLLM_KEEPALIVE_INTERVAL_SEC}s"
fi

wait "$VLLM_PID"
