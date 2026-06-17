import os
import re
import urllib.parse
from html import unescape
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


APP_TITLE = "Open WebUI Web + Image Tools"
DEFAULT_MODEL = "AEON-7/Gemma-4-26B-A4B-it-Uncensored-NVFP4"


app = FastAPI(
    title=APP_TITLE,
    description=(
        "OpenAPI tool server for Open WebUI. Provides web search, image search, "
        "and image inspection through the local vLLM OpenAI-compatible endpoint."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class WebSearchRequest(BaseModel):
    query: str = Field(..., description="Search query.")
    max_results: int = Field(5, ge=1, le=10, description="Maximum number of results.")


class ImageSearchRequest(BaseModel):
    query: str = Field(..., description="Image search query.")
    max_results: int = Field(5, ge=1, le=10, description="Maximum number of image results.")


class InspectImageRequest(BaseModel):
    image_url: str = Field(..., description="Public image URL to inspect.")
    question: str = Field("Describe this image and answer any relevant question.", description="Question for the vision model.")
    model: str | None = Field(None, description="vLLM served model name. Defaults to SERVE_MODEL env or Gemma4.")
    max_tokens: int = Field(768, ge=64, le=4096, description="Maximum completion tokens.")


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


def _clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _decode_ddg_href(href: str) -> str:
    href = unescape(href)
    if "uddg=" not in href:
        return href
    parsed = urllib.parse.urlparse(href)
    qs = urllib.parse.parse_qs(parsed.query)
    if "uddg" in qs and qs["uddg"]:
        return qs["uddg"][0]
    return href


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
        "tools": ["search_web", "search_images", "inspect_image"],
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


@app.post("/inspect_image", operation_id="inspect_image")
async def inspect_image(req: InspectImageRequest) -> dict[str, Any]:
    """Inspect a public image URL with the local vLLM vision model."""
    base_url = os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
    api_key = os.getenv("VLLM_API_KEY", "sk-test")
    model = req.model or os.getenv("SERVE_MODEL") or DEFAULT_MODEL
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
        "chat_template_kwargs": {"enable_thinking": True},
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
        raise HTTPException(status_code=502, detail=f"vLLM image inspection failed: {exc}") from exc
    data = res.json()
    message = data.get("choices", [{}])[0].get("message", {})
    return {
        "image_url": req.image_url,
        "question": req.question,
        "model": model,
        "reasoning": message.get("reasoning"),
        "answer": message.get("content"),
        "raw_finish_reason": data.get("choices", [{}])[0].get("finish_reason"),
    }
