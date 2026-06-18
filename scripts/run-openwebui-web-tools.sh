#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

source "${WORKSPACE_DIR}/venvs/webui/bin/activate"

export TOOL_BACKEND="${TOOL_BACKEND:-ollama}"
export ENABLE_INSPECT_TOOLS="${ENABLE_INSPECT_TOOLS:-true}"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
export OLLAMA_INSPECT_MODEL="${OLLAMA_INSPECT_MODEL:-}"
export OLLAMA_INSPECT_MAX_IMAGE_MB="${OLLAMA_INSPECT_MAX_IMAGE_MB:-20}"
export OLLAMA_INSPECT_MAX_VIDEO_MB="${OLLAMA_INSPECT_MAX_VIDEO_MB:-200}"
export OLLAMA_INSPECT_MAX_IMAGE_SIDE="${OLLAMA_INSPECT_MAX_IMAGE_SIDE:-1024}"

export VLLM_BASE_URL="${VLLM_BASE_URL:-${OPENAI_API_BASE_URL:-http://127.0.0.1:8000/v1}}"
export VLLM_API_KEY="${VLLM_API_KEY:-${SERVE_API_KEY:-sk-test}}"
export SERVE_MODEL="${SERVE_MODEL:-AEON-7/Gemma-4-26B-A4B-it-Uncensored-NVFP4}"

cd "${REPO_DIR}/tools/openwebui-web-tools"

exec python -m uvicorn app:app \
  --host "${TOOLS_HOST:-127.0.0.1}" \
  --port "${TOOLS_PORT:-17071}" \
  --proxy-headers
