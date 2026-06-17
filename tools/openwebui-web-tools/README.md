# Open WebUI Web Tools

Local OpenAPI tool server for Open WebUI.

Tools:

- `search_web`: web search using Brave if `BRAVE_SEARCH_API_KEY` is set, otherwise DuckDuckGo HTML.
- `search_images`: image search using Brave, Tavily, then DuckDuckGo fallback.
- `inspect_image`: sends a public image URL to local vLLM vision model.

Default local URL:

```text
http://127.0.0.1:17071/openapi.json
```

Open WebUI:

1. Admin Panel -> Settings -> Tools / Tool Servers.
2. Add OpenAPI server URL: `http://127.0.0.1:17071/openapi.json`.
3. Enable tools for the model.
4. For native tool calling with Gemma4, serve vLLM with `--tool-call-parser gemma4`.

Optional env:

```bash
export BRAVE_SEARCH_API_KEY="..."
export TAVILY_API_KEY="..."
export VLLM_BASE_URL="http://127.0.0.1:8000/v1"
export VLLM_API_KEY="sk-test"
export SERVE_MODEL="AEON-7/Gemma-4-26B-A4B-it-Uncensored-NVFP4"
```
