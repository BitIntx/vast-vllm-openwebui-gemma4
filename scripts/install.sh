#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

python3 -m venv "${WORKSPACE_DIR}/venvs/vllm"
"${WORKSPACE_DIR}/venvs/vllm/bin/python" -m pip install -U pip setuptools wheel
"${WORKSPACE_DIR}/venvs/vllm/bin/pip" install -U "vllm==0.23.0" openai --no-cache-dir

python3 -m venv "${WORKSPACE_DIR}/venvs/webui"
"${WORKSPACE_DIR}/venvs/webui/bin/python" -m pip install -U pip setuptools wheel
"${WORKSPACE_DIR}/venvs/webui/bin/pip" install open-webui --no-cache-dir

echo "Install complete."

