# -*- coding: utf-8 -*-
"""로컬 LLM(LM Studio) 클라이언트 — AI 상담을 이 PC 안에서 처리한다.

**왜 로컬인가**

Gemini 무료 티어는 하루 20회가 전부고, 배경 루프(꿀팁·분석·수집)가 이미 8회를
가져간다. 그래서 학생 한 명당 상담을 **하루 2회**로 묶어둬야 했다. 입시생에게
"오늘 질문 두 번 다 썼어요"라고 답하는 상담 봇은 상담 봇이 아니다.
로컬 모델은 호출 수 제한이 없어서 이 한도를 없앨 수 있다. 이게 로컬로 옮기는
가장 큰 이유고, 비용이나 사생활은 그다음이다.

**LM Studio를 쓰는 이유**: OpenAI 호환 엔드포인트를 그대로 열어주므로
`/v1/chat/completions`에 평범한 JSON을 POST하면 된다. 별도 SDK가 필요 없어
requirements.txt를 건드리지 않는다(워치독이 배포 때 pip install을 돌린다).

**추론 모델 주의**: 지금 쓰는 gemma-4-e4b는 생각 과정을 `reasoning_content`에
따로 담고 최종 답은 `content`에 담는다. max_tokens가 모자라면 생각만 하다
끝나서 `content`가 **빈 문자열로** 온다(2026-10-05 실측: 400토큰이면 전부 생각,
1800토큰이면 생각 1,700자 + 답 455자). 그래서 빈 답을 성공으로 넘기지 않는다.
"""
import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger("passion_mate")

# 기본값은 LM Studio를 기본 설정으로 켰을 때의 주소다. .env로 덮어쓸 수 있다.
BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
MODEL = os.getenv("LOCAL_LLM_MODEL", "google/gemma-4-e4b")

# 추론 모델이라 생각 과정까지 뽑아야 답이 나온다. 넉넉히 준다.
MAX_TOKENS = int(os.getenv("LOCAL_LLM_MAX_TOKENS", "1800"))
# GTX 1070에서 18~19 tok/s, 한 번 답하는 데 35~45초가 걸린다. 여유를 둔다.
TIMEOUT_SEC = int(os.getenv("LOCAL_LLM_TIMEOUT", "180"))

# 서버가 꺼져 있는지 매번 길게 기다리지 않는다 — 꺼져 있으면 즉시 폴백으로 넘겨야 한다.
_HEALTH_TIMEOUT_SEC = 2
# 헬스체크 결과를 잠깐 재사용한다. 학생이 연달아 물어볼 때마다 TCP를 새로 열 이유가 없다.
_HEALTH_TTL_SEC = 30
_health_cache = {"at": 0.0, "ok": False}


def is_enabled() -> bool:
    """로컬 백엔드를 쓸지. .env에서 LOCAL_LLM_ENABLED=0으로 끌 수 있다."""
    return os.getenv("LOCAL_LLM_ENABLED", "1").strip().lower() not in ("0", "false", "no")


def is_available(force: bool = False) -> bool:
    """LM Studio 서버가 지금 응답하는지. 결과를 30초간 재사용한다."""
    if not is_enabled():
        return False

    now = time.monotonic()
    if not force and (now - _health_cache["at"]) < _HEALTH_TTL_SEC:
        return _health_cache["ok"]

    ok = False
    try:
        request = urllib.request.Request(f"{BASE_URL}/models", method="GET")
        with urllib.request.urlopen(request, timeout=_HEALTH_TIMEOUT_SEC) as response:
            ok = response.getcode() == 200
    except Exception as exc:
        logger.info(f"[LOCAL_LLM] 서버 응답 없음 ({type(exc).__name__}) - 폴백 경로로 간다")

    _health_cache.update({"at": now, "ok": ok})
    return ok


def chat(system_prompt: str, user_message: str, temperature: float = 0.7,
         max_tokens: Optional[int] = None, timeout: Optional[int] = None) -> str:
    """로컬 모델에 한 번 물어보고 답 본문만 돌려준다.

    블로킹 호출이다. async 코드에서는 반드시 `await asyncio.to_thread(...)`로 감쌀 것 —
    그냥 부르면 답이 올 때까지(최대 수십 초) 이벤트 루프 전체가 멈춘다.

    실패하면 RuntimeError를 올린다. 호출부가 폴백을 고르게 하기 위해서다.
    """
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens or MAX_TOKENS,
        "stream": False,
    }
    request = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout or TIMEOUT_SEC) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300] if hasattr(exc, "read") else ""
        raise RuntimeError(f"로컬 LLM HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"로컬 LLM 호출 실패: {type(exc).__name__}: {exc}") from exc

    elapsed = time.monotonic() - started
    try:
        choice = body["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"로컬 LLM 응답 형식이 예상과 다름: {str(body)[:200]}") from exc

    text = (message.get("content") or "").strip()
    usage = body.get("usage") or {}
    completion_tokens = usage.get("completion_tokens") or 0

    if not text:
        # 생각만 하다 토큰이 끊긴 경우. 조용히 빈 답을 내보내면 학생 화면이 비어 버린다.
        reasoning_len = len(message.get("reasoning_content") or "")
        raise RuntimeError(
            f"로컬 LLM이 답 본문을 내지 못했다(finish={choice.get('finish_reason')}, "
            f"생각 {reasoning_len}자, 생성 {completion_tokens}토큰). "
            f"LOCAL_LLM_MAX_TOKENS를 올리거나 추론이 없는 모델로 바꿀 것."
        )

    speed = (completion_tokens / elapsed) if elapsed > 0 else 0
    logger.info(f"[LOCAL_LLM] 응답 완료 {elapsed:.1f}초 {completion_tokens}토큰 "
                f"({speed:.1f} tok/s) model={MODEL}")
    return text
