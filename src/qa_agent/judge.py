"""2차 검증의 마지막 단계 — AI 판정.

기계적 검사(상태코드, 로그 태그)가 전부 통과해도 "학생 눈에 정상인가"는 다른 문제다.
실제로 이 앱에서 났던 사고들이 그랬다: 글자가 배경과 같은 색이라 안 보이거나, CSS가
캐시에 막혀 옛 화면이 나오거나 — 상태코드는 전부 200이었다. 그래서 스크린샷을 그대로
Gemini에 보여주고 "이 화면이 사용자에게 정상으로 보이는가"를 묻는다.

호출 예산: Gemini 무료 티어 일일 한도는 학생 챗봇과 오늘의 꿀팁이 먼저 써야 한다.
QA 몫을 하루 judge_daily_budget(기본 6회)으로 못 박고, 예산이 없으면 조용히
'uncertain'으로 넘어간다 — 점검이 서비스 기능을 굶기면 본말전도다.
"""
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.qa_agent import repository
from src.qa_agent.config import get_config

logger = logging.getLogger("passion_mate")


@dataclass
class Judgement:
    verdict: str          # pass | fail | uncertain
    reason: str
    findings: List[str]
    used_ai: bool


def _strip_code_fence(text: str) -> str:
    """Gemini가 ```json 펜스를 씌워 주는 경우가 잦다."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    return cleaned.strip()


def _build_prompt(features: List[str], primary_summary: str, secondary_summary: str,
                  device_summary: str, logcat_excerpt: str, traffic_summary: str,
                  has_screenshot: bool) -> str:
    screenshot_clause = (
        "첨부된 이미지는 방금 가상 안드로이드 폰에서 이 앱을 실행해 찍은 실제 화면이다. "
        "화면이 비어 있지 않은지, 글자가 배경에 묻혀 안 보이지는 않는지, 오류/재시도 화면이 "
        "아닌지, 레이아웃이 깨지지 않았는지를 직접 보고 판단하라.\n"
        if has_screenshot else
        "스크린샷은 이번 점검에서 확보하지 못했다. 텍스트 근거만으로 판단하라.\n"
    )

    return (
        "너는 PASSION MATE(음악 입시생 연습 관리 앱)의 QA 검증관이다. "
        "아래는 방금 자동 점검이 수집한 증거다. 이 증거만 보고 최종 판정을 내려라.\n\n"
        f"[점검 대상 기능]\n{', '.join(features) if features else '(지정 없음)'}\n\n"
        f"[1차 검증 — 로컬 서버 직접 호출]\n{primary_summary}\n\n"
        f"[2차 검증 — 공개 도메인(passionmate.app) 재현]\n{secondary_summary}\n\n"
        f"[실화면 검증 — 가상 안드로이드 폰]\n{device_summary}\n\n"
        f"[앱 logcat 일부]\n{logcat_excerpt[-2500:] if logcat_excerpt else '(없음)'}\n\n"
        f"[최근 실사용 트래픽/에러]\n{traffic_summary}\n\n"
        f"{screenshot_clause}\n"
        "판정 기준:\n"
        "- pass: 학생/선생님이 지금 쓰는 데 지장이 없다.\n"
        "- fail: 실제 사용자가 겪을 문제가 확인된다(화면이 안 보임, 기능 오류, 인증 뚫림 등).\n"
        "- uncertain: 증거만으로는 단정할 수 없다.\n\n"
        "**1차(로컬)가 전부 통과했는데 2차(공개 도메인)만 실패한 경우는 fail로 매기지 마라.**\n"
        "같은 코드가 로컬에서 멀쩡히 응답했다면 코드 회귀가 아니라 Cloudflare 터널·DNS·"
        "일시적 네트워크 문제일 가능성이 높다(타임아웃, 520, 간헐적 5xx가 그렇다). 이런 건 "
        "호출하는 쪽이 이미 warn 등급으로 따로 기록하므로, 너는 pass로 두고 findings에만 "
        "적어라. 2차 실패가 매번 같은 경로에서 반복되거나 1차에서도 재현되면 그때는 fail이다.\n\n"
        "반드시 아래 JSON 하나만 출력하라. 다른 말, 마크다운, 이모지는 절대 쓰지 마라.\n"
        '{"verdict": "pass|fail|uncertain", "reason": "한국어 두 문장 이내 요약", '
        '"findings": ["구체적인 문제 1", "구체적인 문제 2"]}\n'
        "findings는 문제가 없으면 빈 배열로 둬라."
    )


def judge(features: List[str], primary_summary: str, secondary_summary: str,
          device_summary: str, logcat_excerpt: str, traffic_summary: str,
          screenshot_path: Optional[str]) -> Judgement:
    """동기 함수 — 호출부에서 asyncio.to_thread로 감쌀 것."""
    config = get_config()

    if not config.judge_enabled:
        return Judgement("uncertain", "AI 판정이 꺼져 있어 기계적 검사 결과만 반영했습니다.", [], False)

    try:
        from src import gemini_client
        if not gemini_client.is_configured():
            return Judgement("uncertain", "GEMINI_API_KEY가 없어 AI 판정을 건너뛰었습니다.", [], False)
    except Exception as exc:
        return Judgement("uncertain", f"Gemini 클라이언트 로드 실패: {exc}", [], False)

    today = datetime.now().strftime("%Y-%m-%d")
    if not repository.consume_ai_budget(today, config.judge_daily_budget):
        used = repository.get_ai_budget_used(today)
        logger.info(f"[QA_JUDGE] 오늘 AI 판정 예산 소진 used={used}/{config.judge_daily_budget}")
        return Judgement(
            "uncertain",
            f"오늘 AI 판정 예산({config.judge_daily_budget}회)을 모두 써서 기계적 검사 결과만 반영했습니다.",
            [], False,
        )

    has_screenshot = bool(screenshot_path and Path(screenshot_path).exists())
    prompt = _build_prompt(features, primary_summary, secondary_summary, device_summary,
                           logcat_excerpt, traffic_summary, has_screenshot)

    contents: list = [prompt]
    if has_screenshot:
        try:
            from google.genai import types
            image_bytes = Path(screenshot_path).read_bytes()
            contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/png"))
        except Exception as exc:
            # 이미지 첨부에 실패해도 텍스트 판정은 계속 간다.
            logger.warning(f"[QA_JUDGE] 스크린샷 첨부 실패, 텍스트만으로 판정: {exc}")
            has_screenshot = False

    logger.info(f"[QA_JUDGE] AI 판정 요청 features={features} screenshot={has_screenshot}")
    try:
        from src import gemini_client
        response = gemini_client.get_client().models.generate_content(
            model=config.judge_model,
            contents=contents,
        )
        raw = _strip_code_fence(response.text or "")
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # 호출 자체는 성공했으니 예산은 실제로 쓴 것이 맞다. 되돌리지 않는다.
        logger.warning("[QA_JUDGE] AI 응답이 JSON이 아님")
        return Judgement("uncertain", "AI 응답을 해석하지 못했습니다.", [], True)
    except Exception as exc:
        # 503(일시적 과부하)처럼 응답조차 못 받은 경우다. 쓰지 않은 예산을 돌려놔야
        # 다음 점검이 판정을 시도할 수 있다.
        repository.refund_ai_budget(today)
        logger.warning(f"[QA_JUDGE] AI 판정 실패(예산 환불): {exc}")
        return Judgement("uncertain", f"AI 판정 호출 실패: {exc}", [], False)

    verdict = str(payload.get("verdict", "uncertain")).lower().strip()
    if verdict not in ("pass", "fail", "uncertain"):
        verdict = "uncertain"
    findings = [str(item) for item in payload.get("findings", []) if str(item).strip()]
    reason = str(payload.get("reason", "")).strip() or "판정 사유가 비어 있습니다."

    logger.info(f"[QA_JUDGE] AI 판정 결과 verdict={verdict} findings={len(findings)}")
    return Judgement(verdict, reason, findings, True)
