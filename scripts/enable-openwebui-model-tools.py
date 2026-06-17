#!/usr/bin/env python3
import json
import os
import sqlite3
import time


DB_PATH = os.environ.get(
    "OPEN_WEBUI_DB",
    os.path.join(os.environ.get("WORKSPACE", "/workspace"), "open-webui-data", "webui.db"),
)

TOOL_ID = os.environ.get("OPEN_WEBUI_TOOL_ID", "server:web_image_tools")

MODELS = [
    {
        "id": "AEON-7/Gemma-4-26B-A4B-it-Uncensored-NVFP4",
        "name": "AEON Gemma4 Web Tools",
        "description": "Gemma4 with Web + Image + Video Tools enabled by default.",
        "tags": ["tools", "gemma4"],
    },
    {
        "id": "lyf/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-NVFP4",
        "name": "Qwen3.6 Web Tools",
        "description": "Qwen3.6 NVFP4 with Web + Image + Video Tools enabled by default.",
        "tags": ["tools", "qwen3.6"],
    },
]


def upsert_model(cur: sqlite3.Cursor, model: dict, now: int) -> None:
    params = {"function_calling": "native"}
    meta = {
        "description": model["description"],
        "toolIds": [TOOL_ID],
        "capabilities": {
            "vision": True,
            "file_upload": True,
            "web_search": True,
            "image_generation": False,
            "code_interpreter": False,
            "function_calling": True,
            "builtin_tools": True,
        },
        "tags": [{"name": tag} for tag in model["tags"]],
    }

    cur.execute("select user_id, created_at from model where id=?", (model["id"],))
    existing = cur.fetchone()
    user_id = existing[0] if existing else None
    created_at = existing[1] if existing and existing[1] else now

    cur.execute(
        """
        insert into model (id,user_id,base_model_id,name,params,meta,updated_at,created_at,is_active)
        values (?,?,?,?,?,?,?,?,1)
        on conflict(id) do update set
          name=excluded.name,
          params=excluded.params,
          meta=excluded.meta,
          updated_at=excluded.updated_at,
          is_active=1
        """,
        (
            model["id"],
            user_id,
            None,
            model["name"],
            json.dumps(params, ensure_ascii=False),
            json.dumps(meta, ensure_ascii=False),
            now,
            created_at,
        ),
    )


def main() -> None:
    if not os.path.exists(DB_PATH):
        raise SystemExit(f"Open WebUI DB not found: {DB_PATH}")

    now = int(time.time())
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.cursor()
        for model in MODELS:
            upsert_model(cur, model, now)
            print(f"enabled tools for {model['id']}")
        con.commit()
    finally:
        con.close()

    print("restart Open WebUI for changes to apply")


if __name__ == "__main__":
    main()
