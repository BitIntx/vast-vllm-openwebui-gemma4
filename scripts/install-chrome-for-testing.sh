#!/usr/bin/env bash
set -euo pipefail

CHROME_ROOT="${OPENWEBUI_CHROME_ROOT:-${HOME}/.cache/openwebui-web-tools/chrome-for-testing}"
LIB_ROOT="${OPENWEBUI_CHROME_LIB_ROOT:-${HOME}/.local/chrome-libs}"
DEB_DIR="${TMPDIR:-/tmp}/openwebui-chrome-debs"

mkdir -p "${CHROME_ROOT}" "${LIB_ROOT}" "${DEB_DIR}"

python3 - <<'PY'
import json
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path

root = Path(os.environ["CHROME_ROOT"])
meta_url = "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"
with urllib.request.urlopen(meta_url, timeout=30) as response:
    data = json.load(response)
stable = data["channels"]["Stable"]
version = stable["version"]
url = next(item["url"] for item in stable["downloads"]["chrome"] if item["platform"] == "linux64")
target = root / version
exe = target / "chrome-linux64" / "chrome"
if not exe.exists():
    zip_path = root / f"chrome-linux64-{version}.zip"
    print(f"Downloading Chrome for Testing {version}: {url}")
    urllib.request.urlretrieve(url, zip_path)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(target)

for file_name in ("chrome", "chrome_crashpad_handler", "chrome_sandbox", "chrome-wrapper"):
    candidate = target / "chrome-linux64" / file_name
    if candidate.exists():
        candidate.chmod(0o755)

print(exe)
PY

if command -v apt-get >/dev/null 2>&1 && command -v dpkg-deb >/dev/null 2>&1; then
  cd "${DEB_DIR}"
  apt-get download \
    libatk1.0-0t64 \
    libatk-bridge2.0-0t64 \
    libcups2t64 \
    libasound2t64 \
    libcairo2 \
    libpango-1.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libatspi2.0-0t64 \
    libavahi-common3 \
    libavahi-client3 \
    libfontconfig1 \
    libxrender1 \
    libxcb-render0 \
    libpixman-1-0 \
    libthai0 \
    libharfbuzz0b \
    libxi6 \
    libxres1 \
    libdatrie1 \
    libgraphite2-3 \
    fontconfig \
    fontconfig-config \
    fonts-dejavu-core \
    fonts-dejavu-mono \
    fonts-liberation
  for deb in ./*.deb; do
    dpkg-deb -x "${deb}" "${LIB_ROOT}"
  done
fi

CHROME_PATH="$(find "${CHROME_ROOT}" -path '*/chrome-linux64/chrome' -type f | sort | tail -n 1)"
CHROME_LIBRARY_PATH="${LIB_ROOT}/usr/lib/x86_64-linux-gnu"

echo "Chrome executable: ${CHROME_PATH}"
echo "Chrome library path: ${CHROME_LIBRARY_PATH}"
echo "Set OPENWEBUI_CHROME_PATH=${CHROME_PATH}"
echo "Set OPENWEBUI_CHROME_LIBRARY_PATH=${CHROME_LIBRARY_PATH}"
