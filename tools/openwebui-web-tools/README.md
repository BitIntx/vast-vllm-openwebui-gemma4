# Open WebUI Web Tools

Local OpenAPI tool server for Open WebUI.

Tools:

- `search_web`: web search using Brave if `BRAVE_SEARCH_API_KEY` is set, otherwise DuckDuckGo HTML.
- `read_webpage`: fetches a webpage and returns readable title, metadata, text, and links.
- `search_images`: image search using Brave, Tavily, then DuckDuckGo fallback.
- `resolve_media_url`: accepts a direct media URL or webpage URL and returns direct video/image/audio candidates when they are exposed in HTML/meta tags. It does not inspect media content; call `inspect_video` or `inspect_image` after this.
- `inspect_image`: sends a public image URL to local vLLM vision model.
- `inspect_video`: sends a direct public or local mp4/webm/mov/m4v URL to local vLLM video model for actual video understanding.

Default local URL:

```text
http://127.0.0.1:17071/openapi.json
```

Open WebUI:

1. Admin Panel -> Settings -> Tools / Tool Servers.
2. Add OpenAPI server URL: `http://127.0.0.1:17071/openapi.json`.
3. Enable tools for the model.
4. For native tool calling with Gemma4, serve vLLM with `--tool-call-parser gemma4`.

Direct media URLs are best:

```text
https://example.com/video.mp4
https://example.com/video.webm
https://example.com/image.webp
```

`resolve_media_url` can find simple `<video>`, `<source>`, `og:video`, `og:image`,
and similar candidates from normal HTML pages. It does not download YouTube/TikTok/X
players or run site JavaScript. If it returns a video `resolved_url`, use
`inspect_video` with that URL to actually analyze the video.

Optional env:

```bash
export BRAVE_SEARCH_API_KEY="..."
export TAVILY_API_KEY="..."
export VLLM_BASE_URL="http://127.0.0.1:8000/v1"
export VLLM_API_KEY="sk-test"
export SERVE_MODEL="AEON-7/Gemma-4-26B-A4B-it-Uncensored-NVFP4"
```
