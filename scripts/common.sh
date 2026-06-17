#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "${REPO_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_DIR}/.env"
  set +a
fi

export WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
export HF_HOME="${HF_HOME:-${WORKSPACE_DIR}/hf-cache}"
export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-${HF_HOME}/hub}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-${HF_HOME}/hub}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-${HF_HOME}/transformers}"
export VLLM_CACHE_ROOT="${VLLM_CACHE_ROOT:-${WORKSPACE_DIR}/vllm-cache}"
export TMPDIR="${TMPDIR:-${WORKSPACE_DIR}/tmp}"

export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
export PATH="${CUDA_HOME}/bin:${PATH}"
export LD_LIBRARY_PATH="${CUDA_HOME}/lib64:${LD_LIBRARY_PATH:-}"

mkdir -p "${HF_HOME}" "${HUGGINGFACE_HUB_CACHE}" "${TRANSFORMERS_CACHE}" \
  "${VLLM_CACHE_ROOT}" "${TMPDIR}" "${WORKSPACE_DIR}/venvs" \
  "${OPEN_WEBUI_DATA_DIR:-${WORKSPACE_DIR}/open-webui-data}"

