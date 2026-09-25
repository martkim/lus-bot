"""Crossref 조회 클라이언트 — "이 논문이 진짜 있는가"를 확인하는 유일한 통로.

왜 이게 필요한가: 생성형 AI는 그럴듯한 가짜 논문(있지도 않은 저자/학술지/연도)을
아주 자연스럽게 지어낸다. 학생에게 "논문 근거"라고 보여주는 이상 그건 재앙이다.
그래서 이 앱은 **AI가 논문을 말하게 두지 않는다.** 논문은 여기서 DOI로 실존이
확인된 것만 DB에 들어가고, AI는 그 확인된 논문을 '쉬운 말로 풀어쓰는' 일만 한다.

Crossref는 API 키가 필요 없고, User-Agent에 연락처를 적어주면 정중한 사용자로
분류돼 더 안정적인 응답을 받는다(polite pool).
"""
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from typing import Optional

logger = logging.getLogger("passion_mate")

CROSSREF_API = "https://api.crossref.org/works"
USER_AGENT = "PassionMate/1.0 (https://passionmate.app; mailto:guitarlessonroom1@gmail.com)"

# 제목이 이 정도는 겹쳐야 "같은 논문"으로 인정한다. 너무 낮추면 엉뚱한 논문이
# 붙고, 너무 높이면 부제/대소문자 차이로 진짜 논문을 놓친다.
TITLE_MATCH_THRESHOLD = 0.70

# Crossref에는 같은 논문의 '학회 초록 stub'이 함께 올라와 있는 경우가 많다.
# (APA PsycEXTRA의 10.1037/e...., 경영학회 프로시딩의 ...abstract 등)
# 제목이 거의 같아서 점수로는 안 걸러지는데, 실제로는 한 페이지짜리 초록이라
# 학생에게 보여줄 근거로 쓸 수 없다. DOI 모양으로 먼저 쳐낸다.
STUB_DOI_PATTERNS = (
    re.compile(r"^10\.1037/e\d+"),      # APA PsycEXTRA 등록물
    re.compile(r"abstract$"),            # ...10554abstract 같은 프로시딩 초록
    re.compile(r"^10\.1037/\d+-\d+$"),  # 서지 stub
)

# 학술지 논문을 기대하는 자리다. 다른 유형은 감점해서 뒤로 민다.
PREFERRED_TYPES = ("journal-article", "book-chapter", "posted-content")

_last_request_at = 0.0
_MIN_INTERVAL_SEC = 0.35  # Crossref에 대한 최소 호출 간격 (정중한 속도)


def _normalize(text: str) -> str:
    """제목 비교용 정규화 — 대소문자/구두점/공백 차이를 없앤다."""
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def _token_overlap(a: str, b: str) -> float:
    """두 제목이 같은 논문을 가리키는지 0~1로 점수화.

    단순 자카드만 쓰면 놓치는 게 있다 — Crossref는 부제를 잘라 저장하는 일이 잦다.
    실제로 "It's Not How Much; It's How: Characteristics of Practice Behavior and
    Retention of Performance Skills"가 Crossref에는 "It's Not How Much; It's How"로만
    올라와 있어, 자카드 0.38로 진짜 논문이 탈락했다.

    그래서 자카드와 '짧은 쪽이 긴 쪽에 얼마나 담기는가(포함율)' 중 큰 값을 쓴다.
    포함율은 제목이 통째로 잘린 경우를 살려주고, 단어가 너무 적은 제목에는
    적용하지 않아(3단어 미만) 아무거나 걸리는 걸 막는다.
    """
    ta = set(_normalize(a).split())
    tb = set(_normalize(b).split())
    if not ta or not tb:
        return 0.0

    shared = len(ta & tb)
    jaccard = shared / len(ta | tb)

    shorter = min(len(ta), len(tb))
    if shorter >= 3:
        containment = shared / shorter
        return max(jaccard, containment)
    return jaccard


def _throttled_get(url: str, timeout: int = 15) -> Optional[dict]:
    """Crossref 호출 — 최소 간격을 지키고, 실패는 None으로 삼킨다(호출측이 건너뛰게)."""
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
        logger.warning(f"[CROSSREF] 조회 실패 url={url[:120]} err={e}")
        return None


def _strip_jats(abstract: Optional[str]) -> Optional[str]:
    """Crossref 초록은 JATS XML 태그가 섞여 온다. 태그만 걷어낸다."""
    if not abstract:
        return None
    text = re.sub(r"<[^>]+>", " ", abstract)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _is_stub(doi: Optional[str]) -> bool:
    """학회 초록/서지 stub DOI인지 — 근거 논문으로 쓰면 안 되는 레코드."""
    if not doi:
        return True
    low = doi.lower()
    return any(p.search(low) for p in STUB_DOI_PATTERNS)


def _to_paper(item: dict) -> dict:
    """Crossref 원본 레코드를 앱이 쓰는 논문 dict으로 변환."""
    titles = item.get("title") or []
    authors = item.get("author") or []
    author_names = [
        " ".join(filter(None, [a.get("given"), a.get("family")])).strip()
        for a in authors
        if a.get("family")
    ]
    date_parts = (
        item.get("issued", {}).get("date-parts")
        or item.get("published-print", {}).get("date-parts")
        or item.get("published-online", {}).get("date-parts")
        or [[None]]
    )
    year = date_parts[0][0] if date_parts and date_parts[0] else None
    containers = item.get("container-title") or []

    return {
        "doi": item.get("DOI"),
        "title": titles[0] if titles else "",
        "authors": author_names,
        "year": year,
        "journal": containers[0] if containers else None,
        "url": f"https://doi.org/{item['DOI']}" if item.get("DOI") else None,
        "abstract": _strip_jats(item.get("abstract")),
        "cited_by": item.get("is-referenced-by-count", 0),
        "type": item.get("type"),
    }


def verify_by_title(title: str, author_surname: Optional[str] = None,
                    year: Optional[int] = None) -> Optional[dict]:
    """제목(+저자/연도)으로 Crossref에서 실제 논문을 찾아 메타데이터를 돌려준다.

    찾지 못하거나 제목이 충분히 닮지 않으면 None — 호출측은 그 논문을 **버린다.**
    '비슷한 걸로 대충 채우기'를 하지 않는 게 이 함수의 존재 이유다.
    """
    params = {"query.bibliographic": title, "rows": "5", "select":
              "DOI,title,author,issued,container-title,abstract,is-referenced-by-count,published-print,published-online,type"}
    if author_surname:
        params["query.author"] = author_surname

    data = _throttled_get(f"{CROSSREF_API}?{urllib.parse.urlencode(params)}")
    if not data:
        return None

    best, best_score = None, 0.0
    for item in data.get("message", {}).get("items", []):
        candidate = _to_paper(item)
        if not candidate["title"]:
            continue
        score = _token_overlap(title, candidate["title"])

        # 연도가 3년 넘게 어긋나면 동명의 다른 논문이다 — 후보에서 뺀다.
        if year and candidate["year"] and abs(candidate["year"] - year) > 3:
            continue
        # 1~3년 차이는 온라인 선공개/재수록일 수 있어 감점만.
        if year and candidate["year"] and candidate["year"] != year:
            score -= 0.05
        # 학회 초록 stub은 제목이 같아도 근거로 못 쓴다.
        if _is_stub(candidate["doi"]):
            score -= 0.5
        if candidate.get("type") and candidate["type"] not in PREFERRED_TYPES:
            score -= 0.15

        if score > best_score:
            best, best_score = candidate, score

    if best and best_score >= TITLE_MATCH_THRESHOLD:
        return best

    logger.info(f"[CROSSREF] 실존 확인 실패 — 코퍼스에서 제외 title={title[:70]!r} score={best_score:.2f}")
    return None


def verify_by_doi(doi: str) -> Optional[dict]:
    """DOI로 직접 실존 확인. 선생님이 논문을 직접 추가할 때 쓴다."""
    doi = doi.strip().replace("https://doi.org/", "").replace("http://dx.doi.org/", "")
    data = _throttled_get(f"{CROSSREF_API}/{urllib.parse.quote(doi)}")
    if not data or "message" not in data:
        return None
    return _to_paper(data["message"])
