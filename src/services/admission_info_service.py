# -*- coding: utf-8 -*-
"""입시 정보 센터 서비스 — 매일 공고를 모아 쌓고, 선생님이 승인한 것만 학생에게 보낸다.

흐름:
  1. 대학 공식 게시판에서 새 공고를 긁는다 (src/knowledge/info_sources.py)
  2. 이미 있는 공고는 content_hash로 걸러내고, 새 것만 pending으로 저장
  3. 새로 들어온 것들을 **한 번의 AI 호출로 묶어** 분류한다
     (카테고리 / 대상 파트 / 마감일 / 한 줄 요약)
  4. 선생님이 승인 -> 그때부터 학생 화면에 보인다

왜 승인 단계를 두는가: 자동 수집은 학교 홈페이지 구조에 기대고 있어서 언젠가는
엉뚱한 걸 긁어온다. 그게 바로 학생에게 노출되면 "우리 앱이 틀린 입시 정보를 줬다"가
된다. 사람이 한 번 보고 넘기는 단계가 그 사고를 막는다.

AI 호출은 하루 1회로 묶는다(새 공고가 없으면 0회).
"""
import asyncio
import hashlib
import json
import logging
from datetime import datetime
from typing import List, Optional

from src import db
from src.errors import NotFoundError, ValidationError
from src.gemini_client import GEMINI_API_KEY, get_client, strip_code_fence
from src.knowledge import info_sources

logger = logging.getLogger("passion_mate")

PARTS = ["일렉기타", "베이스", "작곡", "보컬", "미디", "드럼"]

CATEGORIES = ["모집요강", "실기일정", "입시설명회", "합격발표", "등록서류", "기타"]

# 한 번의 AI 호출로 분류할 공고 수 상한. 이보다 많이 들어온 날은 나머지를
# 분류 없이 pending으로 남겨둔다(선생님이 제목만 보고도 승인할 수 있다).
MAX_ITEMS_PER_AI_CALL = 25


def _content_hash(school: Optional[str], title: str, external_id: Optional[str] = None) -> str:
    """같은 공고를 매일 다시 저장하지 않기 위한 지문.

    external_id(게시판 글번호)가 있으면 그걸 쓴다 — 제목이 수정돼도 같은 글로 본다.
    """
    seed = external_id or f"{school or ''}|{title}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


async def _classify_items(items: List[dict]) -> List[dict]:
    """새 공고들을 한 번의 AI 호출로 분류한다. 실패하면 빈 목록(분류 없이 둔다)."""
    if not items or not GEMINI_API_KEY:
        return []

    listing = "\n".join(
        f'{i + 1}. [{it.get("school", "")}/{it.get("board_name", "")}] '
        f'(작성일 {it.get("posted_at") or "미상"}) {it["title"]}'
        for i, it in enumerate(items)
    )
    today = datetime.now().strftime("%Y-%m-%d")

    prompt = (
        "당신은 실용음악 입시 담당 선생님입니다. 아래는 대학 공식 게시판에서 오늘 새로 수집한 "
        "공고 제목 목록입니다. 각 공고를 입시생이 보기 좋게 분류해 주세요.\n\n"
        f"[오늘 날짜] {today}\n\n"
        f"[수집된 공고]\n{listing}\n\n"
        "아래 형태의 JSON 배열 하나만 반환하세요. 설명이나 코드펜스(```)는 절대 붙이지 마세요.\n"
        '[{"index": 1, "category": "실기일정", "summary": "한 줄 설명", '
        '"parts": [], "deadline": null}, ...]\n\n'
        "규칙:\n"
        f"1. index는 위 번호 그대로. 목록에 있는 {len(items)}개 전부에 대해 답하세요.\n"
        f"2. category는 반드시 이 중 하나: {', '.join(CATEGORIES)}\n"
        "3. summary는 제목에 실제로 담긴 내용만 한 문장으로 풀어 쓰세요. "
        "제목에 없는 날짜나 조건을 추측해서 만들어 내지 마세요.\n"
        f"4. parts는 특정 전공에만 해당할 때만 채우고, 전 파트 공통이면 빈 배열 []. "
        f"쓸 수 있는 값: {', '.join(PARTS)}\n"
        "5. deadline은 제목에 명확한 날짜가 있을 때만 \"YYYY-MM-DD\"로, 없으면 null.\n"
        "6. 이모지를 쓰지 마세요."
    )

    try:
        response = await asyncio.to_thread(
            get_client().models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
        )
        parsed = json.loads(strip_code_fence(response.text))
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        logger.exception("[CLASSIFY_ITEMS] Gemini 응답이 JSON이 아님 - 분류 없이 진행")
        return []
    except Exception:
        logger.exception("[CLASSIFY_ITEMS] Gemini 분류 실패 - 분류 없이 진행")
        return []


async def collect_daily_info() -> dict:
    """하루 1회: 공고를 모으고, 새로 들어온 것만 AI로 분류한다."""
    logger.info("[COLLECT_DAILY_INFO] 시작")

    try:
        raw_items = info_sources.collect_all()
    except Exception:
        logger.exception("[COLLECT_DAILY_INFO] 수집 단계에서 예외 - 오늘 수집 건너뜀")
        return {"collected": 0, "new": 0, "classified": 0}

    now_iso = datetime.now().isoformat()
    new_items = []
    for item in raw_items:
        record = {
            "content_hash": _content_hash(item.get("school"), item["title"], item.get("external_id")),
            "title": item["title"],
            "school": item.get("school"),
            "board_name": item.get("board_name"),
            "posted_at": item.get("posted_at"),
            "source_url": item.get("url"),
            "source_type": "auto_crawl",
            "source_key": item.get("source_key"),
            "status": "pending",
            "collected_at": now_iso,
        }
        try:
            new_id = db.insert_admission_info(record)
            if new_id:
                record["id"] = new_id
                new_items.append(record)
        except Exception:
            logger.exception(f"[COLLECT_DAILY_INFO] 저장 실패 title={item['title'][:50]!r}")

    logger.info(f"[COLLECT_DAILY_INFO] 수집 {len(raw_items)}건 중 신규 {len(new_items)}건")

    if not new_items:
        # 새 게 없으면 AI를 부르지 않는다 — 무료 티어를 아끼는 가장 쉬운 방법.
        return {"collected": len(raw_items), "new": 0, "classified": 0}

    to_classify = new_items[:MAX_ITEMS_PER_AI_CALL]
    classifications = await _classify_items(to_classify)

    classified = 0
    for entry in classifications:
        try:
            idx = int(entry.get("index", 0)) - 1
            if not (0 <= idx < len(to_classify)):
                continue
            # 저장할 때 받아둔 id를 그대로 쓴다(예전엔 여기서 매번 전체 목록을 다시
            # 읽어 해시로 찾았는데, 공고 한 건마다 테이블을 통째로 훑는 셈이었다).
            target_id = to_classify[idx].get("id")
            if not target_id:
                continue

            category = entry.get("category")
            fields = {
                "category": category if category in CATEGORIES else "기타",
                "summary": entry.get("summary"),
                "parts": [p for p in (entry.get("parts") or []) if p in PARTS],
                "deadline": entry.get("deadline") or None,
            }
            db.update_admission_info_fields(target_id, fields)
            classified += 1
        except Exception:
            logger.exception("[COLLECT_DAILY_INFO] 분류 결과 반영 실패")

    logger.info(f"[COLLECT_DAILY_INFO] 완료 신규 {len(new_items)}건 중 {classified}건 분류됨 "
                f"(전부 승인 대기 상태 - 선생님 확인 필요)")
    return {"collected": len(raw_items), "new": len(new_items), "classified": classified}


def list_for_student(part: Optional[str] = None, limit: int = 20) -> List[dict]:
    """학생 화면용 — 승인된 공고만, 최신순."""
    logger.info(f"[LIST_FOR_STUDENT] 시작 part={part} limit={limit}")
    return db.get_admission_info(status="approved", part=part, limit=limit)


def list_for_teacher(status: Optional[str] = None, limit: int = 100) -> List[dict]:
    """선생님 대시보드용 — 상태 무관 전체 조회 가능."""
    logger.info(f"[LIST_FOR_TEACHER] 시작 status={status} limit={limit}")
    return db.get_admission_info(status=status, part=None, limit=limit)


def status_counts() -> dict:
    return db.count_admission_info_by_status()


def set_status(info_id: int, status: str, approved_by: Optional[str] = None) -> dict:
    """승인/반려. 승인된 순간부터 학생에게 보인다."""
    logger.info(f"[SET_ADMISSION_STATUS] 시작 info_id={info_id} status={status} by={approved_by}")
    if status not in ("approved", "rejected", "pending"):
        raise ValidationError("승인 상태 값이 올바르지 않습니다.")

    if db.set_admission_info_status(info_id, status, approved_by) == 0:
        raise NotFoundError("해당 입시 정보를 찾을 수 없습니다.")
    return db.get_admission_info_by_id(info_id)


def add_manually(title: str, summary: Optional[str], school: Optional[str],
                 category: Optional[str], parts: Optional[List[str]],
                 deadline: Optional[str], source_url: Optional[str],
                 created_by: Optional[str]) -> dict:
    """선생님이 직접 입력 — 자동 수집이 막힌 학교(robots 금지)나 현장 정보가 여기로 들어온다.

    사람이 넣은 것이므로 승인 단계를 거치지 않고 바로 approved.
    """
    logger.info(f"[ADD_ADMISSION_MANUALLY] 시작 title={str(title)[:50]!r} by={created_by}")

    title = (title or "").strip()
    if not title:
        raise ValidationError("제목을 입력해 주세요.")

    now_iso = datetime.now().isoformat()
    record = {
        "content_hash": _content_hash(school, title, external_id=f"manual:{title}:{now_iso}"),
        "title": title,
        "summary": (summary or "").strip() or None,
        "school": (school or "").strip() or None,
        "board_name": None,
        "category": category if category in CATEGORIES else "기타",
        "parts": [p for p in (parts or []) if p in PARTS],
        "deadline": (deadline or "").strip() or None,
        "source_url": (source_url or "").strip() or None,
        "source_type": "teacher",
        "source_key": None,
        "status": "approved",
        "approved_by": created_by,
        "approved_at": now_iso,
        "collected_at": now_iso,
    }
    new_id = db.insert_admission_info(record)
    if not new_id:
        raise ValidationError("이미 같은 내용이 등록되어 있습니다.")

    return db.get_admission_info_by_id(new_id)
