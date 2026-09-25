# -*- coding: utf-8 -*-
"""논문 코퍼스 서비스 — 검증된 논문을 DB에 올려두고, 오늘 쓸 한 편을 골라준다.

꿀팁의 '무조건 논문 바탕' 규칙이 실제로 지켜지는 자리가 여기다.
`pick_todays_paper()`가 None을 돌려주면 그날 꿀팁은 **만들지 않는다.**
근거 없이 그럴듯한 조언을 내보내느니 "준비 중"이 낫다.
"""
import logging
from datetime import datetime
from typing import Optional

from src import db
from src.knowledge import crossref, openalex, papers_seed
from src.errors import NotFoundError

logger = logging.getLogger("passion_mate")


def sync_seed_corpus() -> dict:
    """papers_seed.json의 검증된 논문을 DB에 올린다. 서버 기동 때마다 호출해도 안전.

    이미 있는 DOI는 메타데이터만 갱신되고 사용 이력(use_count/last_used_at)은 남는다.
    """
    logger.info("[SYNC_SEED_CORPUS] 시작")
    seed = papers_seed.load_seed()
    if not seed:
        logger.error("[SYNC_SEED_CORPUS] 코퍼스 파일이 비어 있음 - "
                     "`.venv/Scripts/python.exe -m src.knowledge.papers_seed`로 먼저 생성해야 한다")
        return {"loaded": 0, "usable": 0}

    for paper in seed:
        try:
            db.upsert_research_paper(paper)
        except Exception:
            logger.exception(f"[SYNC_SEED_CORPUS] 논문 저장 실패 doi={paper.get('doi')}")

    usable = db.count_usable_papers()
    logger.info(f"[SYNC_SEED_CORPUS] 완료 적재={len(seed)}편 사용가능(근거초록 보유)={usable}편")
    return {"loaded": len(seed), "usable": usable}


def pick_todays_paper(topic: Optional[str] = None) -> Optional[dict]:
    """오늘의 근거 논문 한 편. 가장 오랫동안 안 쓴 것부터 돌아가며 고른다."""
    logger.info(f"[PICK_TODAYS_PAPER] 시작 topic={topic}")
    paper = db.pick_least_used_paper(topic)

    # 해당 주제에 쓸 논문이 다 떨어졌으면 주제를 풀고 다시 고른다.
    if paper is None and topic:
        logger.info(f"[PICK_TODAYS_PAPER] topic={topic} 에 쓸 논문 없음 - 주제 제한 해제하고 재시도")
        paper = db.pick_least_used_paper(None)

    if paper is None:
        logger.error("[PICK_TODAYS_PAPER] 쓸 수 있는 논문이 0편 - 오늘 꿀팁 생성 불가")
    return paper


def mark_used(doi: str) -> None:
    db.mark_paper_used(doi, datetime.now().isoformat())


def list_papers(limit: int = 200) -> list:
    logger.info(f"[LIST_PAPERS] 시작 limit={limit}")
    return db.get_all_papers(limit)


def add_paper_by_doi(doi: str, topic: str, angle: str) -> dict:
    """선생님이 논문을 직접 추가할 때 — DOI로 실존을 확인한 뒤에만 저장한다.

    확인이 안 되는 DOI는 저장하지 않고 에러를 낸다. 여기서 한 번 뚫리면
    '논문 기반'이라는 말 자체가 무너지기 때문에 예외를 두지 않는다.
    """
    logger.info(f"[ADD_PAPER_BY_DOI] 시작 doi={doi} topic={topic}")
    paper = crossref.verify_by_doi(doi)
    if not paper:
        raise NotFoundError(f"Crossref에서 확인되지 않는 DOI입니다: {doi}")

    # 초록이 없으면 OpenAlex로 한 번 더 찾아본다.
    extra = openalex.fetch_by_doi(paper["doi"]) or {}
    if not paper.get("abstract") and extra.get("abstract"):
        paper["abstract"] = extra["abstract"]
    if extra.get("open_access_url"):
        paper["open_access_url"] = extra["open_access_url"]

    paper.update({
        "topic": topic,
        "angle": angle,
        "has_evidence": bool(paper.get("abstract")),
        "verified_at": datetime.now().isoformat(),
    })
    db.upsert_research_paper(paper)

    if not paper["has_evidence"]:
        logger.warning(f"[ADD_PAPER_BY_DOI] 초록을 못 구해 근거 텍스트가 없음 doi={paper['doi']} - "
                       f"저장은 됐지만 꿀팁 생성에는 쓰이지 않는다")
    return paper
