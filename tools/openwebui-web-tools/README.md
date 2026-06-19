# Open WebUI Web Tools

Local OpenAPI tool server for Open WebUI.

Tools:

- `search_web`: web search using Brave if `BRAVE_SEARCH_API_KEY` is set, otherwise DuckDuckGo HTML.
- `read_webpage`: fetches a webpage and returns readable title, metadata, text, and links.
- `read_pdf`: fetches a PDF URL and returns extracted text, metadata, and simple tables.
- `search_images`: image search using Brave, Tavily, then DuckDuckGo fallback.
- `capture_webpage`: renders a webpage in headless Chrome and returns DOM text plus a reusable screenshot URL.
- `resolve_media_url`: accepts a direct media URL or webpage URL and returns direct video/image/audio candidates when they are exposed in HTML/meta tags.
- `ollama_status`: returns local Ollama/Open WebUI service status, loaded models, memory, swap, and process details.
- `inspect_image`: inspects a public image URL using the configured backend.
- `inspect_image_deep`: inspects a public image URL with one overview image plus zoomed crop tiles for small text and fine details.
- `ocr_image`: extracts text, bounding boxes, and confidence scores from a public image URL using local EasyOCR.
- `inspect_video`: inspects a direct video URL using the configured backend.

Default local URL:

```text
http://127.0.0.1:17071/openapi.json
```

Backend modes:

```bash
# Ollama mode, default
export TOOL_BACKEND=ollama
export OLLAMA_BASE_URL="http://127.0.0.1:11434"
export OLLAMA_INSPECT_MODEL="your-vision-model"
export OLLAMA_INSPECT_ENABLE_THINKING=true
export OLLAMA_INSPECT_RETURN_THINKING=false
export OLLAMA_INSPECT_RETRY_WITHOUT_THINKING=true
export OLLAMA_INSPECT_KEEP_ALIVE=1h
export OPENWEBUI_TOOLS_MAX_PDF_MB=100
export OPENWEBUI_CHROME_PATH="/path/to/chrome"
export OPENWEBUI_CHROME_LIBRARY_PATH="$HOME/.local/chrome-libs/usr/lib/x86_64-linux-gnu"
export OPENWEBUI_CHROME_RUNTIME_ROOT="$HOME/.local/chrome-libs"
export LOCAL_MEDIA_HOST=127.0.0.1
export LOCAL_MEDIA_PORT=9000
export LOCAL_MEDIA_DIR="$HOME/.local/share/openwebui-media"

# vLLM mode
export TOOL_BACKEND=vllm
export VLLM_BASE_URL="http://127.0.0.1:8000/v1"
export VLLM_API_KEY="sk-test"
export SERVE_MODEL="AEON-7/Gemma-4-26B-A4B-it-Uncensored-NVFP4"
```

Ollama mode:

- `inspect_image` downloads image URLs and sends base64 images to Ollama `/api/chat`.
- `inspect_image_deep` sends an overview image plus zoomed crop tiles to Ollama `/api/chat`.
- `ocr_image` uses EasyOCR locally. It does not require Ollama or vLLM once the image is downloaded.
- `inspect_video` samples frames from direct mp4/webm/mov/m4v files and sends the frames to Ollama vision.
- If thinking consumes the full output budget and returns an empty final answer, the Ollama vision call retries once with thinking disabled by default.
- Video inspection is sampled-frame analysis, not native video understanding.

vLLM mode:

- `inspect_image` sends OpenAI-style `image_url` content to vLLM.
- `inspect_video` sends OpenAI-style `video_url` content to vLLM.
- For native tool calling with Gemma/Qwen-style models, serve vLLM with the correct `--tool-call-parser` and `--enable-auto-tool-choice`.

Open WebUI:

1. Admin Panel -> Settings -> Tools / Tool Servers.
2. Add OpenAPI server URL: `http://127.0.0.1:17071/openapi.json`.
3. Enable tools for the model.

Direct media URLs are best:

```text
https://example.com/video.mp4
https://example.com/video.webm
https://example.com/image.webp
```

`resolve_media_url` can find simple `<video>`, `<source>`, `og:video`, `og:image`, and similar candidates from normal HTML pages. It does not download YouTube/TikTok/X players or run site JavaScript.

Example prompts:

```text
Use ollama_status and show current loaded model, context, memory, swap, and service status.
```

```text
Use read_pdf on this PDF URL and extract text and tables.
```

```text
Use capture_webpage on this URL, then pass screenshot.url to inspect_image_deep for visual analysis.
```

```text
Use inspect_image_deep on this image URL and carefully read small labels, logos, and visible text.
```

```text
Use ocr_image on this screenshot URL and return extracted text with confidence scores.
```
