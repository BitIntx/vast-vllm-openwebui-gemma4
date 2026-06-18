# Open WebUI Multibackend Toolkit

[한국어 README](./README.ko.md)

Personal setup notes and helper scripts for Open WebUI with local model backends.

This started as a Vast.ai + vLLM setup, but now also includes an Ollama-compatible OpenAPI tool server path. It is still a personal toolkit, not a polished product. Expect to adjust paths, model names, CUDA versions, Open WebUI versions, and backend settings for your machine.

## Backends

Supported paths:

- `vLLM`: OpenAI-compatible serving for high-end GPU hosts, tested around Vast.ai, CUDA, Gemma/Qwen-style models, native tool calling, image URL inspection, and direct video URL inspection.
- `Ollama`: local CPU or GPU Ollama serving, with image URL inspection through Ollama vision and video inspection through sampled frames.

The OpenAPI tool server exposes:

```text
search_web
read_webpage
search_images
resolve_media_url
inspect_image
inspect_video
```

`search_web`, `read_webpage`, `search_images`, and `resolve_media_url` do not require vLLM or Ollama. `inspect_image` and `inspect_video` use the configured backend.

## Clone

```bash
git clone https://github.com/BitIntx/openwebui-multibackend-toolkit.git
cd openwebui-multibackend-toolkit
cp .env.example .env
```

## Install

```bash
bash scripts/install.sh
```

Default paths are still Vast-style:

```text
/workspace/venvs/vllm
/workspace/venvs/webui
/workspace/hf-cache
/workspace/vllm-cache
/workspace/open-webui-data
```

On Vast.ai, check whether `/workspace` is persistent before storing important data:

```bash
vast-capabilities | jq '.instance.workspace_is_volume'
```

## vLLM Mode

Start Gemma4:

```bash
bash scripts/run-vllm-gemma4.sh
```

Start the Qwen3.6-family variant:

```bash
bash scripts/run-vllm-qwen36.sh
```

Useful vLLM options used by the scripts:

```text
context: 256K
KV cache dtype: fp8
multimodal limit: image 8, video 1
reasoning parser: gemma4 or qwen3
tool call parser: gemma4 or qwen3_xml
```

For native Open WebUI tool calling, vLLM needs:

```bash
--enable-auto-tool-choice
--tool-call-parser ...
```

To use the web tool server with vLLM inspection, set:

```bash
TOOL_BACKEND=vllm
VLLM_BASE_URL=http://127.0.0.1:8000/v1
VLLM_API_KEY=sk-test
```

In vLLM mode:

- `inspect_image` sends `image_url` content to `/v1/chat/completions`.
- `inspect_video` sends `video_url` content to `/v1/chat/completions`.
- Direct video inspection depends on your vLLM version, model, and multimodal support.

## Ollama Mode

For an existing Ollama server:

```bash
TOOL_BACKEND=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_INSPECT_MODEL=your-vision-model
```

If `OLLAMA_INSPECT_MODEL` is empty, the tool server tries to pick the first installed Ollama model that reports the `vision` capability.

In Ollama mode:

- `inspect_image` downloads the image URL, resizes it, converts it to JPEG/base64, and calls Ollama `/api/chat`.
- `inspect_video` downloads a direct video file, samples frames with ffmpeg, and sends those frames to Ollama vision.

Ollama video inspection is frame-sampling based, not native video understanding. Audio, fast motion, and events between sampled frames can be missed.

## Start Open WebUI

```bash
bash scripts/run-openwebui.sh
```

For vLLM, Open WebUI points to:

```text
OPENAI_API_BASE_URL=http://127.0.0.1:8000/v1
OPENAI_API_KEY=sk-test
```

For Ollama, configure Open WebUI with your Ollama URL, for example:

```text
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

## Start Tool Server

```bash
bash scripts/run-openwebui-web-tools.sh
```

OpenAPI URL:

```text
http://127.0.0.1:17071/openapi.json
```

`.env.example` includes `TOOL_SERVER_CONNECTIONS` so Open WebUI can register the tool server from the backend side.

When using Cloudflare or another remote URL for Open WebUI, avoid adding `http://127.0.0.1:17071` from the browser unless you know whether Open WebUI resolves it server-side or browser-side. Backend-side `TOOL_SERVER_CONNECTIONS` is safer.

## Tool Examples

```text
Use search_web to search for "Open WebUI OpenAPI tool server" and show the top 3 result URLs.
```

```text
Use read_webpage to read https://github.com/open-webui/openapi-servers and summarize the key points.
```

```text
Use search_images to find "RTX PRO 5000 Blackwell", then inspect the first image URL with inspect_image.
```

```text
Use inspect_video on https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4 and describe it briefly.
```

## Optional Search Keys

```bash
BRAVE_SEARCH_API_KEY=...
TAVILY_API_KEY=...
```

Without keys, web and image search fall back to DuckDuckGo where possible.
