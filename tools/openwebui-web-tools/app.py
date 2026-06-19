import os
import re
import base64
import io
import json
import time
import subprocess
import tempfile
import urllib.parse
import uuid
from html.parser import HTMLParser
from html import unescape
from pathlib import Path
from typing import Any

import imageio_ffmpeg
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field


APP_TITLE = "Open WebUI Web + Image + Video Tools"
DEFAULT_MODEL = "AEON-7/Gemma-4-26B-A4B-it-Uncensored-NVFP4"
DEFAULT_OLLAMA_INSPECT_MODEL = "tinyrick/Qwen3.6-35B-A3B-uncensored-heretic-vision-llmfan46:Q4_K_M-cpu4"
WEB_ONLY_TOOL_PATHS = {
    "/ollama_status",
    "/search_web",
    "/read_webpage",
    "/read_pdf",
    "/search_images",
    "/capture_webpage",
    "/resolve_media_url",
}
INSPECT_TOOL_PATHS = {
    "/inspect_image",
    "/inspect_image_deep",
    "/ocr_image",
    "/inspect_video",
}


app = FastAPI(
    title=APP_TITLE,
    description=(
        "OpenAPI tool server for Open WebUI. Provides web search, webpage reading, "
        "image search, media URL resolution, image inspection, and video inspection "
        "through a local Ollama or vLLM backend."
    ),
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _inspect_tools_enabled() -> bool:
    value = os.getenv("ENABLE_INSPECT_TOOLS", os.getenv("ENABLE_OLLAMA_INSPECT_TOOLS", "true"))
    return value.lower() in {"1", "true", "yes", "on"}


def _tool_backend() -> str:
    backend = os.getenv("TOOL_BACKEND", "ollama").strip().lower()
    if backend not in {"ollama", "vllm"}:
        return "ollama"
    return backend


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    allowed_tool_paths = WEB_ONLY_TOOL_PATHS | (INSPECT_TOOL_PATHS if _inspect_tools_enabled() else set())
    schema["paths"] = {
        path: methods
        for path, methods in schema.get("paths", {}).items()
        if path in allowed_tool_paths
    }
    if not _inspect_tools_enabled():
        for schema_name in ("InspectImageRequest", "InspectVideoRequest"):
            schema.get("components", {}).get("schemas", {}).pop(schema_name, None)

    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi


class WebSearchRequest(BaseModel):
    query: str = Field(..., description="Search query.")
    max_results: int = Field(5, ge=1, le=10, description="Maximum number of results.")


class ImageSearchRequest(BaseModel):
    query: str = Field(..., description="Image search query.")
    max_results: int = Field(5, ge=1, le=10, description="Maximum number of image results.")


class ReadWebpageRequest(BaseModel):
    url: str = Field(..., description="HTTP(S) webpage URL to fetch and summarize as text.")
    max_chars: int = Field(12000, ge=1000, le=50000, description="Maximum extracted text characters to return.")


class OllamaStatusRequest(BaseModel):
    include_logs: bool = Field(False, description="Include recent user-systemd logs for Ollama and related services.")
    log_lines: int = Field(80, ge=10, le=300, description="Maximum log lines per service when include_logs is true.")
    include_processes: bool = Field(True, description="Include local process memory/CPU details for Ollama-related processes.")


class ReadPdfRequest(BaseModel):
    url: str = Field(..., description="HTTP(S) PDF URL to fetch and extract.")
    max_pages: int = Field(20, ge=1, le=200, description="Maximum PDF pages to inspect.")
    max_chars: int = Field(50000, ge=1000, le=200000, description="Maximum extracted text characters to return.")
    password: str | None = Field(None, description="Optional PDF password.")
    extract_tables: bool = Field(True, description="Try to extract simple tables with PyMuPDF.")
    max_tables: int = Field(10, ge=0, le=50, description="Maximum tables to return.")
    max_table_rows: int = Field(40, ge=1, le=200, description="Maximum rows per extracted table.")
    ocr_if_no_text: bool = Field(False, description="Run EasyOCR on pages with little or no embedded text.")
    ocr_languages: list[str] = Field(default_factory=lambda: ["ko", "en"], description="EasyOCR languages used when OCR fallback is enabled.")
    ocr_max_pages: int = Field(3, ge=1, le=20, description="Maximum pages to OCR when OCR fallback is enabled.")
    ocr_dpi: int = Field(144, ge=72, le=240, description="Render DPI for OCR fallback.")


class CaptureWebpageRequest(BaseModel):
    url: str = Field(..., description="HTTP(S) webpage URL to render in a headless browser.")
    wait_until: str = Field("networkidle", pattern="^(load|domcontentloaded|networkidle)$", description="Page load state to wait for.")
    wait_ms: int = Field(1000, ge=0, le=10000, description="Extra milliseconds to wait after the load state.")
    timeout_ms: int = Field(45000, ge=5000, le=120000, description="Browser navigation timeout.")
    viewport_width: int = Field(1365, ge=320, le=3840, description="Browser viewport width.")
    viewport_height: int = Field(900, ge=240, le=2160, description="Browser viewport height.")
    full_page: bool = Field(False, description="Capture the full scrollable page instead of just the viewport.")
    max_text_chars: int = Field(20000, ge=1000, le=100000, description="Maximum rendered body text characters to return.")
    screenshot_max_side: int = Field(1800, ge=512, le=4096, description="Resize screenshot so its longest side is at most this many pixels.")
    include_screenshot_base64: bool = Field(False, description="Also return screenshot as a base64 data URL. This can make tool output large.")


class ResolveMediaUrlRequest(BaseModel):
    url: str = Field(..., description="Direct media URL or webpage URL to inspect for media candidates. This tool does not analyze media content.")
    media_type: str = Field(
        "video",
        pattern="^(video|image|audio|any)$",
        description="Preferred media type to resolve.",
    )
    max_results: int = Field(8, ge=1, le=20, description="Maximum candidate URLs to return.")


class InspectImageRequest(BaseModel):
    image_url: str = Field(..., description="Public image URL to inspect.")
    question: str = Field("Describe this image and answer any relevant question.", description="Question for the vision model.")
    model: str | None = Field(None, description="Vision model name. With Ollama, defaults to OLLAMA_INSPECT_MODEL or the first installed vision-capable model. With vLLM, defaults to the served model.")
    max_tokens: int = Field(4096, ge=64, le=8192, description="Maximum completion tokens.")
    enable_thinking: bool = Field(True, description="Enable deeper reasoning for image inspection when the backend supports it.")


class InspectImageDeepRequest(BaseModel):
    image_url: str = Field(..., description="Public image URL to inspect with overview plus zoomed crop tiles.")
    question: str = Field(
        "Analyze this image in detail. Include visible text, small objects, relationships, and uncertainty.",
        description="Question for the vision model.",
    )
    model: str | None = Field(None, description="Vision model name. With Ollama, defaults to OLLAMA_INSPECT_MODEL or the first installed vision-capable model.")
    max_tokens: int = Field(8192, ge=512, le=16384, description="Maximum completion tokens.")
    max_tiles: int = Field(8, ge=1, le=20, description="Maximum number of zoomed crop tiles to send after the overview image.")
    tile_max_side: int = Field(1536, ge=512, le=2048, description="Maximum long side in pixels for each zoomed crop tile.")
    overview_max_side: int = Field(2048, ge=512, le=3072, description="Maximum long side in pixels for the overview image.")
    enable_thinking: bool = Field(True, description="Enable deeper reasoning for image inspection when the backend supports it.")


class OcrImageRequest(BaseModel):
    image_url: str = Field(..., description="Public image URL to OCR.")
    languages: list[str] = Field(
        default_factory=lambda: ["ko", "en"],
        description="EasyOCR language codes, such as ['ko', 'en'] or ['en'].",
    )
    max_image_side: int = Field(3072, ge=512, le=4096, description="Maximum long side in pixels before OCR.")
    min_confidence: float = Field(0.2, ge=0.0, le=1.0, description="Minimum confidence for returned OCR lines.")
    paragraph: bool = Field(False, description="Group text into paragraphs instead of individual text boxes.")
    max_results: int = Field(120, ge=1, le=300, description="Maximum OCR boxes or paragraphs to return.")


class InspectVideoRequest(BaseModel):
    video_url: str = Field(
        ...,
        description=(
            "Direct video URL to analyze by sampling frames and sending them to the local Ollama vision model, such as mp4, webm, mov, or m4v. "
            "Use this after resolve_media_url returns a video candidate. Local URLs like http://127.0.0.1:9000/me.mp4 are supported."
        ),
    )
    question: str = Field("Describe this video and answer any relevant question.", description="Question for the vision model.")
    model: str | None = Field(None, description="Vision model name. With Ollama, defaults to OLLAMA_INSPECT_MODEL or the first installed vision-capable model. With vLLM, defaults to the served model.")
    max_tokens: int = Field(8192, ge=64, le=16384, description="Maximum completion tokens.")
    max_frames: int = Field(8, ge=1, le=16, description="Maximum video frames to sample and send to the vision model.")
    enable_thinking: bool = Field(True, description="Enable deeper reasoning for video inspection when the backend supports it.")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            )
        },
    )


async def _resolve_vllm_model(requested_model: str | None, base_url: str, api_key: str) -> str:
    if requested_model:
        return requested_model

    configured_model = os.getenv("SERVE_MODEL") or DEFAULT_MODEL
    try:
        async with _client() as client:
            res = await client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            res.raise_for_status()
        model_ids = [item.get("id") for item in res.json().get("data", []) if item.get("id")]
    except Exception:
        return configured_model

    if configured_model in model_ids:
        return configured_model
    if model_ids:
        return model_ids[0]
    return configured_model


def _vllm_error_detail(prefix: str, exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        body = exc.response.text.strip()
        if len(body) > 800:
            body = body[:800] + "...[truncated]"
        return f"{prefix}: HTTP {exc.response.status_code}: {body}"
    return f"{prefix}: {exc}"


def _ollama_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")


def _max_image_side() -> int:
    return int(os.getenv("OLLAMA_INSPECT_MAX_IMAGE_SIDE", "2048"))


def _max_image_bytes() -> int:
    return int(os.getenv("OLLAMA_INSPECT_MAX_IMAGE_MB", "50")) * 1024 * 1024


def _max_video_bytes() -> int:
    return int(os.getenv("OLLAMA_INSPECT_MAX_VIDEO_MB", "200")) * 1024 * 1024


def _max_pdf_bytes() -> int:
    return int(os.getenv("OPENWEBUI_TOOLS_MAX_PDF_MB", "100")) * 1024 * 1024


def _return_inspect_thinking() -> bool:
    return _env_bool("OLLAMA_INSPECT_RETURN_THINKING", "false")


def _run_local_command(cmd: list[str], timeout: float = 5.0) -> dict[str, Any]:
    try:
        result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "stdout": "", "stderr": ""}
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _systemctl_user_value(*args: str, timeout: float = 5.0) -> str | None:
    result = _run_local_command(["systemctl", "--user", *args], timeout=timeout)
    if not result["ok"]:
        return None
    return result["stdout"]


def _journalctl_user(service: str, lines: int) -> str:
    result = _run_local_command(
        ["journalctl", "--user", "-u", service, "--no-pager", "-n", str(lines)],
        timeout=8.0,
    )
    if result["ok"]:
        return result["stdout"]
    return result["stderr"] or result["stdout"]


def _bytes_summary(value: int | float | None) -> dict[str, Any] | None:
    if value is None:
        return None
    number = float(value)
    return {
        "bytes": int(number),
        "gib": round(number / 1024 / 1024 / 1024, 3),
    }


def _ollama_related_processes() -> list[dict[str, Any]]:
    try:
        import psutil
    except Exception:
        return []

    processes: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline", "memory_info", "cpu_percent", "create_time", "status"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            joined = " ".join(cmdline)
            name = proc.info.get("name") or ""
            if "ollama" not in name.lower() and "ollama" not in joined.lower():
                continue
            mem = proc.info.get("memory_info")
            processes.append(
                {
                    "pid": proc.info["pid"],
                    "name": name,
                    "cmdline": cmdline,
                    "status": proc.info.get("status"),
                    "rss": _bytes_summary(getattr(mem, "rss", None)),
                    "vms": _bytes_summary(getattr(mem, "vms", None)),
                    "cpu_percent_last_interval": proc.info.get("cpu_percent"),
                    "create_time": proc.info.get("create_time"),
                }
            )
        except Exception:
            continue
    return processes


def _local_media_dir() -> Path:
    configured = os.getenv("LOCAL_MEDIA_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "share" / "openwebui-web-tools" / "media"


def _local_media_url(filename: str) -> str:
    host = os.getenv("LOCAL_MEDIA_HOST", "127.0.0.1")
    port = os.getenv("LOCAL_MEDIA_PORT", "9000")
    return f"http://{host}:{port}/{urllib.parse.quote(filename)}"


def _save_local_media(content: bytes, suffix: str) -> dict[str, str]:
    media_dir = _local_media_dir()
    media_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{int(time.time())}-{uuid.uuid4().hex}{suffix}"
    path = media_dir / filename
    path.write_bytes(content)
    return {"path": str(path), "url": _local_media_url(filename), "filename": filename}


def _chrome_executable_path() -> str | None:
    configured = os.getenv("OPENWEBUI_CHROME_PATH")
    if configured and Path(configured).exists():
        return configured

    cache_root = Path.home() / ".cache" / "openwebui-web-tools" / "chrome-for-testing"
    if cache_root.exists():
        candidates = sorted(cache_root.glob("*/chrome-linux64/chrome"), reverse=True)
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

    for candidate in (
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def _chrome_library_path() -> str | None:
    configured = os.getenv("OPENWEBUI_CHROME_LIBRARY_PATH")
    if configured:
        return configured
    default = Path.home() / ".local" / "chrome-libs" / "usr" / "lib" / "x86_64-linux-gnu"
    return str(default) if default.exists() else None


def _chrome_runtime_root() -> Path:
    return Path(os.getenv("OPENWEBUI_CHROME_RUNTIME_ROOT", str(Path.home() / ".local" / "chrome-libs"))).expanduser()


def _apply_chrome_runtime_env(browser_env: dict[str, str]) -> None:
    lib_path = _chrome_library_path()
    if lib_path:
        browser_env["LD_LIBRARY_PATH"] = lib_path + (":" + browser_env["LD_LIBRARY_PATH"] if browser_env.get("LD_LIBRARY_PATH") else "")

    runtime_root = _chrome_runtime_root()
    fonts_conf = runtime_root / "etc" / "fonts" / "fonts.conf"
    if fonts_conf.exists():
        browser_env.setdefault("FONTCONFIG_PATH", str(fonts_conf.parent))
        browser_env.setdefault("FONTCONFIG_FILE", str(fonts_conf))
        browser_env.setdefault("FONTCONFIG_SYSROOT", str(runtime_root))
        xdg_share = str(runtime_root / "usr" / "share")
        browser_env["XDG_DATA_DIRS"] = xdg_share + (":" + browser_env["XDG_DATA_DIRS"] if browser_env.get("XDG_DATA_DIRS") else ":/usr/local/share:/usr/share")


def _compress_screenshot(png_bytes: bytes, max_side: int) -> tuple[bytes, dict[str, int]]:
    image = Image.open(io.BytesIO(png_bytes))
    original = {"width": image.width, "height": image.height}
    image.thumbnail((max_side, max_side))
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue(), {"original_width": original["width"], "original_height": original["height"], "width": image.width, "height": image.height}


async def _fetch_pdf_content(url: str) -> tuple[bytes, str, str]:
    _require_http_url(url)
    try:
        async with _client() as client:
            res = await client.get(url, timeout=httpx.Timeout(120.0, connect=10.0))
            res.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=400, detail=f"PDF fetch failed: HTTP {exc.response.status_code}: {exc.response.text[:300]}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"PDF fetch failed: {exc}") from exc

    content = res.content
    if len(content) > _max_pdf_bytes():
        raise HTTPException(status_code=413, detail=f"PDF is larger than {_max_pdf_bytes() // 1024 // 1024} MB")
    content_type = res.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type and "pdf" not in content_type and not content.lstrip().startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail=f"url must return PDF content. Got {content_type}")
    return content, str(res.url), content_type


def _extract_pdf(content: bytes, source_url: str, content_type: str, req: ReadPdfRequest) -> dict[str, Any]:
    try:
        import fitz
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"PyMuPDF is not installed or failed to import: {exc}") from exc

    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PDF could not be opened: {exc}") from exc

    try:
        if doc.needs_pass:
            if not req.password or not doc.authenticate(req.password):
                raise HTTPException(status_code=401, detail="PDF requires a valid password")

        metadata = {key: value for key, value in (doc.metadata or {}).items() if value}
        max_pages = min(req.max_pages, doc.page_count)
        remaining_chars = req.max_chars
        pages: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        ocr_pages_used = 0
        truncated = False

        for page_index in range(max_pages):
            if remaining_chars <= 0:
                truncated = True
                break
            page = doc.load_page(page_index)
            text = page.get_text("text") or ""
            ocr_used = False
            ocr_line_count = 0

            if req.ocr_if_no_text and len(text.strip()) < 40 and ocr_pages_used < req.ocr_max_pages:
                zoom = req.ocr_dpi / 72
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                image = Image.open(io.BytesIO(pix.tobytes("png")))
                ocr_req = OcrImageRequest(
                    image_url=source_url,
                    languages=req.ocr_languages,
                    max_image_side=3072,
                    paragraph=False,
                    max_results=120,
                )
                ocr_result = _ocr_image_with_easyocr(ocr_req, image)
                if ocr_result["text"].strip():
                    text = ocr_result["text"]
                    ocr_used = True
                    ocr_line_count = ocr_result["line_count"]
                    ocr_pages_used += 1

            page_text = _normalize_text(text)
            if len(page_text) > remaining_chars:
                page_text = page_text[:remaining_chars].rstrip() + "\n...[truncated]"
                truncated = True
                remaining_chars = 0
            else:
                remaining_chars -= len(page_text)

            pages.append(
                {
                    "page": page_index + 1,
                    "text": page_text,
                    "char_count": len(page_text),
                    "ocr_used": ocr_used,
                    "ocr_line_count": ocr_line_count,
                }
            )

            if req.extract_tables and len(tables) < req.max_tables:
                try:
                    found = page.find_tables()
                    for table_index, table in enumerate(getattr(found, "tables", []) or []):
                        if len(tables) >= req.max_tables:
                            break
                        rows = table.extract()[: req.max_table_rows]
                        tables.append(
                            {
                                "page": page_index + 1,
                                "table": table_index + 1,
                                "row_count_returned": len(rows),
                                "rows": rows,
                            }
                        )
                except Exception:
                    pass

        joined_text = "\n\n".join(f"[Page {page['page']}]\n{page['text']}" for page in pages if page["text"])
        return {
            "url": source_url,
            "content_type": content_type,
            "page_count": doc.page_count,
            "pages_returned": len(pages),
            "metadata": metadata,
            "text": joined_text,
            "pages": pages,
            "tables": tables,
            "truncated": truncated or max_pages < doc.page_count,
            "ocr_pages_used": ocr_pages_used,
        }
    finally:
        doc.close()


async def _capture_webpage(req: CaptureWebpageRequest) -> dict[str, Any]:
    _require_http_url(req.url)
    chrome_path = _chrome_executable_path()
    if not chrome_path:
        raise HTTPException(
            status_code=503,
            detail="No Chrome/Chromium executable found. Set OPENWEBUI_CHROME_PATH or install a browser.",
        )

    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Playwright is not installed or failed to import: {exc}") from exc

    browser_env = dict(os.environ)
    _apply_chrome_runtime_env(browser_env)

    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(
                executable_path=chrome_path,
                headless=True,
                env=browser_env,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-crash-reporter",
                ],
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Headless browser failed to launch: {exc}") from exc

        try:
            page = await browser.new_page(viewport={"width": req.viewport_width, "height": req.viewport_height})
            response = await page.goto(req.url, wait_until=req.wait_until, timeout=req.timeout_ms)
            if req.wait_ms:
                await page.wait_for_timeout(req.wait_ms)
            title = await page.title()
            final_url = page.url
            body_text = await page.evaluate("() => document.body ? (document.body.innerText || document.body.textContent || '') : ''")
            page_size = await page.evaluate(
                "() => ({width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight})"
            )
            screenshot = await page.screenshot(full_page=req.full_page, type="png")
        finally:
            await browser.close()

    screenshot, screenshot_size = _compress_screenshot(screenshot, req.screenshot_max_side)
    saved = _save_local_media(screenshot, ".png")
    result = {
        "url": req.url,
        "final_url": final_url,
        "status_code": response.status if response else None,
        "title": title,
        "viewport": {"width": req.viewport_width, "height": req.viewport_height},
        "page_size": page_size,
        "screenshot": {
            "url": saved["url"],
            "path": saved["path"],
            "filename": saved["filename"],
            **screenshot_size,
        },
        "text": _normalize_text(body_text, req.max_text_chars),
        "text_truncated": len(_normalize_text(body_text)) > req.max_text_chars,
        "next_tool": "inspect_image_deep",
        "note": "Pass screenshot.url to inspect_image_deep when visual analysis of the rendered page is needed.",
    }
    if req.include_screenshot_base64:
        result["screenshot"]["data_url"] = "data:image/png;base64," + base64.b64encode(screenshot).decode("ascii")
    return result


_EASYOCR_READERS: dict[tuple[str, ...], Any] = {}


def _get_easyocr_reader(languages: list[str]) -> Any:
    normalized = tuple(dict.fromkeys(lang.strip().lower() for lang in languages if lang.strip()))
    if not normalized:
        normalized = ("en",)
    if normalized not in _EASYOCR_READERS:
        try:
            import easyocr
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"EasyOCR is not installed or failed to import: {exc}") from exc
        _EASYOCR_READERS[normalized] = easyocr.Reader(list(normalized), gpu=False, verbose=False)
    return _EASYOCR_READERS[normalized]


def _ocr_image_with_easyocr(req: OcrImageRequest, image: Image.Image) -> dict[str, Any]:
    try:
        import numpy as np
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"NumPy is required for OCR: {exc}") from exc

    work = image.copy()
    work.thumbnail((req.max_image_side, req.max_image_side))
    if work.mode != "RGB":
        work = work.convert("RGB")

    scale_x = image.width / work.width if work.width else 1.0
    scale_y = image.height / work.height if work.height else 1.0
    reader = _get_easyocr_reader(req.languages)
    try:
        raw_results = reader.readtext(np.array(work), paragraph=req.paragraph)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"EasyOCR failed: {exc}") from exc

    lines: list[dict[str, Any]] = []
    for raw in raw_results:
        if len(raw) == 3:
            bbox, text, confidence = raw
        elif len(raw) == 2:
            bbox, text = raw
            confidence = None
        else:
            continue
        if confidence is not None and float(confidence) < req.min_confidence:
            continue
        points = [
            {"x": round(float(x) * scale_x), "y": round(float(y) * scale_y)}
            for x, y in bbox
        ]
        xs = [point["x"] for point in points]
        ys = [point["y"] for point in points]
        lines.append(
            {
                "text": str(text).strip(),
                "confidence": round(float(confidence), 4) if confidence is not None else None,
                "bbox": {
                    "left": min(xs),
                    "top": min(ys),
                    "right": max(xs),
                    "bottom": max(ys),
                },
                "points": points,
            }
        )

    lines = [line for line in lines if line["text"]]
    lines.sort(key=lambda item: (item["bbox"]["top"], item["bbox"]["left"]))
    lines = lines[: req.max_results]
    text = "\n".join(line["text"] for line in lines)
    return {
        "engine": "easyocr",
        "languages": list(dict.fromkeys(req.languages)),
        "image_size": {"width": image.width, "height": image.height},
        "ocr_size": {"width": work.width, "height": work.height},
        "line_count": len(lines),
        "text": text,
        "lines": lines,
    }


async def _resolve_ollama_model(requested_model: str | None) -> str:
    if requested_model:
        return requested_model

    configured_model = os.getenv("OLLAMA_INSPECT_MODEL")
    if configured_model:
        return configured_model

    try:
        async with _client() as client:
            res = await client.get(f"{_ollama_base_url()}/api/tags")
            res.raise_for_status()
        for item in res.json().get("models", []):
            if "vision" in item.get("capabilities", []):
                return item.get("model") or item.get("name") or DEFAULT_OLLAMA_INSPECT_MODEL
    except Exception:
        pass

    return DEFAULT_OLLAMA_INSPECT_MODEL


def _encode_image_bytes_for_ollama(content: bytes) -> str:
    try:
        image = Image.open(io.BytesIO(content))
        return _encode_pil_image_for_ollama(image, _max_image_side())
    except Exception:
        # Ollama accepts raw base64 image bytes too; keep the original when
        # Pillow cannot decode but the upstream URL still returned image data.
        pass

    return base64.b64encode(content).decode("ascii")


def _encode_pil_image_for_ollama(image: Image.Image, max_side: int, label: str | None = None) -> str:
    image = image.copy()
    image.thumbnail((max_side, max_side))
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    if image.mode == "L":
        image = image.convert("RGB")

    if label:
        draw = ImageDraw.Draw(image)
        pad = max(6, image.width // 160)
        text_bbox = draw.textbbox((0, 0), label)
        box_w = text_bbox[2] - text_bbox[0] + pad * 2
        box_h = text_bbox[3] - text_bbox[1] + pad * 2
        draw.rectangle((0, 0, min(image.width, box_w), min(image.height, box_h)), fill=(255, 255, 255))
        draw.rectangle((0, 0, image.width - 1, image.height - 1), outline=(255, 0, 0), width=max(2, image.width // 300))
        draw.text((pad, pad), label, fill=(0, 0, 0))

    out = io.BytesIO()
    image.save(out, format="JPEG", quality=88, optimize=True)
    return base64.b64encode(out.getvalue()).decode("ascii")


async def _fetch_image_content(image_url: str) -> bytes:
    _require_http_url(image_url, "image_url")
    try:
        async with _client() as client:
            res = await client.get(image_url, timeout=httpx.Timeout(60.0, connect=10.0))
            res.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"image_url fetch failed: HTTP {exc.response.status_code}: {exc.response.text[:300]}",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"image_url fetch failed: {exc}") from exc
    content_type = res.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type and not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail=f"image_url must return image content. Got {content_type}")
    if len(res.content) > _max_image_bytes():
        raise HTTPException(status_code=413, detail=f"image is larger than {_max_image_bytes() // 1024 // 1024} MB")
    return res.content


async def _fetch_image_for_ollama(image_url: str) -> str:
    return _encode_image_bytes_for_ollama(await _fetch_image_content(image_url))


async def _fetch_pil_image(image_url: str) -> Image.Image:
    content = await _fetch_image_content(image_url)
    try:
        image = Image.open(io.BytesIO(content))
        image.load()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"image_url could not be decoded as an image: {exc}") from exc
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    if image.mode == "L":
        image = image.convert("RGB")
    return image


def _choose_tile_grid(width: int, height: int, max_tiles: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        return 1, 1
    aspect = width / height
    best_cols, best_rows, best_score = 1, 1, float("-inf")
    for rows in range(1, max_tiles + 1):
        for cols in range(1, max_tiles + 1):
            tile_count = rows * cols
            if tile_count > max_tiles:
                continue
            grid_aspect = cols / rows
            score = tile_count * 100 - abs(grid_aspect - aspect)
            if score > best_score:
                best_cols, best_rows, best_score = cols, rows, score
    return best_cols, best_rows


def _build_image_tiles(
    image: Image.Image, max_tiles: int, tile_max_side: int
) -> tuple[list[str], list[dict[str, int]]]:
    width, height = image.size
    cols, rows = _choose_tile_grid(width, height, max_tiles)
    tiles: list[str] = []
    metadata: list[dict[str, int]] = []
    index = 1
    for row in range(rows):
        for col in range(cols):
            left = round(col * width / cols)
            upper = round(row * height / rows)
            right = round((col + 1) * width / cols)
            lower = round((row + 1) * height / rows)
            crop = image.crop((left, upper, right, lower))
            label = f"Tile {index} ({left},{upper})-({right},{lower})"
            tiles.append(_encode_pil_image_for_ollama(crop, tile_max_side, label=label))
            metadata.append(
                {
                    "tile": index,
                    "left": left,
                    "top": upper,
                    "right": right,
                    "bottom": lower,
                    "width": right - left,
                    "height": lower - upper,
                }
            )
            index += 1
    return tiles, metadata


async def _call_ollama_vision(
    *,
    model: str,
    prompt: str,
    images: list[str],
    max_tokens: int,
    timeout_seconds: float,
    enable_thinking: bool = True,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": images,
            }
        ],
        "stream": False,
        "think": enable_thinking and _env_bool("OLLAMA_INSPECT_ENABLE_THINKING", "true"),
        "options": {
            "num_predict": max_tokens,
            "temperature": 0.2,
        },
        "keep_alive": os.getenv("OLLAMA_INSPECT_KEEP_ALIVE", "1h"),
    }

    async def post_chat(chat_payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with _client() as client:
                res = await client.post(
                    f"{_ollama_base_url()}/api/chat",
                    json=chat_payload,
                    timeout=httpx.Timeout(timeout_seconds, connect=10.0),
                )
                res.raise_for_status()
        except Exception as exc:
            if isinstance(exc, httpx.HTTPStatusError):
                body = exc.response.text.strip()
                if len(body) > 800:
                    body = body[:800] + "...[truncated]"
                raise HTTPException(status_code=502, detail=f"Ollama vision call failed: HTTP {exc.response.status_code}: {body}") from exc
            raise HTTPException(status_code=502, detail=f"Ollama vision call failed: {exc}") from exc
        return res.json()

    data = await post_chat(payload)
    message = data.get("message", {})
    content = str(message.get("content") or "").strip()
    should_retry_without_thinking = (
        bool(payload["think"])
        and _env_bool("OLLAMA_INSPECT_RETRY_WITHOUT_THINKING", "true")
        and not content
        and data.get("done_reason") == "length"
    )
    if should_retry_without_thinking:
        retry_payload = dict(payload)
        retry_payload["think"] = False
        retry_data = await post_chat(retry_payload)
        retry_data["_thinking_retry"] = {
            "triggered": True,
            "reason": "empty_answer_after_thinking_length_limit",
            "first_done_reason": data.get("done_reason"),
            "first_eval_count": data.get("eval_count"),
            "first_eval_duration": data.get("eval_duration"),
        }
        return retry_data
    return data


async def _call_vllm_image_inspection(req: InspectImageRequest) -> dict[str, Any]:
    base_url = os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
    api_key = os.getenv("VLLM_API_KEY", "sk-test")
    model = await _resolve_vllm_model(req.model, base_url, api_key)
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": req.question},
                    {"type": "image_url", "image_url": {"url": req.image_url}},
                ],
            }
        ],
        "max_tokens": req.max_tokens,
        "temperature": 0.2,
        "chat_template_kwargs": {"enable_thinking": req.enable_thinking},
    }
    try:
        async with _client() as client:
            res = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=httpx.Timeout(180.0, connect=10.0),
            )
            res.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_vllm_error_detail("vLLM image inspection failed", exc)) from exc

    data = res.json()
    message = data.get("choices", [{}])[0].get("message", {})
    return {
        "backend": "vllm",
        "image_url": req.image_url,
        "question": req.question,
        "model": model,
        "reasoning": message.get("reasoning"),
        "answer": message.get("content"),
        "raw_finish_reason": data.get("choices", [{}])[0].get("finish_reason"),
    }


async def _call_vllm_video_inspection(req: InspectVideoRequest, video_metadata: dict[str, Any]) -> dict[str, Any]:
    base_url = os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
    api_key = os.getenv("VLLM_API_KEY", "sk-test")
    model = await _resolve_vllm_model(req.model, base_url, api_key)
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": req.question},
                    {"type": "video_url", "video_url": {"url": req.video_url}},
                ],
            }
        ],
        "max_tokens": req.max_tokens,
        "temperature": 0.2,
        "chat_template_kwargs": {"enable_thinking": req.enable_thinking},
    }
    try:
        async with _client() as client:
            res = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=httpx.Timeout(300.0, connect=10.0),
            )
            res.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_vllm_error_detail("vLLM video inspection failed", exc)) from exc

    data = res.json()
    message = data.get("choices", [{}])[0].get("message", {})
    return {
        "backend": "vllm",
        "video_url": req.video_url,
        "video_metadata": video_metadata,
        "question": req.question,
        "model": model,
        "reasoning": message.get("reasoning"),
        "answer": message.get("content"),
        "raw_finish_reason": data.get("choices", [{}])[0].get("finish_reason"),
    }


async def _download_media_to_temp(url: str, suffix: str, max_bytes: int) -> Path:
    _require_http_url(url)
    fd, path = tempfile.mkstemp(prefix="owui-media-", suffix=suffix)
    os.close(fd)
    target = Path(path)
    size = 0
    try:
        async with _client() as client:
            async with client.stream("GET", url, timeout=httpx.Timeout(120.0, connect=10.0)) as res:
                res.raise_for_status()
                with target.open("wb") as f:
                    async for chunk in res.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise HTTPException(status_code=413, detail=f"media is larger than {max_bytes // 1024 // 1024} MB")
                        f.write(chunk)
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


def _extract_frames_with_ffmpeg(video_path: Path, max_frames: int) -> list[str]:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory(prefix="owui-frames-") as frame_dir:
        output_pattern = str(Path(frame_dir) / "frame_%03d.jpg")
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"fps=1/5,scale='min({_max_image_side()},iw)':-2",
            "-frames:v",
            str(max_frames),
            output_pattern,
        ]
        result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        if result.returncode != 0:
            raise HTTPException(status_code=502, detail=f"ffmpeg frame extraction failed: {result.stderr.strip()}")

        frames = sorted(Path(frame_dir).glob("frame_*.jpg"))
        if not frames:
            raise HTTPException(status_code=502, detail="ffmpeg did not extract any video frames")

        return [_encode_image_bytes_for_ollama(frame.read_bytes()) for frame in frames]


class _ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.links: list[dict[str, str]] = []
        self.media: list[dict[str, str]] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr = {key.lower(): value or "" for key, value in attrs}
        if tag in {"script", "style", "noscript", "svg", "canvas"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            key = attr.get("property") or attr.get("name")
            content = attr.get("content")
            if key and content:
                self.meta[key.lower()] = content.strip()
        if tag == "a" and attr.get("href"):
            self.links.append({"text": "", "url": attr["href"]})
        if tag in {"video", "audio", "source", "img"}:
            src = attr.get("src") or attr.get("data-src")
            if src:
                kind = "image" if tag == "img" else "audio" if tag == "audio" else "video"
                self.media.append({"url": src, "type": attr.get("type") or kind, "source": tag})
        if tag in {"p", "br", "div", "section", "article", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag == "title":
            self._in_title = False
        if tag in {"p", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        value = data.strip()
        if not value:
            return
        if self._in_title:
            self.title_parts.append(value)
        self.text_parts.append(value)
        self.text_parts.append(" ")


def _clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _normalize_text(value: str, max_chars: int | None = None) -> str:
    lines = []
    for line in value.splitlines():
        cleaned = re.sub(r"[ \t]+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    text = "\n".join(lines)
    if max_chars is not None and len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n...[truncated]"
    return text


def _require_http_url(url: str, field_name: str = "url") -> str:
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail=f"{field_name} must start with http:// or https://")
    return url


def _decode_ddg_href(href: str) -> str:
    href = unescape(href)
    if "uddg=" not in href:
        return href
    parsed = urllib.parse.urlparse(href)
    qs = urllib.parse.parse_qs(parsed.query)
    if "uddg" in qs and qs["uddg"]:
        return qs["uddg"][0]
    return href


def _looks_like_direct_video_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    return path.endswith((".mp4", ".webm", ".mov", ".m4v"))


def _guess_media_type(url: str, content_type: str | None = None) -> str:
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    if ctype.startswith("video/"):
        return "video"
    if ctype.startswith("image/"):
        return "image"
    if ctype.startswith("audio/"):
        return "audio"
    path = urllib.parse.urlparse(url).path.lower()
    if path.endswith((".mp4", ".webm", ".mov", ".m4v", ".mkv", ".avi")):
        return "video"
    if path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")):
        return "image"
    if path.endswith((".mp3", ".wav", ".ogg", ".m4a", ".flac")):
        return "audio"
    if path.endswith((".m3u8", ".mpd")):
        return "video"
    return "unknown"


def _is_media_candidate(url: str, preferred: str = "any", content_type: str | None = None) -> bool:
    kind = _guess_media_type(url, content_type)
    if preferred == "any":
        return kind in {"video", "image", "audio"}
    return kind == preferred


def _absolute_url(base_url: str, candidate: str) -> str:
    return urllib.parse.urljoin(base_url, unescape(candidate).strip())


async def _fetch_url(url: str) -> tuple[httpx.Response, str]:
    _require_http_url(url)
    async with _client() as client:
        res = await client.get(url)
        res.raise_for_status()
    content_type = res.headers.get("content-type", "")
    return res, content_type


async def _validate_direct_video_url(url: str) -> dict[str, Any]:
    _require_http_url(url, "video_url")

    metadata: dict[str, Any] = {"content_type": None, "content_length": None, "validated_by": "extension"}
    if _looks_like_direct_video_url(url):
        return metadata

    try:
        async with _client() as client:
            res = await client.head(url)
            metadata["content_type"] = res.headers.get("content-type")
            metadata["content_length"] = res.headers.get("content-length")
            metadata["validated_by"] = "head"
            res.raise_for_status()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "video_url does not look like a direct mp4/webm/mov/m4v URL, "
                f"and HEAD validation failed: {exc}"
            ),
        ) from exc

    content_type = (metadata.get("content_type") or "").lower()
    if not content_type.startswith("video/"):
        raise HTTPException(
            status_code=400,
            detail=(
                "video_url must be a direct video file URL. "
                f"Got content-type: {metadata.get('content_type') or 'unknown'}"
            ),
        )
    return metadata


async def _extract_readable_webpage(url: str, max_chars: int) -> dict[str, Any]:
    res, content_type = await _fetch_url(url)
    if "html" not in content_type.lower() and not res.text.lstrip().startswith("<"):
        text = _normalize_text(res.text, max_chars)
        return {
            "url": str(res.url),
            "content_type": content_type,
            "title": "",
            "description": "",
            "text": text,
            "truncated": text.endswith("...[truncated]"),
            "links": [],
        }

    parser = _ReadableHTMLParser()
    parser.feed(res.text)
    title = _normalize_text(" ".join(parser.title_parts))
    description = parser.meta.get("description") or parser.meta.get("og:description") or ""
    text = _normalize_text("".join(parser.text_parts), max_chars)
    links = []
    seen = set()
    for link in parser.links:
        link_url = _absolute_url(str(res.url), link["url"])
        if link_url in seen:
            continue
        seen.add(link_url)
        links.append({"url": link_url})
        if len(links) >= 30:
            break
    return {
        "url": str(res.url),
        "content_type": content_type,
        "title": title,
        "description": description,
        "text": text,
        "truncated": text.endswith("...[truncated]"),
        "links": links,
    }


async def _resolve_media_candidates(url: str, preferred: str, max_results: int) -> dict[str, Any]:
    _require_http_url(url)
    direct: dict[str, Any] | None = None
    try:
        async with _client() as client:
            head = await client.head(url)
        head.raise_for_status()
        content_type = head.headers.get("content-type")
        content_length = head.headers.get("content-length")
        if _is_media_candidate(url, preferred, content_type):
            direct = {
                "url": str(head.url),
                "type": _guess_media_type(str(head.url), content_type),
                "content_type": content_type,
                "content_length": content_length,
                "source": "direct",
            }
    except Exception:
        direct = None
    if direct:
        return {
            "url": url,
            "resolved_url": direct["url"],
            "candidates": [direct],
            "next_tool": "inspect_video" if direct["type"] == "video" else "inspect_image" if direct["type"] == "image" else None,
            "note": (
                "The input is already a direct media URL. This tool only resolves URLs and does not inspect or play media. "
                "To answer questions about video content, call inspect_video with resolved_url."
            ),
        }

    res, content_type = await _fetch_url(url)
    if "html" not in content_type.lower() and _is_media_candidate(str(res.url), preferred, content_type):
        candidate = {
            "url": str(res.url),
            "type": _guess_media_type(str(res.url), content_type),
            "content_type": content_type,
            "content_length": res.headers.get("content-length"),
            "source": "direct-get",
        }
        return {
            "url": url,
            "resolved_url": candidate["url"],
            "candidates": [candidate],
            "next_tool": "inspect_video" if candidate["type"] == "video" else "inspect_image" if candidate["type"] == "image" else None,
            "note": (
                "The input resolved to a direct media URL. This tool only resolves URLs and does not inspect or play media. "
                "To answer questions about video content, call inspect_video with resolved_url."
            ),
        }

    parser = _ReadableHTMLParser()
    parser.feed(res.text)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_candidate(candidate_url: str, source: str, content_hint: str | None = None) -> None:
        absolute = _absolute_url(str(res.url), candidate_url)
        if absolute in seen:
            return
        if not _is_media_candidate(absolute, preferred, content_hint):
            return
        seen.add(absolute)
        candidates.append(
            {
                "url": absolute,
                "type": _guess_media_type(absolute, content_hint),
                "content_type": content_hint,
                "content_length": None,
                "source": source,
            }
        )

    meta_sources = {
        "og:video": "meta:og:video",
        "og:video:url": "meta:og:video:url",
        "og:video:secure_url": "meta:og:video:secure_url",
        "twitter:player": "meta:twitter:player",
        "og:image": "meta:og:image",
        "twitter:image": "meta:twitter:image",
    }
    for key, source in meta_sources.items():
        value = parser.meta.get(key)
        if value:
            add_candidate(value, source)

    for item in parser.media:
        add_candidate(item["url"], item["source"], item.get("type"))

    regex = re.compile(r'https?://[^"\'<>\s]+?\.(?:mp4|webm|mov|m4v|m3u8|mpd|jpg|jpeg|png|webp|gif|avif)(?:\?[^"\'<>\s]*)?', re.I)
    for match in regex.finditer(res.text):
        add_candidate(match.group(0), "html-regex")
        if len(candidates) >= max_results:
            break

    return {
        "url": url,
        "resolved_url": candidates[0]["url"] if candidates else None,
        "candidates": candidates[:max_results],
        "next_tool": (
            "inspect_video"
            if candidates and candidates[0]["type"] == "video"
            else "inspect_image"
            if candidates and candidates[0]["type"] == "image"
            else None
        ),
        "note": (
            "This tool only resolves direct media URLs and simple HTML media/meta tags; it does not inspect or play media. "
            "If resolved_url is a video, call inspect_video with resolved_url to answer questions about the video content. "
            "JavaScript-only players such as many YouTube/TikTok/X pages may not expose a direct file URL."
        ),
    }


async def _brave_web_search(query: str, max_results: int) -> list[dict[str, Any]]:
    key = os.getenv("BRAVE_SEARCH_API_KEY")
    if not key:
        return []
    async with _client() as client:
        res = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
        )
        res.raise_for_status()
    data = res.json()
    results = []
    for item in data.get("web", {}).get("results", [])[:max_results]:
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
                "source": "brave",
            }
        )
    return results


async def _duckduckgo_web_search(query: str, max_results: int) -> list[dict[str, Any]]:
    async with _client() as client:
        res = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
        res.raise_for_status()
    html = res.text
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
        re.S,
    )
    results = []
    for match in pattern.finditer(html):
        results.append(
            {
                "title": _clean_text(match.group("title")),
                "url": _decode_ddg_href(match.group("href")),
                "snippet": _clean_text(match.group("snippet")),
                "source": "duckduckgo",
            }
        )
        if len(results) >= max_results:
            break
    return results


async def _tavily_image_search(query: str, max_results: int) -> list[dict[str, Any]]:
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        return []
    async with _client() as client:
        res = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": key,
                "query": query,
                "max_results": max_results,
                "include_images": True,
                "include_image_descriptions": True,
            },
        )
        res.raise_for_status()
    data = res.json()
    images = data.get("images") or []
    results = []
    for item in images[:max_results]:
        if isinstance(item, str):
            results.append({"title": "", "image_url": item, "thumbnail_url": item, "source_url": "", "source": "tavily"})
        elif isinstance(item, dict):
            url = item.get("url") or item.get("image_url") or ""
            results.append(
                {
                    "title": item.get("description", ""),
                    "image_url": url,
                    "thumbnail_url": item.get("thumbnail_url", url),
                    "source_url": item.get("source_url", ""),
                    "source": "tavily",
                }
            )
    return results


async def _brave_image_search(query: str, max_results: int) -> list[dict[str, Any]]:
    key = os.getenv("BRAVE_SEARCH_API_KEY")
    if not key:
        return []
    async with _client() as client:
        res = await client.get(
            "https://api.search.brave.com/res/v1/images/search",
            params={"q": query, "count": max_results},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
        )
        res.raise_for_status()
    data = res.json()
    results = []
    for item in data.get("results", [])[:max_results]:
        props = item.get("properties", {}) or {}
        thumbnail = item.get("thumbnail", {}) or {}
        results.append(
            {
                "title": item.get("title", ""),
                "image_url": props.get("url") or item.get("url") or "",
                "thumbnail_url": thumbnail.get("src", ""),
                "source_url": item.get("url", ""),
                "source": "brave",
            }
        )
    return results


async def _duckduckgo_image_search(query: str, max_results: int) -> list[dict[str, Any]]:
    async with _client() as client:
        page = await client.get("https://duckduckgo.com/", params={"q": query, "iax": "images", "ia": "images"})
        page.raise_for_status()
        match = re.search(r"vqd=['\"]?([^'\"&]+)", page.text)
        if not match:
            return []
        vqd = match.group(1)
        res = await client.get(
            "https://duckduckgo.com/i.js",
            params={
                "q": query,
                "vqd": vqd,
                "o": "json",
                "l": "us-en",
                "p": "1",
            },
            headers={"Referer": str(page.url)},
        )
        res.raise_for_status()
    data = res.json()
    results = []
    for item in data.get("results", [])[:max_results]:
        results.append(
            {
                "title": item.get("title", ""),
                "image_url": item.get("image", ""),
                "thumbnail_url": item.get("thumbnail", ""),
                "source_url": item.get("url", ""),
                "width": item.get("width"),
                "height": item.get("height"),
                "source": "duckduckgo",
            }
        )
    return results


@app.get("/health", operation_id="health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", operation_id="root")
async def root() -> dict[str, Any]:
    return {
        "name": APP_TITLE,
        "status": "ok",
        "openapi_url": "/openapi.json",
        "tools": [
            "ollama_status",
            "search_web",
            "read_webpage",
            "read_pdf",
            "search_images",
            "capture_webpage",
            "resolve_media_url",
        ]
        + (["inspect_image", "inspect_image_deep", "ocr_image", "inspect_video"] if _inspect_tools_enabled() else []),
    }


@app.post("/ollama_status", operation_id="ollama_status")
async def ollama_status(req: OllamaStatusRequest) -> dict[str, Any]:
    """Return local Ollama, Open WebUI tool server, memory, swap, and model status."""
    api: dict[str, Any] = {}
    for name, path in {
        "version": "/api/version",
        "running_models": "/api/ps",
        "installed_models": "/api/tags",
    }.items():
        try:
            async with _client() as client:
                res = await client.get(f"{_ollama_base_url()}{path}", timeout=httpx.Timeout(10.0, connect=3.0))
                res.raise_for_status()
            api[name] = res.json()
        except Exception as exc:
            api[name] = {"error": str(exc)}

    services = [
        "ollama.service",
        "ollama-context-proxy.service",
        "open-webui.service",
        "openwebui-web-tools.service",
        "cloudflared-open-webui.service",
        "local-media-server.service",
    ]
    service_status: dict[str, Any] = {}
    for service in services:
        service_status[service] = {
            "active": _systemctl_user_value("is-active", service),
            "enabled": _systemctl_user_value("is-enabled", service),
        }
        env_value = _systemctl_user_value("show", service, "-p", "Environment", "--value")
        if env_value:
            service_status[service]["environment"] = env_value
        if req.include_logs:
            service_status[service]["recent_logs"] = _journalctl_user(service, req.log_lines)

    system: dict[str, Any] = {}
    try:
        import psutil

        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
        root_disk = psutil.disk_usage("/")
        system = {
            "cpu_count_logical": psutil.cpu_count(logical=True),
            "cpu_count_physical": psutil.cpu_count(logical=False),
            "load_avg": os.getloadavg() if hasattr(os, "getloadavg") else None,
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory": {
                "total": _bytes_summary(vm.total),
                "available": _bytes_summary(vm.available),
                "used": _bytes_summary(vm.used),
                "percent": vm.percent,
            },
            "swap": {
                "total": _bytes_summary(swap.total),
                "used": _bytes_summary(swap.used),
                "free": _bytes_summary(swap.free),
                "percent": swap.percent,
            },
            "root_disk": {
                "total": _bytes_summary(root_disk.total),
                "used": _bytes_summary(root_disk.used),
                "free": _bytes_summary(root_disk.free),
                "percent": root_disk.percent,
            },
        }
    except Exception as exc:
        system = {"error": str(exc)}

    return {
        "ollama_base_url": _ollama_base_url(),
        "tool_backend": _tool_backend(),
        "api": api,
        "services": service_status,
        "system": system,
        "processes": _ollama_related_processes() if req.include_processes else [],
    }


@app.post("/search_web", operation_id="search_web")
async def search_web(req: WebSearchRequest) -> dict[str, Any]:
    """Search the web and return titles, URLs, and snippets."""
    try:
        results = await _brave_web_search(req.query, req.max_results)
        if not results:
            results = await _duckduckgo_web_search(req.query, req.max_results)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"web search failed: {exc}") from exc
    return {"query": req.query, "results": results}


@app.post("/read_webpage", operation_id="read_webpage")
async def read_webpage(req: ReadWebpageRequest) -> dict[str, Any]:
    """Fetch a webpage and return readable title, metadata, text, and links."""
    try:
        return await _extract_readable_webpage(req.url, req.max_chars)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"webpage read failed: {exc}") from exc


@app.post("/read_pdf", operation_id="read_pdf")
async def read_pdf(req: ReadPdfRequest) -> dict[str, Any]:
    """Fetch a PDF URL and return extracted text, metadata, and simple tables."""
    content, final_url, content_type = await _fetch_pdf_content(req.url)
    try:
        return _extract_pdf(content, final_url, content_type, req)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"PDF extraction failed: {exc}") from exc


@app.post("/search_images", operation_id="search_images")
async def search_images(req: ImageSearchRequest) -> dict[str, Any]:
    """Search images and return image URLs, thumbnails, and source pages."""
    try:
        results = await _brave_image_search(req.query, req.max_results)
        if not results:
            results = await _tavily_image_search(req.query, req.max_results)
        if not results:
            results = await _duckduckgo_image_search(req.query, req.max_results)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"image search failed: {exc}") from exc
    return {"query": req.query, "results": results}


@app.post("/capture_webpage", operation_id="capture_webpage")
async def capture_webpage(req: CaptureWebpageRequest) -> dict[str, Any]:
    """Render a webpage in a headless browser and return text plus a screenshot URL."""
    try:
        return await _capture_webpage(req)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"webpage capture failed: {exc}") from exc


@app.post("/resolve_media_url", operation_id="resolve_media_url")
async def resolve_media_url(req: ResolveMediaUrlRequest) -> dict[str, Any]:
    """Resolve media URLs only. Do not use this as the final step for video understanding; call inspect_video after it returns a video URL."""
    try:
        return await _resolve_media_candidates(req.url, req.media_type, req.max_results)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"media URL resolution failed: {exc}") from exc


@app.post("/inspect_image", operation_id="inspect_image")
async def inspect_image(req: InspectImageRequest) -> dict[str, Any]:
    """Inspect a public image URL with the configured local vision backend."""
    if _tool_backend() == "vllm":
        return await _call_vllm_image_inspection(req)

    model = await _resolve_ollama_model(req.model)
    image = await _fetch_image_for_ollama(req.image_url)
    data = await _call_ollama_vision(
        model=model,
        prompt=req.question,
        images=[image],
        max_tokens=req.max_tokens,
        timeout_seconds=float(os.getenv("OLLAMA_IMAGE_TIMEOUT_SECONDS", "300")),
        enable_thinking=req.enable_thinking,
    )
    message = data.get("message", {})
    result = {
        "backend": "ollama",
        "image_url": req.image_url,
        "question": req.question,
        "model": model,
        "answer": message.get("content"),
        "done_reason": data.get("done_reason"),
        "eval_count": data.get("eval_count"),
        "eval_duration": data.get("eval_duration"),
    }
    if _return_inspect_thinking():
        result["thinking"] = message.get("thinking")
    if data.get("_thinking_retry"):
        result["thinking_retry"] = data["_thinking_retry"]
    return result


@app.post("/inspect_image_deep", operation_id="inspect_image_deep")
async def inspect_image_deep(req: InspectImageDeepRequest) -> dict[str, Any]:
    """Inspect an image with an overview plus zoomed crop tiles for small details and text."""
    if _tool_backend() == "vllm":
        fallback = InspectImageRequest(
            image_url=req.image_url,
            question=req.question,
            model=req.model,
            max_tokens=min(req.max_tokens, 8192),
            enable_thinking=req.enable_thinking,
        )
        data = await _call_vllm_image_inspection(fallback)
        data["note"] = "vLLM backend currently uses single-image inspection for inspect_image_deep."
        return data

    model = await _resolve_ollama_model(req.model)
    image = await _fetch_pil_image(req.image_url)
    overview = _encode_pil_image_for_ollama(image, req.overview_max_side, label="Overview")
    tiles, tile_metadata = _build_image_tiles(image, req.max_tiles, req.tile_max_side)
    tile_lines = [
        f"- Tile {item['tile']}: crop box left={item['left']}, top={item['top']}, "
        f"right={item['right']}, bottom={item['bottom']} in original pixel coordinates."
        for item in tile_metadata
    ]
    prompt = (
        f"{req.question}\n\n"
        "You will receive one overview image followed by zoomed crop tiles. "
        "The overview shows the whole image. Each tile is labeled in the image and listed below. "
        "Use the tiles to inspect small text, small objects, faces, logos, UI details, and spatial relationships. "
        "If text is visible, transcribe it as accurately as possible and state uncertainty when characters are unclear. "
        "Avoid inventing details that are not visible.\n\n"
        f"Original image size: {image.width}x{image.height} pixels.\n"
        "Tile map:\n"
        + "\n".join(tile_lines)
    )
    data = await _call_ollama_vision(
        model=model,
        prompt=prompt,
        images=[overview, *tiles],
        max_tokens=req.max_tokens,
        timeout_seconds=float(os.getenv("OLLAMA_IMAGE_DEEP_TIMEOUT_SECONDS", "900")),
        enable_thinking=req.enable_thinking,
    )
    message = data.get("message", {})
    result = {
        "backend": "ollama",
        "image_url": req.image_url,
        "question": req.question,
        "model": model,
        "image_size": {"width": image.width, "height": image.height},
        "overview_max_side": req.overview_max_side,
        "tile_max_side": req.tile_max_side,
        "tile_count": len(tiles),
        "tiles": tile_metadata,
        "answer": message.get("content"),
        "done_reason": data.get("done_reason"),
        "eval_count": data.get("eval_count"),
        "eval_duration": data.get("eval_duration"),
    }
    if _return_inspect_thinking():
        result["thinking"] = message.get("thinking")
    if data.get("_thinking_retry"):
        result["thinking_retry"] = data["_thinking_retry"]
    return result


@app.post("/ocr_image", operation_id="ocr_image")
async def ocr_image(req: OcrImageRequest) -> dict[str, Any]:
    """Extract text, bounding boxes, and confidence scores from a public image URL."""
    image = await _fetch_pil_image(req.image_url)
    result = _ocr_image_with_easyocr(req, image)
    result["image_url"] = req.image_url
    return result


@app.post("/inspect_video", operation_id="inspect_video")
async def inspect_video(req: InspectVideoRequest) -> dict[str, Any]:
    """Analyze a direct video URL with vLLM video input or Ollama frame sampling."""
    video_metadata = await _validate_direct_video_url(req.video_url)
    if _tool_backend() == "vllm":
        return await _call_vllm_video_inspection(req, video_metadata)

    model = await _resolve_ollama_model(req.model)
    video_path: Path | None = None
    try:
        suffix = Path(urllib.parse.urlparse(req.video_url).path).suffix or ".mp4"
        video_path = await _download_media_to_temp(req.video_url, suffix, _max_video_bytes())
        frames = _extract_frames_with_ffmpeg(video_path, req.max_frames)
    finally:
        if video_path:
            video_path.unlink(missing_ok=True)

    prompt = (
        f"{req.question}\n\n"
        f"The input video was sampled into {len(frames)} chronological frames. "
        "Base your answer only on what can be inferred from these sampled frames, "
        "and mention uncertainty when motion or audio would be required."
    )
    data = await _call_ollama_vision(
        model=model,
        prompt=prompt,
        images=frames,
        max_tokens=req.max_tokens,
        timeout_seconds=float(os.getenv("OLLAMA_VIDEO_TIMEOUT_SECONDS", "600")),
        enable_thinking=req.enable_thinking,
    )
    message = data.get("message", {})
    result = {
        "backend": "ollama",
        "video_url": req.video_url,
        "video_metadata": video_metadata,
        "question": req.question,
        "model": model,
        "sampled_frames": len(frames),
        "answer": message.get("content"),
        "done_reason": data.get("done_reason"),
        "eval_count": data.get("eval_count"),
        "eval_duration": data.get("eval_duration"),
    }
    if _return_inspect_thinking():
        result["thinking"] = message.get("thinking")
    if data.get("_thinking_retry"):
        result["thinking_retry"] = data["_thinking_retry"]
    return result
