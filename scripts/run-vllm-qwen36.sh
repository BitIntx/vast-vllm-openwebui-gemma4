#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

source "${WORKSPACE_DIR}/venvs/vllm/bin/activate"

export MAX_JOBS="${MAX_JOBS:-64}"
export NVCC_THREADS="${NVCC_THREADS:-64}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"

MODEL="${SERVE_MODEL:-lyf/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-NVFP4}"

exec vllm serve "${MODEL}" \
  --host "${SERVE_HOST:-127.0.0.1}" \
  --port "${SERVE_PORT:-8000}" \
  --dtype "${SERVE_DTYPE:-bfloat16}" \
  --kv-cache-dtype "${SERVE_KV_CACHE_DTYPE:-fp8}" \
  --gpu-memory-utilization "${SERVE_GPU_MEMORY_FRACTION:-0.90}" \
  --max-model-len "${SERVE_CONTEXT_LENGTH:-256K}" \
  --max-num-batched-tokens "${SERVE_BATCHED_TOKENS:-32768}" \
  --limit-mm-per-prompt "${SERVE_MM_LIMIT:-{\"image\":4,\"video\":1}}" \
  --default-chat-template-kwargs '{"enable_thinking":true}' \
  --reasoning-parser qwen3 \
  --tool-call-parser qwen3_xml \
  --enable-auto-tool-choice \
  --trust-remote-code \
  --enforce-eager \
  --api-key "${SERVE_API_KEY:-sk-test}"
