# -*- coding: utf-8 -*-
"""OpenAlex 조회 — Crossref에 없는 '초록'을 메우는 두 번째 출처.

왜 필요한가: Crossref는 DOI 실존 확인에는 완벽하지만, 심리학·교육학 학술지는
초록을 Crossref에 거의 등록하지 않는다(54편 중 16편만 초록이 있었다). 초록이
없으면 AI가 기댈 원문이 없고, 그러면 결국 '그럴듯하게 지어내기'로 돌아간다.

OpenAlex는 키가 필요 없고 거의 모든 논문의 초록을 갖고 있다. 다만 초록을
`abstract_inverted_index`(단어 -> 등장 위치 목록) 형태로 주기 때문에 원래 문장으로
되돌리는 복원 과정이 필요하다.
"""
import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Optional

logger = logging.getLogger("passion_mate")

OPENALEX_API = "https://api.openalex.org/works"
# mailto를 붙이면 polite pool로 분류돼 응답이 안정적이다.
CONTACT_EMAIL = "guitarlessonroom1@gmail.com"
USER_AGENT = f"PassionMate/1.0 (https://passionmate.app; mailto:{CONTACT_EMAIL})"

_last_request_at = 0.0
_MIN_INTERVAL_SEC = 0.15


def _throttled_get(url: str, timeout: int = 15) -> Optional[dict]:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < _MIN_INTERVAL_SEC:
        time.sleep(_MIN_INTERVAL_SEC - elapsed)
    _last_request_at = time.monotonic()

    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:
        logger.info(f"[OPENALEX] 조회 실패 url={url[:110]} err={e}")
        return None


def _rebuild_abstract(inverted: Optional[dict]) -> Optional[str]:
    """`{단어: [위치...]}` 형태의 역색인을 원래 초록 문장으로 되돌린다."""
    if not inverted:
        return None
    positions = []
    for word, idxs in inverted.items():
        for i in idxs:
            positions.append((i, word))
    if not positions:
        return None
    positions.sort()
    text = " ".join(word for _, word in positions).strip()
    # 초록이 통째로 잘려 한두 단어만 오는 경우가 있어 최소 길이를 본다.
    return text if len(text) >= 120 else None


def fetch_by_doi(doi: str) -> Optional[dict]:
    """DOI로 OpenAlex 레코드를 가져와 초록/인용수/공개본 링크를 돌려준다."""
    if not doi:
        return None
    clean = doi.strip().replace("https://doi.org/", "").lower()
    data = _throttled_get(f"{OPENALEX_API}/doi:{urllib.parse.quote(clean)}")
    if not data:
        return None

    oa = (data.get("best_oa_location") or {}) or {}
    return {
        "abstract": _rebuild_abstract(data.get("abstract_inverted_index")),
        "cited_by": data.get("cited_by_count"),
        "open_access_url": oa.get("pdf_url") or oa.get("landing_page_url"),
        "type": data.get("type"),
        "openalex_id": data.get("id"),
    }
