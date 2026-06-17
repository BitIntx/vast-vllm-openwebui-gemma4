#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

source "${WORKSPACE_DIR}/venvs/webui/bin/activate"

export CUDA_VISIBLE_DEVICES=""
export DATA_DIR="${OPEN_WEBUI_DATA_DIR:-${WORKSPACE_DIR}/open-webui-data}"
export OPENAI_API_BASE_URL="${OPENAI_API_BASE_URL:-http://127.0.0.1:8000/v1}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-${SERVE_API_KEY:-sk-test}}"

exec open-webui serve \
  --host "${OPEN_WEBUI_HOST:-127.0.0.1}" \
  --port "${OPEN_WEBUI_PORT:-3000}"

