# Open WebUI Web Tools

Local OpenAPI tool server for Open WebUI.

Tools:

- `search_web`: web search using Brave if `BRAVE_SEARCH_API_KEY` is set, otherwise DuckDuckGo HTML.
- `read_webpage`: fetches a webpage and returns readable title, metadata, text, and links.
- `search_images`: image search using Brave, Tavily, then DuckDuckGo fallback.
- `resolve_media_url`: accepts a direct media URL or webpage URL and returns direct video/image/audio candidates when they are exposed in HTML/meta tags.
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
Use inspect_image_deep on this image URL and carefully read small labels, logos, and visible text.
```

```text
Use ocr_image on this screenshot URL and return extracted text with confidence scores.
```
