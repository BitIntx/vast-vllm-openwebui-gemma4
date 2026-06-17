#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

TARGET="http://${OPEN_WEBUI_HOST:-127.0.0.1}:${OPEN_WEBUI_PORT:-3000}"

if [[ -x /opt/instance-tools/bin/cloudflared ]]; then
  CLOUDFLARED=/opt/instance-tools/bin/cloudflared
else
  CLOUDFLARED="$(command -v cloudflared)"
fi

exec "${CLOUDFLARED}" tunnel --url "${TARGET}" --protocol http2

