# Vast Blackwell vLLM + Open WebUI Quickstart

개인용으로 대충 정리한 실행 메모입니다. 나만 쓰려고 만든 거라 따라 쓰든 말든 실행은 보장하지 않습니다. 환경, 드라이버, vLLM 버전, 모델 repo 상태에 따라 그냥 깨질 수 있습니다.

테스트한 기준:

- Vast.ai container
- NVIDIA RTX PRO 5000 Blackwell
- CUDA 13.x
- vLLM 0.23.0
- Open WebUI
- Gemma4 NVFP4 계열 모델
- Qwen3.6 NVFP4 계열 모델도 별도 스크립트로 간단 테스트

## 1. Clone

```bash
git clone https://github.com/BitIntx/vast-vllm-openwebui-gemma4.git
cd vast-vllm-openwebui-gemma4
cp .env.example .env
```

필요하면 `.env`에서 모델명, 컨텍스트 길이, KV cache dtype을 바꿉니다.

## 2. Install

```bash
bash scripts/install.sh
```

기본 설치 경로:

```text
/workspace/venvs/vllm
/workspace/venvs/webui
/workspace/hf-cache
/workspace/vllm-cache
/workspace/open-webui-data
```

주의: Vast에서 `/workspace`가 persistent volume이 아닐 수 있습니다.

```bash
vast-capabilities | jq '.instance.workspace_is_volume'
```

`false`면 instance recycle/destroy 때 전부 날아갑니다.

## 3. Start vLLM

기존 테스트 서비스가 있으면 먼저 내립니다.

```bash
supervisorctl stop vllm-openai 2>/dev/null || true
```

vLLM 실행:

```bash
bash scripts/run-vllm-gemma4.sh
```

기본 옵션:

```text
model: AEON-7/Gemma-4-26B-A4B-it-Uncensored-NVFP4
context: 256K
weights dtype: bfloat16
KV cache dtype: fp8
multimodal limit: image 4, video 1
thinking: enabled
reasoning parser: gemma4
tool call parser: gemma4
```

Gemma4 thinking 분리에 필요한 핵심 옵션:

```bash
--default-chat-template-kwargs '{"enable_thinking":true}'
--reasoning-parser gemma4
```

Open WebUI의 native tool calling을 쓰려면 이것도 필요합니다.

```bash
--tool-call-parser gemma4
--enable-auto-tool-choice
```

### Qwen3.6 NVFP4 test variant

Gemma4 설정은 그대로 두고 Qwen3.6 계열 모델만 빠르게 테스트하려면:

```bash
bash scripts/run-vllm-qwen36.sh
```

기본 모델:

```text
lyf/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-NVFP4
```

Gemma4와 다른 핵심 parser 옵션:

```bash
--reasoning-parser qwen3
--tool-call-parser qwen3_xml
--enable-auto-tool-choice
```

테스트 당시 `tool_choice: "auto"` 요청에서 vLLM 응답이 아래처럼 구조화된 `tool_calls`를 반환했습니다.

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

Open WebUI에서 이 모델로 tool을 자동 선택하게 하려면 모델 설정에서 Function Calling을 `Native`로 두고 도구를 켜야 합니다. 이 레포의 기본 자동 도구 메타 설정은 환경에 따라 특정 모델 ID에만 붙어 있을 수 있습니다.

Gemma4와 Qwen3.6 모델에 `Web + Image + Video Tools`를 기본 활성화하려면 Open WebUI DB에 model metadata를 넣습니다.

```bash
python3 scripts/enable-openwebui-model-tools.py
supervisorctl restart open-webui-vllm
```

## 4. Start Open WebUI

새 터미널에서:

```bash
cd vast-vllm-openwebui-gemma4
bash scripts/run-openwebui.sh
```

Open WebUI는 기본적으로 내부 vLLM에 붙습니다.

```text
OPENAI_API_BASE_URL=http://127.0.0.1:8000/v1
OPENAI_API_KEY=sk-test
```

## 5. Optional Web + Image + Video Tools

웹 검색, 웹페이지 읽기, 이미지 검색, 미디어 URL 해석, 이미지 URL inspection, 직접 영상 URL inspection용 OpenAPI tool server를 같이 넣어뒀습니다.

새 터미널에서:

```bash
cd vast-vllm-openwebui-gemma4
bash scripts/run-openwebui-web-tools.sh
```

기본 tool server 주소:

```text
http://127.0.0.1:17071/openapi.json
```

포함된 도구:

```text
search_web
read_webpage
search_images
resolve_media_url
inspect_image
inspect_video
```

`.env.example`에는 Open WebUI backend가 시작할 때 이 tool server를 global tool server로 읽도록 `TOOL_SERVER_CONNECTIONS`를 넣어뒀습니다. Open WebUI를 이미 켠 상태에서 `.env`를 바꿨다면 Open WebUI를 재시작하세요.

```bash
supervisorctl restart open-webui-vllm
```

또는 직접 실행 중이면 `scripts/run-openwebui.sh`를 다시 실행합니다.

중요: Cloudflare URL로 Open WebUI에 접속 중일 때 사용자 화면의 tool server 연결에 `http://127.0.0.1:17071`을 넣으면, 그 `127.0.0.1`은 Vast 컨테이너가 아니라 접속한 브라우저 기기의 localhost일 수 있습니다. 이 레포는 그래서 UI에 직접 넣는 방식보다 `TOOL_SERVER_CONNECTIONS`로 backend에 주입하는 방식을 기본값으로 둡니다.

Open WebUI에서 확인할 것:

- 모델 설정에서 Function Calling을 `Native`로 설정
- 채팅 입력창의 도구 목록에서 `Web + Image + Video Tools` 또는 필요한 개별 도구 활성화

테스트 프롬프트:

```text
search_web 도구를 사용해서 "Open WebUI OpenAPI tool server"를 검색하고 상위 3개 결과 URL을 보여줘.
```

```text
read_webpage 도구로 https://github.com/open-webui/openapi-servers 페이지를 읽고 핵심만 요약해줘.
```

```text
search_images 도구로 "RTX PRO 5000 Blackwell" 이미지를 찾고, 첫 번째 이미지 URL을 inspect_image 도구로 분석해서 한국어로 설명해줘.
```

페이지에서 직접 미디어 URL 후보를 찾고 싶을 때:

```text
resolve_media_url 도구로 https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4 의 video URL을 확인해줘.
```

`resolve_media_url`은 파일 형식과 직접 URL 후보만 확인합니다. 영상 내용을 실제로 보려면 이어서 `inspect_video`를 호출해야 합니다.

직접 mp4/webm URL이 있을 때:

```text
inspect_video 도구로 https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4 영상을 보고 한국어로 한 문장으로 설명해줘.
```

주의: `resolve_media_url`은 직접 파일 URL과 HTML에 노출된 `<video>`, `<source>`, `og:video`, `og:image` 같은 단순 후보만 찾습니다. `inspect_video`는 직접 접근 가능한 `mp4`, `webm`, `mov`, `m4v` 파일 URL만 처리합니다. YouTube/TikTok/X 같은 JavaScript 플레이어 페이지에서 영상을 다운로드하거나 프레임을 추출하는 기능은 넣지 않았습니다.

선택 API 키:

```bash
BRAVE_SEARCH_API_KEY=...
TAVILY_API_KEY=...
```

키가 없으면 DuckDuckGo fallback으로 시도합니다.

## 6. Local Media Server for Video URLs

Open WebUI의 파일 업로드가 vLLM `video_url`로 잘 전달되지 않을 때는 같은 컨테이너 안의 로컬 HTTP 서버로 우회할 수 있습니다. 기본 공개 폴더는 `/workspace/media`이고 외부에는 노출하지 않도록 `127.0.0.1:9000`에만 바인딩합니다.

```bash
mkdir -p /workspace/media
cp ~/me.mp4 /workspace/media/me.mp4

cd vast-vllm-openwebui-gemma4
bash scripts/run-local-media-server.sh
```

Open WebUI에서는 도구를 켠 뒤 이렇게 물어봅니다.

```text
inspect_video 도구로 http://127.0.0.1:9000/me.mp4 영상을 보고 장면을 설명해줘.
```

모델이 URL 확인만 하고 멈추면 아래처럼 명시합니다.

```text
resolve_media_url로 확인한 뒤, resolved_url을 inspect_video 도구에 넘겨서 영상 내용을 실제로 분석해줘.
```

이 `127.0.0.1`은 사용자의 브라우저 기기가 아니라 Vast 컨테이너 내부에서 tool server와 vLLM이 접근하는 주소입니다. 파일명에 공백이 있으면 URL 인코딩을 쓰거나 파일명을 단순하게 바꾸는 편이 낫습니다.

환경 변수:

```bash
LOCAL_MEDIA_HOST=127.0.0.1
LOCAL_MEDIA_PORT=9000
LOCAL_MEDIA_DIR=/workspace/media
```

## 7. Cloudflare Quick Tunnel

새 터미널에서:

```bash
cd vast-vllm-openwebui-gemma4
bash scripts/run-cloudflare.sh
```

로그에 나오는 `https://*.trycloudflare.com` 주소로 접속합니다. Quick tunnel은 임시 주소라 재시작하면 바뀔 수 있습니다.

## 8. API Smoke Test

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-test" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "AEON-7/Gemma-4-26B-A4B-it-Uncensored-NVFP4",
    "messages": [{"role": "user", "content": "안녕"}],
    "max_tokens": 512,
    "temperature": 0
  }'
```

`--reasoning-parser gemma4`가 잘 먹으면 thinking은 `message.reasoning` 쪽으로 분리됩니다.

## 8. Heavier Settings

BF16 KV cache를 시도하려면 `.env`에서:

```bash
SERVE_KV_CACHE_DTYPE=bfloat16
```

비디오 frame/해상도를 제한하고 싶으면 `SERVE_MM_LIMIT`를 더 구체적으로 바꿉니다.

```bash
SERVE_MM_LIMIT={"image":4,"video":{"count":1,"num_frames":16,"width":512,"height":512}}
```

## 9. No Warranty

이 레포는 제품이 아니고 개인용 실행 메모입니다.

- 실행 보장 없음
- 성능 보장 없음
- 모델 품질 보장 없음
- 보안 구성 보장 없음
- 비용 폭탄 책임 안 짐
