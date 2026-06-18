import os
import re
import base64
import io
import subprocess
import tempfile
import urllib.parse
from html.parser import HTMLParser
from html import unescape
from pathlib import Path
from typing import Any

import imageio_ffmpeg
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from PIL import Image
from pydantic import BaseModel, Field


APP_TITLE = "Open WebUI Web + Image + Video Tools"
DEFAULT_MODEL = "AEON-7/Gemma-4-26B-A4B-it-Uncensored-NVFP4"
DEFAULT_OLLAMA_INSPECT_MODEL = "tinyrick/Qwen3.6-35B-A3B-uncensored-heretic-vision-llmfan46:Q4_K_M-cpu4"
WEB_ONLY_TOOL_PATHS = {
    "/search_web",
    "/read_webpage",
    "/search_images",
    "/resolve_media_url",
}
INSPECT_TOOL_PATHS = {
    "/inspect_image",
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
    max_tokens: int = Field(768, ge=64, le=4096, description="Maximum completion tokens.")
    enable_thinking: bool = Field(False, description="Used by vLLM Gemma-style models. Ollama image inspection ignores this flag.")


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
    max_tokens: int = Field(2048, ge=64, le=8192, description="Maximum completion tokens.")
    max_frames: int = Field(4, ge=1, le=12, description="Maximum video frames to sample and send to the vision model.")
    enable_thinking: bool = Field(False, description="Used by vLLM Gemma-style models. Ollama video inspection ignores this flag.")


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
    return int(os.getenv("OLLAMA_INSPECT_MAX_IMAGE_SIDE", "1024"))


def _max_image_bytes() -> int:
    return int(os.getenv("OLLAMA_INSPECT_MAX_IMAGE_MB", "20")) * 1024 * 1024


def _max_video_bytes() -> int:
    return int(os.getenv("OLLAMA_INSPECT_MAX_VIDEO_MB", "200")) * 1024 * 1024


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
        image.thumbnail((_max_image_side(), _max_image_side()))
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")

        out = io.BytesIO()
        image.save(out, format="JPEG", quality=85, optimize=True)
        content = out.getvalue()
    except Exception:
        # Ollama accepts raw base64 image bytes too; keep the original when
        # Pillow cannot decode but the upstream URL still returned image data.
        pass

    return base64.b64encode(content).decode("ascii")


async def _fetch_image_for_ollama(image_url: str) -> str:
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
    return _encode_image_bytes_for_ollama(res.content)


async def _call_ollama_vision(
    *,
    model: str,
    prompt: str,
    images: list[str],
    max_tokens: int,
    timeout_seconds: float,
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
        "think": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": 0.2,
        },
        "keep_alive": os.getenv("OLLAMA_INSPECT_KEEP_ALIVE", "5m"),
    }
    try:
        async with _client() as client:
            res = await client.post(
                f"{_ollama_base_url()}/api/chat",
                json=payload,
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
            "search_web",
            "read_webpage",
            "search_images",
            "resolve_media_url",
        ]
        + (["inspect_image", "inspect_video"] if _inspect_tools_enabled() else []),
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
    )
    message = data.get("message", {})
    return {
        "backend": "ollama",
        "image_url": req.image_url,
        "question": req.question,
        "model": model,
        "answer": message.get("content"),
        "thinking": message.get("thinking"),
        "done_reason": data.get("done_reason"),
        "eval_count": data.get("eval_count"),
        "eval_duration": data.get("eval_duration"),
    }


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
    )
    message = data.get("message", {})
    return {
        "backend": "ollama",
        "video_url": req.video_url,
        "video_metadata": video_metadata,
        "question": req.question,
        "model": model,
        "sampled_frames": len(frames),
        "answer": message.get("content"),
        "thinking": message.get("thinking"),
        "done_reason": data.get("done_reason"),
        "eval_count": data.get("eval_count"),
        "eval_duration": data.get("eval_duration"),
    }
