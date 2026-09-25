# -*- coding: utf-8 -*-
"""유튜브 영상 서비스 — 영상을 찾아 **자막을 실제로 받아 읽고** 분석해 저장한다.

이 서비스가 지키는 원칙 하나: **자막을 못 받은 영상은 저장하지 않는다.**
제목과 썸네일만 보고 "이런 내용입니다"라고 소개하면 그건 추측이고, 학생은 그걸
사실로 읽는다. 자막이 있어야만 내용을 말할 자격이 생긴다.

그리고 AI가 뽑아낸 '핵심 발언'은 자막 원문에 실제로 들어 있는지 **글자 단위로
대조한다**(_verify_quote). 대조에 실패하면 그 인용문은 버리고 우리가 직접 자막에서
고른다. 없는 말을 "학생이 이렇게 말했습니다"로 내보내는 게 제일 나쁜 실패다.

AI 호출은 하루 1회(영상 1건 분석)로 묶는다 — Gemini 무료 티어를 학생 챗봇과
나눠 써야 하기 때문이다.
"""
import asyncio
import json
import logging
import re
from datetime import datetime
from typing import List, Optional

from src import db
from src.errors import NotFoundError, ValidationError
from src.gemini_client import GEMINI_API_KEY, get_client, strip_code_fence
from src.knowledge import youtube_api

logger = logging.getLogger("passion_mate")

PARTS = ["일렉기타", "베이스", "작곡", "보컬", "미디", "드럼"]

# 하루에 자막까지 받아볼 후보 수. 자막 수집은 공짜지만 유튜브에 예의를 지키고,
# AI 분석은 그중 '쓸 만한 첫 번째' 한 건에만 쓴다.
MAX_CANDIDATES_PER_RUN = 8

# 자막 원문을 통째로 AI에 넘기면 토큰이 크다. 앞부분 위주로 자른다.
MAX_TRANSCRIPT_CHARS_FOR_AI = 6000


def _normalize_for_compare(text: str) -> str:
    """인용문 대조용 — 공백/문장부호 차이를 무시한다(자막은 띄어쓰기가 들쭉날쭉하다)."""
    return re.sub(r"[\s.,!?~\"'·\-—]+", "", text or "")


def _verify_quote(quote: Optional[str], transcript_text: str) -> bool:
    """AI가 돌려준 인용문이 자막에 실제로 있는 말인지 확인한다."""
    if not quote or len(quote.strip()) < 10:
        return False
    return _normalize_for_compare(quote) in _normalize_for_compare(transcript_text)


def _fallback_excerpt(transcript_text: str) -> Optional[str]:
    """AI 인용문을 못 믿게 됐을 때, 자막에서 우리가 직접 한 토막 고른다."""
    # 문장처럼 끊어서, 입시 관련 단어가 들어간 첫 덩어리를 쓴다.
    chunks = re.split(r"(?<=[.!?])\s+|\s{2,}", transcript_text)
    for chunk in chunks:
        chunk = chunk.strip()
        if 25 <= len(chunk) <= 160 and any(kw in chunk for kw in youtube_api.RELEVANCE_KEYWORDS):
            return chunk
    # 그래도 없으면 앞에서 한 토막.
    head = transcript_text[:140].strip()
    return head or None


def _todays_queries() -> List[str]:
    """날짜에 따라 검색어를 돌려쓴다 — 매일 같은 영상만 찾지 않도록."""
    day = datetime.now().timetuple().tm_yday
    general = youtube_api.SEARCH_QUERIES_GENERAL
    part = PARTS[day % len(PARTS)]
    queries = [general[day % len(general)]]
    queries += [tpl.format(part=part) for tpl in youtube_api.SEARCH_QUERIES_BY_PART]
    return queries


async def _analyze_transcript(video_meta: dict, transcript: dict) -> Optional[dict]:
    """자막 원문을 Gemini에 넘겨 입시생 관점 요약/핵심/인용문을 받는다. (AI 호출 1회)"""
    text = transcript["text"][:MAX_TRANSCRIPT_CHARS_FOR_AI]

    prompt = (
        "당신은 실용음악 입시를 지도하는 선생님입니다. 아래는 유튜브 영상의 **실제 자막 원문**입니다.\n"
        "이 자막에 실제로 담긴 내용만 가지고 입시생에게 도움이 되게 정리해 주세요.\n\n"
        f"[영상 제목] {video_meta.get('title', '')}\n"
        f"[채널] {video_meta.get('channel', '')}\n\n"
        f"[자막 원문]\n{text}\n\n"
        "아래 JSON 하나만 반환하세요. 설명 문장이나 코드펜스(```)는 절대 붙이지 마세요.\n"
        "{\n"
        '  "is_useful": true 또는 false,   // 실용음악/예체능 입시생에게 실제로 도움이 되는 내용인가\n'
        '  "summary": "이 영상이 입시생에게 알려주는 것 2~3문장",\n'
        '  "key_points": ["핵심 조언 1", "핵심 조언 2", "핵심 조언 3"],\n'
        '  "quote": "자막에 나온 문장을 **한 글자도 바꾸지 말고** 그대로 옮긴 인상적인 한 문장",\n'
        '  "parts": ["보컬", "드럼"],   // 관련 전공 파트. 전 파트 공통이면 빈 배열 []\n'
        '  "relevance_score": 0~100    // 입시생에게 얼마나 유용한가\n'
        "}\n\n"
        "규칙:\n"
        "1. quote는 반드시 위 자막 원문에 있는 그대로여야 합니다. 다듬거나 요약하면 안 됩니다.\n"
        "2. 자막에 없는 내용을 추측해서 채우지 마세요. 내용이 부실하면 is_useful을 false로 하세요.\n"
        f"3. parts에 쓸 수 있는 값: {', '.join(PARTS)}\n"
        "4. 이모지와 그림문자를 쓰지 마세요."
    )

    try:
        response = await asyncio.to_thread(
            get_client().models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return json.loads(strip_code_fence(response.text))
    except json.JSONDecodeError:
        logger.exception("[ANALYZE_TRANSCRIPT] Gemini 응답이 JSON이 아님")
        return None
    except Exception:
        logger.exception("[ANALYZE_TRANSCRIPT] Gemini 분석 실패")
        return None


def _build_video_row(video_meta: dict, transcript: dict, analysis: dict, source: str) -> dict:
    """분석 결과를 DB 행으로. 인용문 대조도 여기서 한다."""
    quote = analysis.get("quote")
    if _verify_quote(quote, transcript["text"]):
        excerpt = quote.strip()
    else:
        # AI가 자막에 없는 말을 지어냈다는 뜻이다. 조용히 넘기지 말고 남긴다.
        logger.warning(
            f"[BUILD_VIDEO_ROW] AI 인용문이 자막에 없음 video_id={video_meta['video_id']} "
            f"quote={str(quote)[:60]!r} - 자막에서 직접 고른 문장으로 대체"
        )
        excerpt = _fallback_excerpt(transcript["text"])

    parts = [p for p in (analysis.get("parts") or []) if p in PARTS]

    return {
        "video_id": video_meta["video_id"],
        "title": video_meta.get("title") or "",
        "channel": video_meta.get("channel"),
        "url": video_meta.get("url") or f"https://www.youtube.com/watch?v={video_meta['video_id']}",
        "published_at": video_meta.get("published_at"),
        "duration_seconds": video_meta.get("duration_seconds"),
        "view_count": video_meta.get("view_count"),
        "parts": parts,
        "topic": None,
        "transcript_language": transcript.get("language"),
        "transcript_chars": transcript.get("char_count"),
        "transcript_excerpt": excerpt,
        "analysis_summary": analysis.get("summary"),
        "key_points": [str(p) for p in (analysis.get("key_points") or [])][:5],
        "relevance_score": int(analysis.get("relevance_score") or 0),
        "source": source,
        "analyzed_at": datetime.now().isoformat(),
    }


async def harvest_daily_video() -> Optional[dict]:
    """하루 1회: 새 영상을 찾아 자막을 받고, 쓸 만한 것 1건을 분석해 저장한다.

    AI 호출은 최대 1회. 자막을 받아보는 것까지는 공짜라 여러 건을 시도하고,
    '자막이 있고 입시 얘기가 실제로 나오는' 첫 영상에만 AI를 쓴다.
    """
    logger.info("[HARVEST_DAILY_VIDEO] 시작")

    if not GEMINI_API_KEY:
        logger.warning("[HARVEST_DAILY_VIDEO] GEMINI_API_KEY 없음 - 건너뜀")
        return None

    if not youtube_api.is_configured():
        logger.warning(
            "[HARVEST_DAILY_VIDEO] YOUTUBE_API_KEY 없음 - 자동 검색 불가. "
            "선생님이 대시보드에서 직접 등록한 영상은 그대로 꿀팁에 붙는다."
        )
        return None

    known_ids = db.get_known_video_ids()
    candidates = []
    for query in _todays_queries():
        for item in youtube_api.search(query, max_results=10):
            if item["video_id"] not in known_ids and item["video_id"] not in {c["video_id"] for c in candidates}:
                candidates.append(item)
        if len(candidates) >= MAX_CANDIDATES_PER_RUN:
            break

    if not candidates:
        logger.info("[HARVEST_DAILY_VIDEO] 새 후보 영상 없음(이미 다 본 영상이거나 검색 결과 없음)")
        return None

    candidates = candidates[:MAX_CANDIDATES_PER_RUN]
    details = youtube_api.fetch_details([c["video_id"] for c in candidates])

    for candidate in candidates:
        meta = details.get(candidate["video_id"], candidate)
        duration = meta.get("duration_seconds") or 0
        if duration and not (youtube_api.MIN_DURATION_SEC <= duration <= youtube_api.MAX_DURATION_SEC):
            continue

        transcript = youtube_api.fetch_transcript(candidate["video_id"])
        if not transcript:
            continue
        if not youtube_api.is_relevant_transcript(transcript["text"]):
            logger.info(f"[HARVEST_DAILY_VIDEO] 자막에 입시 얘기가 없음 video_id={candidate['video_id']} - 건너뜀")
            continue

        analysis = await _analyze_transcript(meta, transcript)
        if not analysis:
            return None  # AI 호출은 이미 썼다. 오늘은 여기서 끝낸다.
        if not analysis.get("is_useful"):
            logger.info(f"[HARVEST_DAILY_VIDEO] AI 판정: 입시생에게 유용하지 않음 video_id={candidate['video_id']}")
            return None

        row = _build_video_row(meta, transcript, analysis, source="api_search")
        db.upsert_insight_video(row)
        logger.info(f"[HARVEST_DAILY_VIDEO] 저장 완료 video_id={row['video_id']} "
                    f"parts={row['parts']} score={row['relevance_score']} 자막={row['transcript_chars']}자")
        return row

    logger.info(f"[HARVEST_DAILY_VIDEO] 후보 {len(candidates)}건 중 자막 있는 입시 영상 없음 - AI 호출 안 함")
    return None


async def add_video_manually(url_or_id: str, source: str = "manual") -> dict:
    """선생님이 영상 주소를 직접 등록할 때. 자막을 못 받으면 등록을 거부한다.

    주의: 이 경로도 Gemini를 1회 쓴다. 하루 여러 건을 몰아 넣으면 학생 챗봇 몫이 줄어든다.
    """
    logger.info(f"[ADD_VIDEO_MANUALLY] 시작 input={str(url_or_id)[:80]!r}")

    video_id = youtube_api.extract_video_id(url_or_id)
    if not video_id:
        raise ValidationError("유튜브 영상 주소를 알아볼 수 없습니다. 주소를 다시 확인해 주세요.")

    transcript = youtube_api.fetch_transcript(video_id)
    if not transcript:
        raise ValidationError(
            "이 영상은 자막을 받아올 수 없어 등록할 수 없습니다. "
            "자막(자동 생성 포함)이 켜져 있는 영상만 꿀팁에 붙일 수 있습니다."
        )

    # Data API 키가 있으면 길이/조회수까지, 없으면 watch 페이지에서 제목·채널만이라도.
    # 이 fallback이 없으면 학생 화면에 "유튜브 영상 vWvwVliDscc" 같은 제목이 나간다.
    details = youtube_api.fetch_details([video_id])
    meta = details.get(video_id) or youtube_api.fetch_basic_meta(video_id) or {
        "video_id": video_id,
        "title": f"유튜브 영상 {video_id}",
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }

    if not GEMINI_API_KEY:
        raise ValidationError("AI 분석 키(GEMINI_API_KEY)가 설정되지 않아 영상 내용을 분석할 수 없습니다.")

    analysis = await _analyze_transcript(meta, transcript)
    if not analysis:
        raise ValidationError("영상 자막 분석에 실패했습니다. 잠시 후 다시 시도해 주세요.")

    row = _build_video_row(meta, transcript, analysis, source=source)
    db.upsert_insight_video(row)
    logger.info(f"[ADD_VIDEO_MANUALLY] 저장 완료 video_id={video_id} parts={row['parts']}")
    return row


def pick_video_for_part(part: Optional[str]) -> Optional[dict]:
    """꿀팁 카드에 붙일 영상 하나."""
    return db.pick_video_for_part(part)


def mark_used(video_id: str) -> None:
    db.mark_video_used(video_id, datetime.now().isoformat())


def list_videos(limit: int = 100) -> list:
    logger.info(f"[LIST_VIDEOS] 시작 limit={limit}")
    return db.get_all_videos(limit)


def set_active(video_id: str, is_active: int) -> int:
    logger.info(f"[SET_VIDEO_ACTIVE] 시작 video_id={video_id} is_active={is_active}")
    changed = db.set_video_active_status(video_id, is_active)
    if changed == 0:
        raise NotFoundError("영상을 찾을 수 없습니다.")
    return is_active
