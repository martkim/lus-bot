# -*- coding: utf-8 -*-
"""오늘의 꿀팁 — 실존이 확인된 논문 한 편을 골라, 6개 파트에 맞게 쉬운 말로 풀어준다.

**이 서비스의 규칙**

1. 근거 논문 없이는 꿀팁을 만들지 않는다.
   `paper_service.pick_todays_paper()`가 None이면 그날은 생성을 건너뛴다.
   근거 없는 조언을 내보내느니 "준비 중"이 낫다.

2. AI는 사실을 만들지 않는다.
   Gemini에게는 **이미 확인된 논문의 초록**을 통째로 주고, 그걸 입시생이 알아들을
   말로 옮기는 일만 시킨다. 논문 제목·저자·연도는 AI가 아니라 DB에서 나온다.

3. AI는 HTML을 만들지 않는다.
   예전에는 카드 HTML과 CSS를 Gemini가 통째로 만들었다. 그래서 프롬프트에 색을
   적어줘야 했고("흰 배경이니 어두운 글자를 써라"), 학생 화면이 다크 테마로 바뀐
   뒤에도 그 문구가 남아 글자가 안 보이는 사고가 반복됐다. 지금은 AI가 내용만
   채우고 HTML은 src/knowledge/renderer.py가 만든다 — 색은 CSS가 정한다.

AI 호출은 하루 1회(6개 파트 한 번에).
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import List, Optional

from src import db
from src.dto.insights import InsightDTO, InsightSummaryDTO
from src.errors import NotFoundError
from src.gemini_client import GEMINI_API_KEY, get_client, strip_code_fence
from src.knowledge import renderer
from src.knowledge.papers_seed import TOPICS
from src.services import paper_service, video_service

logger = logging.getLogger("passion_mate")

# 파트별 소재 힌트 — 같은 논문이라도 파트 특성에 맞게 적용 예시가 달라야 한다.
PART_FOCUS = {
    "일렉기타": "코드 보이싱, 톤 메이킹, 크로매틱/초견 연습",
    "베이스": "워킹베이스 라인, 그루브와 리듬 정확도, 슬랩 테크닉",
    "작곡": "화성학 진행, 코드 보이싱, 편곡 아이디어",
    "보컬": "발성/호흡법, 음정 안정성, 곡 해석력",
    "미디": "DAW 워크플로우, 사운드 디자인, 편곡/믹싱 기초",
    "드럼": "리듬감, 그루브, 필인(Fill-in) 및 다이내믹 컨트롤",
}

# 날짜에 따라 주제를 돌려가며 고른다. 주제에 쓸 논문이 떨어지면
# paper_service가 알아서 주제 제한을 풀어준다.
TOPIC_ROTATION = list(TOPICS.keys())

# 초록이 아주 긴 논문이 있어 토큰을 아끼려 자른다.
MAX_ABSTRACT_CHARS = 2500


def _todays_topic() -> str:
    return TOPIC_ROTATION[datetime.now().timetuple().tm_yday % len(TOPIC_ROTATION)]


def _build_prompt(paper: dict) -> str:
    """확인된 논문 하나를 주고, 6개 파트용 '쉬운 풀이'를 받아오는 프롬프트."""
    authors = ", ".join(paper.get("authors") or []) or "저자 미상"
    abstract = (paper.get("abstract") or "")[:MAX_ABSTRACT_CHARS]
    parts_hint = "\n".join(f'- "{part}": {focus}' for part, focus in PART_FOCUS.items())

    return (
        "당신은 실용음악 입시생을 가르치는 선생님입니다. 아래는 실제로 출판된 논문 한 편의 정보입니다.\n"
        "이 논문에 실제로 담긴 내용만 가지고, 입시생이 알아들을 수 있는 쉬운 말로 풀어 주세요.\n\n"
        f"[논문 제목] {paper['title']}\n"
        f"[저자] {authors}\n"
        f"[발표 연도] {paper.get('year') or '미상'}\n"
        f"[학술지] {paper.get('journal') or '미상'}\n"
        f"[초록 원문]\n{abstract}\n\n"
        f"[이 논문을 풀어줄 각도] {paper.get('angle') or ''}\n\n"
        "아래 6개 전공 파트 각각에 대해, 같은 논문을 그 파트 상황에 맞게 적용해 주세요:\n"
        f"{parts_hint}\n\n"
        "다음 형태의 JSON 배열 하나만 반환하세요. 설명 문장이나 코드펜스(```)는 절대 붙이지 마세요.\n"
        "[\n"
        '  {"part": "일렉기타",\n'
        '   "headline": "한 줄 제목 (20자 내외)",\n'
        '   "paper_plain": "이 논문이 밝혀낸 것을 쉬운 말로 3~4문장. 고등학생이 읽어도 이해되게.",\n'
        '   "how_to_apply": ["오늘 연습에서 바로 해볼 것 1", "2", "3"],\n'
        '   "caution": "흔히 하는 오해나 주의할 점 한 문장"},\n'
        "  ... (6개)\n"
        "]\n\n"
        "반드시 지킬 것:\n"
        "1. 배열은 정확히 6개이고, part 값은 위에 나열된 6개 이름을 그대로 써야 합니다.\n"
        "2. **초록에 없는 숫자, 실험 조건, 참가자 수를 지어내지 마세요.** "
        "초록에 구체적인 수치가 없으면 수치를 쓰지 말고 경향만 설명하세요.\n"
        "3. 논문 제목·저자·연도는 본문에 쓰지 마세요. 그건 카드 하단에 따로 표시됩니다.\n"
        "4. paper_plain은 '연구에 따르면' 같은 말로 시작해도 좋지만, 논문이 말하지 않은 것을 "
        "단정하지 마세요.\n"
        "5. how_to_apply는 오늘 연습실에서 바로 할 수 있는 구체적인 행동이어야 합니다.\n"
        "6. 이모지와 그림문자를 절대 쓰지 마세요. HTML 태그도 쓰지 마세요."
    )


def _validate_content(item: dict) -> bool:
    """AI가 채워 보낸 한 파트 분량이 카드로 쓸 만한지 확인."""
    if item.get("part") not in PART_FOCUS:
        return False
    if not (item.get("paper_plain") or "").strip():
        return False
    return True


async def auto_generate_daily_insight() -> bool:
    """하루 1회: 논문 한 편 -> 6개 파트 꿀팁 카드.

    오늘 치를 확보했으면 True. 나중에 다시 시도해야 하면 False를 돌려주고,
    호출하는 루프가 24시간 대신 짧게 쉬었다 다시 부른다.
    """
    if not GEMINI_API_KEY:
        logger.warning("[AUTO_GENERATE_DAILY_INSIGHT] GEMINI_API_KEY 없음 - 생성 건너뜀")
        return False

    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        if db.has_todays_insight(today_str):
            logger.info("[AUTO_GENERATE_DAILY_INSIGHT] 오늘자 인사이트가 이미 있음 - 건너뜀")
            return True

        topic = _todays_topic()
        paper = paper_service.pick_todays_paper(topic)
        if not paper:
            logger.error(
                "[AUTO_GENERATE_DAILY_INSIGHT] 근거 논문을 못 골라 오늘 생성 중단. "
                "`.venv/Scripts/python.exe -m src.knowledge.papers_seed`로 코퍼스를 만들고 "
                "서버를 재시작하면 채워진다."
            )
            return False

        theme_title = TOPICS.get(paper.get("topic") or topic, "오늘의 연구 기반 꿀팁")
        logger.info(f"[AUTO_GENERATE_DAILY_INSIGHT] 시작 topic={topic} theme={theme_title} "
                    f"paper={paper['doi']} parts={len(PART_FOCUS)}")

        response = await asyncio.to_thread(
            get_client().models.generate_content,
            model="gemini-2.5-flash",
            contents=_build_prompt(paper),
        )

        try:
            items = json.loads(strip_code_fence(response.text))
        except json.JSONDecodeError:
            logger.exception("오늘의 인사이트 JSON 파싱 실패")
            logger.error("[AUTO_GENERATE_DAILY_INSIGHT] Gemini 응답이 유효한 JSON이 아님 - "
                         "잠시 뒤 재시도")
            return False

        now_iso = datetime.now().isoformat()
        saved_count = 0
        used_video_ids = set()

        for item in items if isinstance(items, list) else []:
            if not _validate_content(item):
                logger.warning(f"[AUTO_GENERATE_DAILY_INSIGHT] 형식이 맞지 않는 항목 건너뜀 "
                               f"part={item.get('part')!r}")
                continue

            part = item["part"]
            video = video_service.pick_video_for_part(part)
            html_content = renderer.render_card(item, paper=paper, video=video)

            db.create_daily_insight(
                insight_type=paper.get("topic") or topic,
                title=theme_title,
                html_content=html_content,
                created_at_iso=now_iso,
                part=part,
                paper_doi=paper["doi"],
                video_id=(video or {}).get("video_id"),
                content_json=json.dumps(item, ensure_ascii=False),
            )
            if video:
                used_video_ids.add(video["video_id"])
            saved_count += 1

        if saved_count:
            paper_service.mark_used(paper["doi"])
            for video_id in used_video_ids:
                video_service.mark_used(video_id)

        logger.info(f"[AUTO_GENERATE_DAILY_INSIGHT] 배치 저장 완료 {saved_count}/{len(PART_FOCUS)} 파트 "
                    f"paper={paper['doi']} 영상연결={len(used_video_ids)}건")
        return saved_count > 0

    except Exception as e:
        logger.exception("오늘의 AI 인사이트 생성 실패")
        logger.error(f"[AUTO_GENERATE_DAILY_INSIGHT] 생성 실패: {e}")
        return False


def get_latest_active_insight(part: str) -> Optional[InsightDTO]:
    logger.info(f"[GET_LATEST_ACTIVE_INSIGHT] 시작 part={part}")
    row = db.get_latest_active_insight(part)
    if row is None:
        available = db.get_available_insight_parts()
        logger.warning(
            f"[GET_LATEST_ACTIVE_INSIGHT] part={part!r} 인사이트 0건 - 보유 파트={available}, "
            f"생성 대상 파트={list(PART_FOCUS)}. 학생의 instrument 값이 이 목록에 없으면 "
            f"그 학생은 꿀팁을 영구히 못 본다(화면엔 '준비 중'으로만 보여 원인이 드러나지 않는다)."
        )
        return None

    return InsightDTO(**{k: row[k] for k in row.keys() if k in InsightDTO.model_fields})


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
