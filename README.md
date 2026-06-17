# Vast OpenWebUI vLLM Toolkit

[한국어 README](./README.ko.md)

Personal quickstart notes for running Open WebUI + vLLM on Vast.ai with Qwen/Gemma-style models and practical OpenAPI tools: web search, webpage reading, image inspection, direct video inspection, media URL resolution, and a local media server for video files.

This repository is not a polished product. It is a personal setup log. Use it if it helps, but there is no guarantee that it will work on your machine, driver, CUDA stack, vLLM version, model repo, or Vast image.

Tested setup:

- Vast.ai container
- NVIDIA RTX PRO 5000 Blackwell
- CUDA 13.x environment
- vLLM 0.23.0
- Open WebUI
- Gemma4 NVFP4-family model
- Qwen3.6 NVFP4-family model variant

## 1. Clone

```bash
git clone https://github.com/BitIntx/vast-openwebui-vllm-toolkit.git
cd vast-openwebui-vllm-toolkit
cp .env.example .env
```

Edit `.env` if you want a different model, context length, KV cache dtype, or local paths.

## 2. Install

```bash
bash scripts/install.sh
```

Default paths:

```text
/workspace/venvs/vllm
/workspace/venvs/webui
/workspace/hf-cache
/workspace/vllm-cache
/workspace/open-webui-data
```

On Vast.ai, `/workspace` is not always persistent. Check before storing anything important there:

```bash
vast-capabilities | jq '.instance.workspace_is_volume'
```

If this returns `false`, recycle/destroy can wipe the instance filesystem.

## 3. Start vLLM

Stop any old test service first:

```bash
supervisorctl stop vllm-openai 2>/dev/null || true
```

Start the Gemma4 variant:

```bash
bash scripts/run-vllm-gemma4.sh
```

Default settings:

```text
model: AEON-7/Gemma-4-26B-A4B-it-Uncensored-NVFP4
context: 256K
weights dtype: bfloat16
KV cache dtype: fp8
multimodal limit: image 8, video 1
thinking: enabled
reasoning parser: gemma4
tool call parser: gemma4
```

Gemma4 thinking/reasoning separation:

```bash
--default-chat-template-kwargs '{"enable_thinking":true}'
--reasoning-parser gemma4
```

Native Open WebUI tool calling also needs:

```bash
--tool-call-parser gemma4
--enable-auto-tool-choice
```

### Qwen3.6 NVFP4 Variant

To test the Qwen3.6-family model with the same general setup:

```bash
bash scripts/run-vllm-qwen36.sh
```

Default model:

```text
lyf/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-NVFP4
```

Key parser differences:

```bash
--reasoning-parser qwen3
--tool-call-parser qwen3_xml
--enable-auto-tool-choice
```

During testing, vLLM returned structured `tool_calls` with `tool_choice: "auto"`:

```json
{
  "message": {
    "content": null,
    "tool_calls": [
      {
        "type": "function",
        "function": {
          "name": "search_web",
          "arguments": "{\"query\":\"RTX PRO 5000 Blackwell vLLM\"}"
        }
      }
    ],
    "reasoning": "..."
  },
  "finish_reason": "tool_calls"
}
```

To make Open WebUI auto-use tools for these models, set Function Calling to `Native` and enable the tool server. This helper writes model metadata for the tested Gemma4 and Qwen3.6 model IDs:

```bash
python3 scripts/enable-openwebui-model-tools.py
python3 scripts/patch-openwebui-default-model-tools.py
supervisorctl restart open-webui-vllm
```

The patch script adds a small Open WebUI backend fallback: if a chat request has no explicit `tool_ids`, Open WebUI uses the selected model's `meta.toolIds`. The UI toggle may still look unchecked, but the model-attached tools are available to the request.

## 4. Start Open WebUI

In another terminal:

```bash
cd vast-openwebui-vllm-toolkit
bash scripts/run-openwebui.sh
```

Open WebUI points to the local vLLM endpoint by default:

```text
OPENAI_API_BASE_URL=http://127.0.0.1:8000/v1
OPENAI_API_KEY=sk-test
```

## 5. Web + Image + Video Tools

This repository includes a local OpenAPI tool server for:

```text
search_web
read_webpage
search_images
resolve_media_url
inspect_image
inspect_video
```

Start it:

```bash
cd vast-openwebui-vllm-toolkit
bash scripts/run-openwebui-web-tools.sh
```

OpenAPI URL:

```text
http://127.0.0.1:17071/openapi.json
```

`.env.example` includes `TOOL_SERVER_CONNECTIONS` so Open WebUI backend can register this tool server automatically. Restart Open WebUI after changing `.env`:

```bash
supervisorctl restart open-webui-vllm
```

Do not add `http://127.0.0.1:17071` from a remote browser UI when using a Cloudflare URL unless you know how Open WebUI resolves tool servers. In many setups, browser-side `127.0.0.1` means your local device, not the Vast container. This repo uses backend-side `TOOL_SERVER_CONNECTIONS` for that reason.

Open WebUI checklist:

- Set model Function Calling to `Native`
- Enable `Web + Image + Video Tools` or the individual tools in the chat UI

Example prompts:

```text
Use search_web to search for "Open WebUI OpenAPI tool server" and show the top 3 result URLs.
```

```text
Use read_webpage to read https://github.com/open-webui/openapi-servers and summarize the key points.
```

```text
Use search_images to find "RTX PRO 5000 Blackwell", then inspect the first image URL with inspect_image.
```

For media URL discovery:

```text
Use resolve_media_url on https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4 and report the video URL.
```

`resolve_media_url` only verifies direct media URLs or finds simple HTML media candidates. It does not inspect or play video. To understand video content, call `inspect_video` after it returns a `resolved_url`.

For direct video inspection:

```text
Use inspect_video on https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4 and describe it in one sentence.
```

Limitations:

- `resolve_media_url` handles direct file URLs and simple HTML tags such as `<video>`, `<source>`, `og:video`, and `og:image`.
- `inspect_video` expects direct video URLs such as `mp4`, `webm`, `mov`, or `m4v`.
- It does not download YouTube/TikTok/X videos or run JavaScript-heavy players.

Optional search API keys:

```bash
BRAVE_SEARCH_API_KEY=...
TAVILY_API_KEY=...
```

Without keys, the search tools try DuckDuckGo fallbacks.

## 6. Local Media Server for Video URLs

If Open WebUI uploads do not reach vLLM as `video_url`, serve local files over an internal HTTP server. The default directory is `/workspace/media`, bound only to `127.0.0.1:9000`.

```bash
mkdir -p /workspace/media
cp ~/me.mp4 /workspace/media/me.mp4

cd vast-openwebui-vllm-toolkit
bash scripts/run-local-media-server.sh
```

Ask Open WebUI:

```text
Use inspect_video on http://127.0.0.1:9000/me.mp4 and describe the scene.
```

If the model only verifies the URL and stops, be explicit:

```text
Resolve the media URL if needed, then pass resolved_url to inspect_video and actually analyze the video content.
```

This `127.0.0.1` is meant for the Vast container where the tool server and vLLM run, not for the user's browser device. Simple ASCII filenames are recommended.

Environment variables:

```bash
LOCAL_MEDIA_HOST=127.0.0.1
LOCAL_MEDIA_PORT=9000
LOCAL_MEDIA_DIR=/workspace/media
```

## 7. Cloudflare Quick Tunnel

In another terminal:

```bash
cd vast-openwebui-vllm-toolkit
bash scripts/run-cloudflare.sh
```

Use the `https://*.trycloudflare.com` URL printed in the logs. Quick tunnel URLs are temporary and can change after restart.

## 8. API Smoke Test

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-test" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "AEON-7/Gemma-4-26B-A4B-it-Uncensored-NVFP4",
    "messages": [{"role": "user", "content": "hello"}],
    "max_tokens": 512,
    "temperature": 0
  }'
```

If `--reasoning-parser gemma4` is active, thinking should appear in `message.reasoning` instead of being mixed into `message.content`.

## 9. Heavier Settings

To try BF16 KV cache, edit `.env`:

```bash
SERVE_KV_CACHE_DTYPE=bfloat16
```

To constrain video frames/resolution, use a more specific multimodal limit:

```bash
SERVE_MM_LIMIT={"image":8,"video":{"count":1,"num_frames":16,"width":512,"height":512}}
```

## 10. No Warranty

This is a personal setup note, not a product.

- No runtime guarantee
- No performance guarantee
- No model quality guarantee
- No security guarantee
- No cost-safety guarantee
