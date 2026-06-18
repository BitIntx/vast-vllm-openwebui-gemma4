# Open WebUI Multibackend Toolkit

[English README](./README.md)

Open WebUI에 로컬 모델 백엔드와 OpenAPI 도구 서버를 붙이기 위한 개인용 툴킷입니다.

처음에는 Vast.ai + vLLM 실행 메모였지만, 지금은 Ollama 경로도 포함합니다. 제품처럼 다듬은 프로젝트는 아니고, 환경과 모델에 맞춰 고쳐 쓰는 개인용 셋업 로그에 가깝습니다.

## 지원 백엔드

- `vLLM`: GPU 서버/Vast.ai 기준. OpenAI 호환 API, native tool calling, image URL inspection, direct video URL inspection 용도.
- `Ollama`: CPU/GPU Ollama 기준. 이미지 URL은 Ollama vision으로 분석하고, 비디오는 프레임을 샘플링해서 Ollama vision으로 분석합니다.

OpenAPI tool server가 노출하는 도구:

```text
search_web
read_webpage
search_images
resolve_media_url
inspect_image
inspect_video
```

`search_web`, `read_webpage`, `search_images`, `resolve_media_url`은 vLLM/Ollama 없이도 동작합니다. `inspect_image`, `inspect_video`는 설정한 백엔드를 사용합니다.

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

기본 경로는 아직 Vast 스타일입니다.

```text
/workspace/venvs/vllm
/workspace/venvs/webui
/workspace/hf-cache
/workspace/vllm-cache
/workspace/open-webui-data
```

Vast.ai에서는 `/workspace`가 persistent volume인지 먼저 확인하세요.

```bash
vast-capabilities | jq '.instance.workspace_is_volume'
```

## vLLM 모드

Gemma4 실행:

```bash
bash scripts/run-vllm-gemma4.sh
```

Qwen3.6 계열 실행:

```bash
bash scripts/run-vllm-qwen36.sh
```

도구 서버의 inspection을 vLLM으로 쓰려면:

```bash
TOOL_BACKEND=vllm
VLLM_BASE_URL=http://127.0.0.1:8000/v1
VLLM_API_KEY=sk-test
```

vLLM 모드에서는:

- `inspect_image`가 OpenAI-style `image_url`을 vLLM에 보냅니다.
- `inspect_video`가 OpenAI-style `video_url`을 vLLM에 보냅니다.
- 직접 비디오 분석은 vLLM 버전, 모델, 멀티모달 지원 상태에 따라 달라집니다.

## Ollama 모드

기본값은 Ollama입니다.

```bash
TOOL_BACKEND=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_INSPECT_MODEL=your-vision-model
```

`OLLAMA_INSPECT_MODEL`을 비워두면 Ollama에 설치된 모델 중 `vision` capability가 있는 첫 모델을 고르려고 시도합니다.

Ollama 모드에서는:

- `inspect_image`가 이미지 URL을 다운로드해서 JPEG/base64로 변환한 뒤 Ollama `/api/chat`에 보냅니다.
- `inspect_video`가 직접 접근 가능한 mp4/webm/mov/m4v 파일을 다운로드하고 ffmpeg로 프레임을 뽑아 Ollama vision에 보냅니다.

Ollama 비디오 분석은 네이티브 비디오 이해가 아니라 프레임 샘플링 기반입니다. 오디오, 빠른 움직임, 프레임 사이 사건은 놓칠 수 있습니다.

## Open WebUI 실행

```bash
bash scripts/run-openwebui.sh
```

vLLM 기준:

```text
OPENAI_API_BASE_URL=http://127.0.0.1:8000/v1
OPENAI_API_KEY=sk-test
```

Ollama 기준:

```text
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

## Tool Server 실행

```bash
bash scripts/run-openwebui-web-tools.sh
```

OpenAPI URL:

```text
http://127.0.0.1:17071/openapi.json
```

`.env.example`에는 Open WebUI가 backend-side에서 tool server를 읽을 수 있게 `TOOL_SERVER_CONNECTIONS` 예시를 넣어뒀습니다.

Cloudflare 같은 외부 URL로 Open WebUI에 접속할 때 브라우저 UI에서 `http://127.0.0.1:17071`을 직접 넣으면, 그 localhost가 서버가 아니라 접속 기기를 가리킬 수 있습니다. 가능하면 backend-side `TOOL_SERVER_CONNECTIONS`를 쓰는 편이 낫습니다.

## 예시 프롬프트

```text
search_web 도구로 "Open WebUI OpenAPI tool server"를 검색하고 상위 3개 결과 URL을 보여줘.
```

```text
read_webpage 도구로 https://github.com/open-webui/openapi-servers 페이지를 읽고 핵심만 요약해줘.
```

```text
search_images 도구로 "RTX PRO 5000 Blackwell" 이미지를 찾고, 첫 번째 이미지 URL을 inspect_image 도구로 분석해줘.
```

```text
inspect_video 도구로 https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4 영상을 보고 짧게 설명해줘.
```

## 선택 API 키

```bash
BRAVE_SEARCH_API_KEY=...
TAVILY_API_KEY=...
```

키가 없으면 가능한 경우 DuckDuckGo fallback으로 시도합니다.
