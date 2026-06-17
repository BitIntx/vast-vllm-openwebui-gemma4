#!/usr/bin/env python3
import glob
import os
from pathlib import Path


WORKSPACE = os.environ.get("WORKSPACE_DIR") or os.environ.get("WORKSPACE") or "/workspace"
MIDDLEWARE_PATH = os.environ.get("OPEN_WEBUI_MIDDLEWARE")


def find_middleware() -> Path:
    if MIDDLEWARE_PATH:
        return Path(MIDDLEWARE_PATH)

    pattern = os.path.join(
        WORKSPACE,
        "venvs",
        "webui",
        "lib",
        "python*",
        "site-packages",
        "open_webui",
        "utils",
        "middleware.py",
    )
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise SystemExit(f"Open WebUI middleware.py not found with pattern: {pattern}")
    return Path(matches[-1])


def main() -> None:
    path = find_middleware()
    text = path.read_text()

    patched = """    tool_ids = form_data.pop('tool_ids', None)
    if not tool_ids:
        tool_ids = model.get('info', {}).get('meta', {}).get('toolIds', None)
    terminal_id = form_data.pop('terminal_id', None)
"""
    if patched in text:
        print(f"already patched: {path}")
        return

    original = """    tool_ids = form_data.pop('tool_ids', None)
    terminal_id = form_data.pop('terminal_id', None)
"""
    if original not in text:
        raise SystemExit("target snippet not found; Open WebUI middleware may have changed")

    path.write_text(text.replace(original, patched, 1))
    print(f"patched model default tools fallback: {path}")
    print("restart Open WebUI for changes to apply")


if __name__ == "__main__":
    main()
