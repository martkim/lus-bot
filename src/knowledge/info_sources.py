# -*- coding: utf-8 -*-
"""입시 정보 자동 수집 — 대학 공식 게시판에서 '새 공고가 떴다'를 매일 긁어온다.

수집하는 것과 안 하는 것을 분명히 해둔다:

- 수집한다: 공고 **제목, 작성일, 공식 링크, 어느 학교 어느 게시판인지**.
- 수집하지 않는다: 공고 **본문 전체**. 남의 공고문을 통째로 복사해 우리 앱에
  다시 싣지 않는다. 학생은 제목으로 "이게 떴구나"를 알고, 링크를 눌러 공식
  페이지에서 원문을 본다. 이게 저작권상으로도, 정확성 면에서도 맞다
  (공고는 수정·정정이 잦아서 우리가 복사해 둔 사본이 금방 틀린 정보가 된다).

robots.txt는 **매 수집마다** 확인한다. 한 번 보고 코드에 박아두지 않는 이유는
규칙이 바뀌기 때문이다. 실제로 2026-09 기준 동아방송예술대와 호원대는
`Disallow: /` 라 자동 수집 대상에서 빠져 있다 — 그 학교 정보는 선생님이
직접 입력하는 경로로 들어온다.

모든 수집물은 `pending` 상태로 들어가고, 선생님이 승인해야 학생에게 보인다.
"""
import html as html_module
import http.cookiejar
import logging
import re
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import date
from typing import List, Optional

logger = logging.getLogger("passion_mate")

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

# 같은 서버에 연달아 때리지 않는다. 하루 한 번 도는 수집기라 느려도 아무 상관 없다.
_POLITE_DELAY_SEC = 1.5
_last_fetch_at = {}

# robots.txt 파서를 호스트별로 캐시(한 번의 수집 사이클 동안만 유효).
_robots_cache = {}

# 게시판 목록에서 한 번에 가져올 최대 건수. 그날 새로 올라온 것만 추려낼 거라
# 넉넉하게 볼 필요가 없다.
MAX_ITEMS_PER_SOURCE = 15


# ----------------------------------------------------------------------------
# 수집 대상 레지스트리
# ----------------------------------------------------------------------------
# extractor 종류
#   egov_notice : 표준프레임워크(eGovFrame) 게시판. 목록 링크가
#                 javascript:fn_egov_inqire_notice('게시판ID','글번호') 형태다.
#                 국내 대학 홈페이지에서 제일 흔한 형태라 한 번 만들어두면 재사용된다.
#   anchor_list : 평범한 <a href="..."> 목록 게시판.
#
# warmup_url : 세션 쿠키를 먼저 받아야 목록이 나오는 사이트용(서울예대가 그렇다).
SOURCES = [
    {
        "key": "seoularts_practical_exam",
        "school": "서울예술대학교",
        "board_name": "실기고사 유의사항",
        "list_url": "https://www.seoularts.ac.kr/web/cop/bbsWeb/selectBoardList.do?bbsId=BBSMSTR_000000000711",
        "warmup_url": "https://www.seoularts.ac.kr/web/com/setEnvi.do",
        "extractor": "egov_notice",
        "enabled": True,
    },
    {
        "key": "seoularts_info_session",
        "school": "서울예술대학교",
        "board_name": "입학설명회 안내",
        "list_url": "https://www.seoularts.ac.kr/web/cop/bbsWeb/selectBoardList.do?bbsId=BBSMSTR_000000001547",
        "warmup_url": "https://www.seoularts.ac.kr/web/com/setEnvi.do",
        "extractor": "egov_notice",
        "enabled": True,
    },
    # 전문학사과정 = 고졸 신입학으로 들어오는 과정. 우리 학생들이 지원하는 곳이다.
    # 예전엔 BBSMSTR_000000001388을 "입시 공지사항"으로 걸어 뒀는데, 그건 학교
    # 메뉴에 '석사과정'으로 적혀 있는 대학원 게시판이라 수집분 10건이 전부
    # 전문기술석사과정 공고였다(2026-10-03 확인).
    {
        "key": "seoularts_admission_notice",
        "school": "서울예술대학교",
        "board_name": "입학 공지(전문학사)",
        "list_url": "https://www.seoularts.ac.kr/web/cop/bbsWeb/selectBoardList.do?bbsId=BBSMSTR_000000000702",
        "warmup_url": "https://www.seoularts.ac.kr/web/com/setEnvi.do",
        "extractor": "egov_notice",
        "enabled": True,
    },
    {
        "key": "seoularts_extra_pass",
        "school": "서울예술대학교",
        "board_name": "추가합격 발표",
        "list_url": "https://www.seoularts.ac.kr/web/cop/bbsWeb/selectBoardList.do?bbsId=BBSMSTR_000000001501",
        "warmup_url": "https://www.seoularts.ac.kr/web/com/setEnvi.do",
        "extractor": "egov_notice",
        "enabled": True,
    },
    {
        "key": "karts_notice",
        "school": "한국예술종합학교",
        "board_name": "공지사항",
        "list_url": "https://www.karts.ac.kr/cop/bbs/selectBoardList.do?bbsId=BBSMSTR_000000000035",
        "extractor": "anchor_list",
        "enabled": False,
        "disabled_reason": "한예종에는 실용음악 전공이 없다(음악원은 클래식·한국음악). "
                           "이 게시판에서 나온 건 사이드바 메뉴 4건과 2023~24년 뮤지컬아카데미 공고뿐이라, "
                           "우리 학생에게 쓸모 있는 글이 한 건도 없었다",
    },
    # robots.txt가 전체 수집을 금지한 곳 — 자동 수집 대상에서 뺀다.
    # 선생님이 대시보드에서 직접 입력하는 경로로 들어온다.
    {
        "key": "dima_notice",
        "school": "동아방송예술대학교",
        "board_name": "입학 공지",
        "list_url": "https://www.dima.ac.kr/",
        "extractor": "anchor_list",
        "enabled": False,
        "disabled_reason": "robots.txt가 전체 경로 수집을 금지(Disallow: /)",
    },
    {
        "key": "howon_notice",
        "school": "호원대학교",
        "board_name": "입학 공지",
        "list_url": "https://www.howon.ac.kr/",
        "extractor": "anchor_list",
        "enabled": False,
        "disabled_reason": "robots.txt가 전체 경로 수집을 금지(Disallow: /)",
    },
]

# 공고 제목에 이 말들이 없으면 입시생과 무관한 글(교내 행정 공지 등)로 본다.
ADMISSION_KEYWORDS = [
    "입시", "입학", "모집", "실기", "수시", "정시", "전형", "합격",
    "원서", "지원", "설명회", "요강", "면접", "고사", "등록",
]

# 위 키워드만으로는 못 거르는 것들. 우리 학생은 **고등학교 졸업 예정 실용음악 입시생**이라,
# 입학 관련 글이어도 대상이 다르면 화면에 올라가 봐야 혼란만 준다.
# 2026-09 수집분 29건 중 10건이 전문기술석사과정 공고였고, 4건은 '장애학생지원센터'
# 같은 사이드바 메뉴였다("지원", "등록"이 키워드에 걸려 통과했다).
EXCLUDE_KEYWORDS = [
    # 대상이 다른 과정 — 고졸 신입학이 아니다
    "석사", "박사", "대학원", "전공심화", "편입", "재입학", "평생교육", "최고위",
    # 게시판이 아니라 학교 조직·행정 페이지(메뉴 링크가 딸려 들어온다).
    # '센터'를 통째로 막지 않는 이유: 고사장 안내에 '예술센터' 같은 건물 이름이 나온다.
    "위원회", "심의", "지원센터", "신고센터", "상담센터", "취업", "진로",
    "채용", "임용", "교직원",
]

# 입시는 학년도 단위로 돌아간다. 3월이면 이미 다음 학년도 모집이 시작되므로
# (수시 요강 공고 -> 9월 원서 -> 이듬해 2월 정시 종료) 그 시점부터 +1년으로 본다.
_YEAR_IN_TITLE = re.compile(r"(20\d{2})\s*학년도")
_STALE_DAYS_WITHOUT_YEAR = 365


def _session() -> urllib.request.OpenerDirector:
    """쿠키를 물고 다니는 오프너. 서울예대처럼 세션을 먼저 요구하는 곳이 있다."""
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    opener.addheaders = [("User-Agent", USER_AGENT),
                         ("Accept-Language", "ko-KR,ko;q=0.9")]
    return opener


def _robots_allowed(url: str) -> bool:
    """이 주소를 긁어도 되는지 robots.txt에 물어본다.

    robots.txt가 아예 없으면(404) 제한을 두지 않은 것으로 보고 허용한다.
    읽다가 실패하면 **허용하지 않는다** — 확인 못 한 채로 긁는 것보다 건너뛰는 게 낫다.
    """
    parsed = urllib.parse.urlparse(url)
    host_key = f"{parsed.scheme}://{parsed.netloc}"

    if host_key not in _robots_cache:
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(f"{host_key}/robots.txt")
        try:
            parser.read()
            _robots_cache[host_key] = parser
        except Exception as e:
            logger.warning(f"[INFO_SOURCES] robots.txt 확인 실패 host={host_key} err={e} - 수집 건너뜀")
            _robots_cache[host_key] = None

    parser = _robots_cache[host_key]
    if parser is None:
        return False
    try:
        return parser.can_fetch(USER_AGENT, url)
    except Exception:
        return False


def _polite_fetch(opener, url: str, data: Optional[bytes] = None, timeout: int = 20) -> Optional[str]:
    """같은 호스트에 연달아 때리지 않으면서 페이지를 가져온다."""
    host = urllib.parse.urlparse(url).netloc
    elapsed = time.monotonic() - _last_fetch_at.get(host, 0.0)
    if elapsed < _POLITE_DELAY_SEC:
        time.sleep(_POLITE_DELAY_SEC - elapsed)
    _last_fetch_at[host] = time.monotonic()

    try:
        req = urllib.request.Request(url, data=data)
        with opener.open(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception as e:
        logger.warning(f"[INFO_SOURCES] 페이지 수집 실패 url={url[:100]} err={type(e).__name__}")
        return None


_HTML_COMMENT = re.compile(r"<!--.*?(?:-->|$)", re.S)
# 게시판 목록의 링크 텍스트에는 글번호와 분류가 먼저 붙어 들어온다
# (한예종이 "83 전체 2024 한예종 ..." 형태라 제목이 저 숫자부터 시작했다).
# 20xx로 시작하면 글번호가 아니라 연도다 — "2027학년도 수시 모집요강"에서 연도를
# 떼어내면 지난 학년도 판정이 작성일로 떨어져 버린다.
_LIST_PREFIX = re.compile(r"^\s*(?!20\d{2})\d{1,4}\s*(?:전체|공지|일반|NEW)?\s*")


def _clean(text: str) -> str:
    # 주석을 태그보다 먼저 지운다. <[^>]+>로는 닫히지 않은 <!-- 가 제목 끝에 남는다.
    text = _HTML_COMMENT.sub(" ", text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    # 엔티티는 태그를 지운 뒤에 푼다. 먼저 풀면 &lt;b&gt;가 진짜 태그가 돼 지워진다.
    # 서울예대 제목에 "&lt;2026.9.30.(수) 17:00 기준&gt;"처럼 꺾쇠가 자주 들어간다.
    text = html_module.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return _LIST_PREFIX.sub("", text).strip()


_EGOV_ROW = re.compile(
    r"fn_egov_inqire_notice\('(BBSMSTR_\d+)',\s*'(\d+)'\);\"[^>]*>([^<]+)"
)
_DATE_NEAR = re.compile(r"(20\d{2})[-.](\d{1,2})[-.](\d{1,2})")


def _extract_egov_notice(html: str, source: dict) -> List[dict]:
    """eGovFrame 게시판 목록에서 (제목, 글번호, 작성일)을 뽑는다.

    목록 링크가 평범한 href가 아니라 javascript: 호출이라 일반 링크 파서로는
    한 건도 안 잡힌다. 실제로 이것 때문에 처음엔 '게시판이 비어 있다'고 잘못 판단했다.
    """
    items = []
    for match in _EGOV_ROW.finditer(html):
        bbs_id, ntt_id, raw_title = match.groups()
        title = _clean(raw_title)
        if not title:
            continue

        # 제목 바로 뒤에 "작성일 : 2026-01-18" 이 따라온다. 못 찾으면 날짜 없음으로 둔다.
        tail = html[match.end():match.end() + 1200]
        date_match = _DATE_NEAR.search(tail)
        posted_at = (f"{date_match.group(1)}-{int(date_match.group(2)):02d}-"
                     f"{int(date_match.group(3)):02d}") if date_match else None

        items.append({
            "title": title,
            "posted_at": posted_at,
            # 상세 페이지는 POST로만 열려서 그냥 링크로 줄 수 없다.
            # 학생은 게시판 목록으로 보내고, 거기서 해당 글을 누르게 한다.
            "url": source["list_url"],
            "external_id": f"{bbs_id}:{ntt_id}",
        })
        if len(items) >= MAX_ITEMS_PER_SOURCE:
            break
    return items


_ANCHOR_ROW = re.compile(r"<a\s[^>]*href=[\"']([^\"'#][^\"']*)[\"'][^>]*>(.*?)</a>", re.S | re.I)


def _extract_anchor_list(html: str, source: dict) -> List[dict]:
    """평범한 링크 목록 게시판에서 공고처럼 보이는 링크만 골라낸다."""
    items, seen = [], set()
    for match in _ANCHOR_ROW.finditer(html):
        href, raw_title = match.groups()
        title = _clean(raw_title)
        # 제목이 너무 짧으면 메뉴/버튼이고, 너무 길면 본문 덩어리다.
        if not (8 <= len(title) <= 120) or title in seen:
            continue
        if not any(kw in title for kw in ADMISSION_KEYWORDS):
            continue
        seen.add(title)

        tail = html[match.end():match.end() + 600]
        date_match = _DATE_NEAR.search(tail)
        posted_at = (f"{date_match.group(1)}-{int(date_match.group(2)):02d}-"
                     f"{int(date_match.group(3)):02d}") if date_match else None

        items.append({
            "title": title,
            "posted_at": posted_at,
            "url": urllib.parse.urljoin(source["list_url"], href),
            "external_id": urllib.parse.urljoin(source["list_url"], href),
        })
        if len(items) >= MAX_ITEMS_PER_SOURCE:
            break
    return items


_EXTRACTORS = {
    "egov_notice": _extract_egov_notice,
    "anchor_list": _extract_anchor_list,
}


def current_admission_year(today: Optional[date] = None) -> int:
    """지금 돌아가고 있는 입시 학년도. 3월부터는 다음 학년도가 현재 사이클이다."""
    today = today or date.today()
    return today.year + 1 if today.month >= 3 else today.year


def is_current_cycle(title: str, posted_at: Optional[str], today: Optional[date] = None) -> bool:
    """지난 학년도 공고를 걸러낸다.

    제목에 학년도가 적혀 있으면 그걸 믿는다 — 작성일보다 정확하다(2027학년도 요강이
    2026년에 올라온다). 학년도가 없으면 작성일로 보고, 둘 다 없으면 통과시켜
    선생님이 판단하게 둔다. 자동으로 버리는 것보다 사람이 한 번 보는 쪽이 낫다.
    """
    today = today or date.today()
    match = _YEAR_IN_TITLE.search(title or "")
    if match:
        return int(match.group(1)) >= current_admission_year(today)

    if posted_at:
        try:
            posted = date.fromisoformat(posted_at)
        except ValueError:
            return True
        return (today - posted).days <= _STALE_DAYS_WITHOUT_YEAR

    return True


def is_admission_related(title: str) -> bool:
    """입시생에게 의미 있는 공고인지 제목으로 1차 선별."""
    title = title or ""
    if any(kw in title for kw in EXCLUDE_KEYWORDS):
        return False
    return any(kw in title for kw in ADMISSION_KEYWORDS)


def fetch_source(source: dict) -> List[dict]:
    """소스 하나를 수집한다. robots가 막으면 아무것도 안 하고 빈 목록."""
    if not source.get("enabled", True):
        logger.info(f"[FETCH_SOURCE] 비활성 소스 건너뜀 key={source['key']} "
                    f"reason={source.get('disabled_reason', '수동 비활성')}")
        return []

    if not _robots_allowed(source["list_url"]):
        logger.warning(f"[FETCH_SOURCE] robots.txt가 수집을 금지 key={source['key']} - 건너뜀")
        return []

    opener = _session()
    if source.get("warmup_url"):
        _polite_fetch(opener, source["warmup_url"])

    html = _polite_fetch(opener, source["list_url"])
    if not html:
        return []

    extractor = _EXTRACTORS.get(source["extractor"])
    if not extractor:
        logger.error(f"[FETCH_SOURCE] 알 수 없는 추출기 key={source['key']} extractor={source['extractor']}")
        return []

    raw_items = extractor(html, source)
    items = []
    dropped_unrelated = dropped_stale = 0
    for item in raw_items:
        if not is_admission_related(item["title"]):
            dropped_unrelated += 1
            continue
        if not is_current_cycle(item["title"], item.get("posted_at")):
            dropped_stale += 1
            continue
        item.update({
            "school": source["school"],
            "board_name": source["board_name"],
            "source_key": source["key"],
        })
        items.append(item)

    logger.info(f"[FETCH_SOURCE] key={source['key']} 추출 {len(raw_items)}건 -> 통과 {len(items)}건 "
                f"(대상밖 {dropped_unrelated}건, 지난 학년도 {dropped_stale}건)")
    return items


def collect_all() -> List[dict]:
    """활성화된 모든 소스를 한 바퀴 돈다. 한 곳이 실패해도 나머지는 계속 간다."""
    _robots_cache.clear()  # 사이클마다 robots를 새로 확인한다(규칙은 바뀐다)
    collected = []
    # 학교가 같은 공고를 여러 게시판에 함께 올린다(입학설명회가 '입학설명회' 게시판과
    # '입학 공지'에 같이 떴다). 저장 지문은 게시판 글번호 기준이라 둘 다 들어가서,
    # 선생님은 같은 글을 두 번 승인해야 한다. 한 사이클 안에서 먼저 나온 것만 남긴다.
    seen_titles = set()
    duplicates = 0
    for source in SOURCES:
        try:
            for item in fetch_source(source):
                key = (item.get("school"), item["title"])
                if key in seen_titles:
                    duplicates += 1
                    continue
                seen_titles.add(key)
                collected.append(item)
        except Exception as e:
            logger.exception(f"[COLLECT_ALL] 소스 수집 중 예외 key={source.get('key')}")
            logger.error(f"[COLLECT_ALL] key={source.get('key')} 실패(계속 진행): {e}")
    logger.info(f"[COLLECT_ALL] 총 {len(collected)}건 수집 (소스 {len(SOURCES)}개, 중복 {duplicates}건 제외)")
    return collected
