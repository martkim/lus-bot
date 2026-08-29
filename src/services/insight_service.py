import asyncio
import json
import logging
from datetime import datetime
from typing import List, Optional

from src import db
from src.gemini_client import GEMINI_API_KEY, get_client
from src.errors import NotFoundError
from src.dto.insights import InsightDTO, InsightSummaryDTO

logger = logging.getLogger("passion_mate")

# 매일 다양하게 바뀌는 공통 테마 (딥워크 타임라인 / 멘탈 도서 / 합격 마인드 / 근육 릴렉스) —
# day-of-year 기준으로 하나를 골라, 아래 6개 파트 전부에 그 테마를 각자 특성에 맞게 변주해서 적용한다.
INSIGHT_THEMES = [
    ("timeplan", "⏱️ 오늘의 딥워크 타임라인",
     "오늘 하루 연습/작업 시간을 어떻게 배분하면 좋을지 딥워크 타임라인을 제시해줘."),
    ("mental_book_review", "📚 딥러닝 라이브러리: 멘탈 도서 리뷰",
     "심리학 도서나 자기계발서 1권(예: 아웃라이어, 미움받을 용기, 아토믹 해빗 등)을 선정해, 그 책의 핵심 철학을 입시생의 슬럼프 극복이나 마인드 세팅에 어떻게 적용할 수 있는지 요약해줘."),
    ("audition_mindset", "🧠 실기고사 합격 마인드 세팅",
     "실기고사장 특유의 분위기, 평가 기준, 그리고 실기장에서 압박감을 이겨내는 스포츠 심리학 기반 멘탈 컨트롤 비법을 정리해줘."),
    ("deep_work_practice", "💪 딥워크(Deep Work)와 신체 관리",
     "신체 피로도 관리, 근육 릴렉스 비법, 호흡법 등 신체적 한계를 극복하고 연습의 질(Quality)을 높이는 딥워크 연습법을 과학적 근거와 함께 제시해줘."),
]

# 파트별 소재 힌트 — 같은 날 같은 테마라도 파트 특성에 맞게 변주하도록 Gemini에 전달
PART_FOCUS = {
    "일렉기타": "코드 보이싱, 톤 메이킹, 크로매틱/초견 연습",
    "베이스": "워킹베이스 라인, 그루브와 리듬 정확도, 슬랩 테크닉",
    "작곡": "화성학 진행, 코드 보이싱, 편곡 아이디어",
    "보컬": "발성/호흡법, 음정 안정성, 곡 해석력",
    "미디": "DAW 워크플로우, 사운드 디자인, 편곡/믹싱 기초",
    "드럼": "리듬감, 그루브, 필인(Fill-in) 및 다이내믹 컨트롤",
}


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # 첫 줄이 ```json 같은 펜스 표시일 수 있으므로 통째로 제거
        text = "\n".join(lines[1:])
    if text.endswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[:-1])
    return text.strip()


async def auto_generate_daily_insight():
    """
    Gemini AI가 매일 6개 파트(일렉기타/베이스/작곡/보컬/미디/드럼) 각각에 맞는
    꿀팁 HTML 카드를 생성해 DB에 저장합니다. Gemini 무료 티어 일일 한도가 빠듯해서
    (배경 루프만으로 하루 6회 고정 소진, ai_chat_service.py 참고) 파트당 별도 호출하지
    않고 **한 번의 호출로 6개 파트 콘텐츠를 구조화된 JSON으로 한꺼번에 받는다.**
    """
    if not GEMINI_API_KEY:
        print("[AI Insight] Skipped. No GEMINI_API_KEY.")
        return

    try:
        # 오늘 이미 생성된 인사이트가 있으면 스킵 (6개 파트 배치가 통째로 하루 1회만 생성됨)
        today_str = datetime.now().strftime("%Y-%m-%d")
        if db.has_todays_insight(today_str):
            print("[AI Insight] Today's insight already exists. Skipping generation.")
            return

        # 오늘 날짜 기준으로 공통 테마 순환 선택 (day_of_year % 테마수)
        day_index = datetime.now().timetuple().tm_yday % len(INSIGHT_THEMES)
        insight_type, theme_title, theme_prompt = INSIGHT_THEMES[day_index]

        parts_hint = "\n".join(f'- "{part}": {focus}' for part, focus in PART_FOCUS.items())

        system_prompt = (
            "당신은 실용음악 입시를 전문으로 하는 최고의 예술 입시 코치이자 UI 개발자입니다.\n"
            f"오늘의 공통 주제: {theme_prompt}\n\n"
            "아래 6개 전공 파트 각각에 대해, 위 주제를 그 파트 특성에 맞게 변형한 HTML 카드를 만들어주세요:\n"
            f"{parts_hint}\n\n"
            "⚠️ 중요한 규칙:\n"
            "1. 반드시 아래 형식의 JSON 배열만 반환하세요. 다른 설명 텍스트나 코드펜스(```) 절대 금지:\n"
            '   [{"part": "일렉기타", "html_content": "<div>...</div>"}, {"part": "베이스", "html_content": "..."}, ...]\n'
            "2. 배열은 반드시 6개 항목이어야 하고, part 값은 위에 나열된 6개 이름을 정확히 그대로 써야 합니다.\n"
            "3. html_content 안에는 <style> 태그로 CSS를 인라인 포함하세요.\n"
            "4. 전체 배경은 투명(transparent), 카드 내부만 다크 글래스 스타일: "
            "background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 20px;\n"
            "5. 텍스트는 흰색 계열(#fff, #e0e0e0), 강조색은 보라(#a78bfa)/민트(#00f2fe)/노랑(#ffd60a) 계열.\n"
            "6. 모바일 화면에 맞게 max-width: 100%를 유지하세요.\n"
            "7. 내용은 각 파트 학생에게 실제로 도움이 되는 진짜 정보로 채우세요.\n"
            "8. html_content 문자열 안의 큰따옴표는 JSON 규격에 맞게 이스케이프하세요."
        )

        print(f"[AI Insight] Generating today's insight batch (theme: {theme_title}) for 6 parts...")
        response = await asyncio.to_thread(
            get_client().models.generate_content,
            model='gemini-2.5-flash',
            contents=system_prompt
        )
        raw_text = _strip_code_fence(response.text)

        try:
            items = json.loads(raw_text)
        except json.JSONDecodeError:
            logger.exception("오늘의 인사이트 JSON 파싱 실패")
            print("[AI Insight Error] Gemini response was not valid JSON. Skipping today's batch (will retry tomorrow).")
            return

        now_iso = datetime.now().isoformat()
        saved_count = 0
        for item in items:
            part = item.get("part")
            html_content = item.get("html_content")
            if not part or not html_content or part not in PART_FOCUS:
                continue
            db.create_daily_insight(insight_type, theme_title, html_content, now_iso, part)
            saved_count += 1

        print(f"[AI Insight] Today's insight batch saved: {saved_count}/{len(PART_FOCUS)} parts.")

    except Exception as e:
        logger.exception("오늘의 AI 인사이트 생성 실패")
        try:
            print(f"[AI Insight Error] Failed to generate daily insight: {e}")
        except Exception:
            print("[AI Insight Error] Failed to generate daily insight due to encoding/unicode error.")


def get_latest_active_insight(part: str) -> Optional[InsightDTO]:
    logger.info(f"[GET_LATEST_ACTIVE_INSIGHT] 시작 part={part}")
    row = db.get_latest_active_insight(part)
    return InsightDTO(**row) if row else None


def get_all_insights() -> List[InsightSummaryDTO]:
    logger.info("[GET_ALL_INSIGHTS] 시작")
    rows = db.get_all_insights(limit=60)
    return [InsightSummaryDTO(**row) for row in rows]


def toggle_insight(insight_id: int) -> int:
    logger.info(f"[TOGGLE_INSIGHT] 시작 insight_id={insight_id}")
    current_status = db.get_insight_active_status(insight_id)
    if current_status is None:
        raise NotFoundError("인사이트를 찾을 수 없습니다.")
    new_status = 0 if current_status == 1 else 1
    db.set_insight_active_status(insight_id, new_status)
    return new_status
