# Vast Blackwell vLLM + Open WebUI Quickstart

개인용으로 대충 정리한 실행 메모입니다. 나만 쓰려고 만든 거라 따라 쓰든 말든 실행은 보장하지 않습니다. 환경, 드라이버, vLLM 버전, 모델 repo 상태에 따라 그냥 깨질 수 있습니다.

테스트한 기준:

- Vast.ai container
- NVIDIA RTX PRO 5000 Blackwell
- CUDA 13.x
- vLLM 0.23.0
- Open WebUI
- Gemma4 NVFP4 계열 모델

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
```

Gemma4 thinking 분리에 필요한 핵심 옵션:

```bash
--default-chat-template-kwargs '{"enable_thinking":true}'
--reasoning-parser gemma4
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

## 5. Cloudflare Quick Tunnel

새 터미널에서:

```bash
cd vast-vllm-openwebui-gemma4
bash scripts/run-cloudflare.sh
```

로그에 나오는 `https://*.trycloudflare.com` 주소로 접속합니다. Quick tunnel은 임시 주소라 재시작하면 바뀔 수 있습니다.

## 6. API Smoke Test

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

## 7. Heavier Settings

BF16 KV cache를 시도하려면 `.env`에서:

```bash
SERVE_KV_CACHE_DTYPE=bfloat16
```

비디오 frame/해상도를 제한하고 싶으면 `SERVE_MM_LIMIT`를 더 구체적으로 바꿉니다.

```bash
SERVE_MM_LIMIT={"image":4,"video":{"count":1,"num_frames":16,"width":512,"height":512}}
```

## 8. No Warranty

이 레포는 제품이 아니고 개인용 실행 메모입니다.

- 실행 보장 없음
- 성능 보장 없음
- 모델 품질 보장 없음
- 보안 구성 보장 없음
- 비용 폭탄 책임 안 짐

