import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from src import db
from src.gemini_client import GEMINI_API_KEY, get_client
from src.errors import NotFoundError
from src.dto.insights import InsightDTO, InsightSummaryDTO

logger = logging.getLogger("passion_mate")

# 매일 다양하게 바뀌는 주제 리스트 (서울예대 기타 입시생 특화 및 딥러닝 멘탈 도서 기반)
INSIGHT_TOPICS = [
    ("guitar_timeplan", "⏱️ 서울예대 기타 맞춤형 시간 계획표",
     "서울예술대학교 실용음악과 기타 전공 입시생을 위한 '오늘의 딥워크 타임라인'을 작성해줘. 하루 단위로 크로매틱, 초견, 자유곡, 즉흥연주(Improvisation) 시간 배분을 과학적으로 제시하고, 구체적인 연습 목표를 정리한 세련된 HTML 카드를 만들어줘."),
    ("mental_book_review", "📚 딥러닝 라이브러리: 멘탈 도서 리뷰",
     "당신의 뇌(Brain)가 오늘 학습한 심리학 도서나 자기계발서 1권(예: 아웃라이어, 미움받을 용기, 아토믹 해빗 등)을 선정해, 그 책의 핵심 철학을 기타 입시생의 슬럼프 극복이나 마인드 세팅에 어떻게 직접 적용할 수 있는지 요약해주는 HTML 카드를 만들어줘."),
    ("seoul_arts_mindset", "🧠 서울예대 합격 마인드 세팅",
     "서울예대 기타 전공 실기고사장 특유의 분위기, 교수님들의 평가 기준(테크닉보다는 톤, 리듬감, 음악성 등), 그리고 실기장에서 압박감을 이겨내는 스포츠 심리학 기반의 멘탈 컨트롤 비법을 정리한 HTML 카드를 만들어줘."),
    ("deep_work_practice", "💪 딥워크(Deep Work)와 근육 릴렉스",
     "신체 피로도 관리, 손목 및 어깨 근육의 릴렉스 비법, 호흡법 등 신체적 한계를 극복하고 연습의 질(Quality)을 높이는 효율적인 딥워크 연습법을 과학적 근거와 함께 제시하는 HTML 카드를 만들어줘."),
]


async def auto_generate_daily_insight():
    """
    Gemini AI가 매일 인터넷 지식 기반으로 서울예대 입시생에게 도움이 되는
    꿀팁/화성학 퀴즈/추천 도서/전공 비법 등 HTML 카드를 자동 생성하고 DB에 저장합니다.
    """
    if not GEMINI_API_KEY:
        print("[AI Insight] Skipped. No GEMINI_API_KEY.")
        return

    try:
        # 오늘 이미 생성된 인사이트가 있으면 스킵
        today_str = datetime.now().strftime("%Y-%m-%d")
        if db.has_todays_insight(today_str):
            print("[AI Insight] Today's insight already exists. Skipping generation.")
            return

        # 오늘 날짜 기준으로 주제 순환 선택 (day_of_year % 주제수)
        day_index = datetime.now().timetuple().tm_yday % len(INSIGHT_TOPICS)
        insight_type, title, topic_prompt = INSIGHT_TOPICS[day_index]

        system_prompt = (
            "당신은 서울예술대학교(서울예대) 입시를 전문으로 하는 최고의 예술 입시 코치이자 UI 개발자입니다.\n"
            "다음 주제에 맞는 내용을 담은 아름다운 HTML+CSS 카드 위젯을 만들어주세요.\n\n"
            f"주제: {topic_prompt}\n\n"
            "⚠️ 중요한 규칙:\n"
            "1. 반드시 완성된 HTML 코드만 반환하세요. (코드 블록 백틱(```) 절대 금지)\n"
            "2. <style> 태그에 CSS를 인라인으로 포함하세요.\n"
            "3. 전체 배경은 투명(transparent)으로, 카드 내부만 다크 글래스 스타일로 꾸며주세요.\n"
            "   예: background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 20px;\n"
            "4. 텍스트 색상은 흰색 계열(#fff, #e0e0e0 등)을 사용하세요.\n"
            "5. 강조 색상은 보라색(#a78bfa), 민트(#00f2fe), 노랑(#ffd60a) 계열을 사용하세요.\n"
            "6. 모바일 화면에 맞게 max-width: 100%를 유지하세요.\n"
            "7. 내용은 실제로 서울예대 입시생에게 도움이 되는 진짜 정보로 채워주세요.\n"
            "8. 인터랙티브 요소(퀴즈, 버튼, 토글 등)가 포함된 경우 <script> 태그도 포함하세요."
        )

        try:
            print(f"[AI Insight] Generating today's insight: [{title}]...")
        except Exception:
            print(f"[AI Insight] Generating today's insight of type: {insight_type}...")
        response = await asyncio.to_thread(
            get_client().models.generate_content,
            model='gemini-2.5-flash',
            contents=system_prompt
        )
        html_content = response.text.strip()

        # 불필요한 코드 펜스 제거
        if html_content.startswith("```"):
            lines = html_content.split("\n")
            html_content = "\n".join(lines[1:])
        if html_content.endswith("```"):
            lines = html_content.split("\n")
            html_content = "\n".join(lines[:-1])
        html_content = html_content.strip()

        # DB에 저장
        now_iso = datetime.now().isoformat()
        db.create_daily_insight(insight_type, title, html_content, now_iso)
        try:
            print(f"[AI Insight] Today's insight [{title}] saved successfully.")
        except Exception:
            print("[AI Insight] Today's insight saved successfully.")

    except Exception as e:
        logger.exception("오늘의 AI 인사이트 생성 실패")
        try:
            print(f"[AI Insight Error] Failed to generate daily insight: {e}")
        except Exception:
            print("[AI Insight Error] Failed to generate daily insight due to encoding/unicode error.")


def get_latest_active_insight() -> Optional[InsightDTO]:
    logger.info("[GET_LATEST_ACTIVE_INSIGHT] 시작")
    row = db.get_latest_active_insight()
    return InsightDTO(**row) if row else None


def get_all_insights() -> List[InsightSummaryDTO]:
    logger.info("[GET_ALL_INSIGHTS] 시작")
    rows = db.get_all_insights(limit=30)
    return [InsightSummaryDTO(**row) for row in rows]


def toggle_insight(insight_id: int) -> int:
    logger.info(f"[TOGGLE_INSIGHT] 시작 insight_id={insight_id}")
    current_status = db.get_insight_active_status(insight_id)
    if current_status is None:
        raise NotFoundError("인사이트를 찾을 수 없습니다.")
    new_status = 0 if current_status == 1 else 1
    db.set_insight_active_status(insight_id, new_status)
    return new_status
