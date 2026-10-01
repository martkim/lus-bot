# -*- coding: utf-8 -*-
"""유튜브 계층 — 영상을 '찾고', 그 영상의 '실제 자막'을 받아온다.

두 가지를 확실히 구분한다:

1. 검색(search): YouTube Data API v3. `YOUTUBE_API_KEY`가 있어야 한다.
   키가 없으면 검색만 꺼지고, 선생님이 직접 등록한 영상은 그대로 동작한다.

2. 자막(transcript): `youtube-transcript-api` 라이브러리. **키가 필요 없다.**
   원래는 유튜브의 timedtext 주소를 직접 부르려 했는데, 지금은 전부 빈 응답이
   돌아온다(유튜브가 PO 토큰으로 막았다). 이 라이브러리는 그 과정을 대신 처리해
   주고, 이 PC에서 실제 자막이 나오는 것을 확인했다.

자막이 이 기능의 핵심이다. 자막을 못 받은 영상은 **꿀팁에 붙이지 않는다** —
제목만 보고 내용을 짐작해 요약하면 그게 바로 지어내기이기 때문이다.
"""
import html as html_module
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from typing import List, Optional

logger = logging.getLogger("passion_mate")

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
SEARCH_ENDPOINT = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"

# 자막을 찾을 언어 우선순위. 한국어가 없으면 영어라도 받는다(해외 음대 인터뷰 대비).
TRANSCRIPT_LANGUAGES = ["ko", "ko-KR", "en", "en-US"]

# 너무 짧은 영상(쇼츠/티저)은 인터뷰가 아니고, 너무 긴 건 강의 전체라 꿀팁으로 못 쓴다.
MIN_DURATION_SEC = 120
MAX_DURATION_SEC = 5400

# 자막이 이보다 짧으면 사실상 내용이 없는 것으로 본다.
MIN_TRANSCRIPT_CHARS = 400

# 검색어 묶음 — "실제 학생이 나와서 말하는" 영상을 겨냥한다.
# 파트 이름은 서비스 계층에서 {part}에 끼워 넣는다.
SEARCH_QUERIES_GENERAL = [
    "서울예대 실용음악과 합격 인터뷰",
    "실용음악과 입시 합격생 인터뷰",
    "실용음악 입시 꿀팁 합격생",
    "예대 실용음악과 재학생 인터뷰",
    "실용음악과 입시 준비 과정 인터뷰",
    "음대 입시 합격생 연습 방법",
]
# 전공별 검색어 — 찾으려는 건 세 갈래다.
#   1) 인터뷰      : 합격생이 직접 말하는 준비 과정
#   2) 연습 방법    : 그 전공의 실기를 실제로 어떻게 연습했는가
#   3) 실기장 질문  : 시험장에서 실제로 받은 질문과 분위기
# harvest는 후보가 찰 때까지 이 순서대로 검색하고 멈춘다. 그래서 앞쪽에
# 둔 갈래가 더 자주 잡힌다 — 합격생이 직접 말하는 인터뷰를 맨 앞에 둔 이유다.
SEARCH_QUERIES_BY_PART = [
    # 1) 인터뷰
    "실용음악 {part} 입시 합격생 인터뷰",
    "{part} 전공 실용음악과 합격 후기",
    # 2) 연습 방법
    "{part} 입시 실기 연습 방법",
    "실용음악 {part} 입시곡 연습 과정",
    # 3) 실기장에서 실제로 받은 질문
    "실용음악과 {part} 실기시험 후기 받은 질문",
    "{part} 입시 면접 질문 실용음악과",
]

# 자막에 이런 말이 하나도 안 나오면 입시생용 영상이 아니라고 본다.
RELEVANCE_KEYWORDS = [
    "입시", "실기", "합격", "연습", "전공", "예대", "음대", "대학",
    "오디션", "시험", "준비", "레슨", "전공실기", "면접",
]


def is_configured() -> bool:
    """검색 기능(Data API)을 쓸 수 있는가. 자막 수집은 이것과 무관하게 동작한다."""
    return bool(YOUTUBE_API_KEY)


def extract_video_id(url_or_id: str) -> Optional[str]:
    """유튜브 주소에서 영상 ID를 뽑는다. 선생님이 어떤 형태로 붙여넣어도 받도록.

    지원: watch?v=, youtu.be/, /embed/, /shorts/, 그리고 ID 자체.
    """
    if not url_or_id:
        return None
    text = url_or_id.strip()

    # 이미 ID 형태(11자)면 그대로
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text

    patterns = [
        r"[?&]v=([A-Za-z0-9_-]{11})",
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"/embed/([A-Za-z0-9_-]{11})",
        r"/shorts/([A-Za-z0-9_-]{11})",
        r"/live/([A-Za-z0-9_-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return None


def _api_get(endpoint: str, params: dict) -> Optional[dict]:
    params = dict(params, key=YOUTUBE_API_KEY)
    url = f"{endpoint}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PassionMate/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:
        # 할당량 초과(403)도 여기로 온다 — 그날 검색을 포기하고 내일 다시 하면 된다.
        logger.warning(f"[YOUTUBE_API] 호출 실패 endpoint={endpoint.rsplit('/', 1)[-1]} err={e}")
        return None


def _parse_iso_duration(value: str) -> int:
    """'PT12M34S' 형태를 초로 바꾼다."""
    m = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not m:
        return 0
    days, hours, minutes, seconds = (int(g or 0) for g in m.groups())
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


def search(query: str, max_results: int = 10, days_back: Optional[int] = None) -> List[dict]:
    """검색어로 영상 후보를 찾는다. 키가 없으면 빈 목록(호출측이 알아서 건너뜀)."""
    if not is_configured():
        logger.info("[YOUTUBE_SEARCH] YOUTUBE_API_KEY 없음 - 자동 검색 건너뜀(수동 등록 영상은 정상 동작)")
        return []

    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": str(min(max_results, 25)),
        "relevanceLanguage": "ko",
        "regionCode": "KR",
        "videoEmbeddable": "true",
        "order": "relevance",
    }
    if days_back:
        from datetime import datetime, timedelta, timezone
        after = datetime.now(timezone.utc) - timedelta(days=days_back)
        params["publishedAfter"] = after.strftime("%Y-%m-%dT%H:%M:%SZ")

    data = _api_get(SEARCH_ENDPOINT, params)
    if not data:
        return []

    results = []
    for item in data.get("items", []):
        vid = (item.get("id") or {}).get("videoId")
        snip = item.get("snippet") or {}
        if not vid:
            continue
        results.append({
            "video_id": vid,
            "title": snip.get("title", ""),
            "channel": snip.get("channelTitle", ""),
            "description": snip.get("description", ""),
            "published_at": snip.get("publishedAt"),
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
    logger.info(f"[YOUTUBE_SEARCH] query={query!r} 후보 {len(results)}건")
    return results


def fetch_details(video_ids: List[str]) -> dict:
    """영상 ID들의 길이/조회수 등을 한 번에 받아 {video_id: 상세} 로 돌려준다."""
    if not is_configured() or not video_ids:
        return {}

    data = _api_get(VIDEOS_ENDPOINT, {
        "part": "snippet,contentDetails,statistics",
        "id": ",".join(video_ids[:50]),
    })
    if not data:
        return {}

    out = {}
    for item in data.get("items", []):
        snip = item.get("snippet") or {}
        stats = item.get("statistics") or {}
        details = item.get("contentDetails") or {}
        out[item["id"]] = {
            "video_id": item["id"],
            "title": snip.get("title", ""),
            "channel": snip.get("channelTitle", ""),
            "description": snip.get("description", ""),
            "published_at": snip.get("publishedAt"),
            "duration_seconds": _parse_iso_duration(details.get("duration", "")),
            "view_count": int(stats.get("viewCount", 0) or 0),
            "url": f"https://www.youtube.com/watch?v={item['id']}",
        }
    return out


def fetch_basic_meta(video_id: str) -> Optional[dict]:
    """Data API 키 없이 영상 제목/채널만 가져온다(watch 페이지의 og: 메타 태그).

    선생님이 키 없이 영상을 직접 등록할 때를 위한 것이다. 이게 없으면 학생 화면에
    "유튜브 영상 vWvwVliDscc" 같은 제목이 그대로 나간다.
    자막과 달리 여긴 실패해도 큰 문제가 아니라, 실패하면 None을 돌려주고 넘어간다.
    """
    try:
        req = urllib.request.Request(
            f"https://www.youtube.com/watch?v={video_id}",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                     "Accept-Language": "ko-KR,ko;q=0.9"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            page = resp.read().decode("utf-8", "replace")
    except Exception as e:
        logger.info(f"[YOUTUBE_BASIC_META] 페이지 조회 실패 video_id={video_id} err={type(e).__name__}")
        return None

    def _meta(prop: str) -> Optional[str]:
        match = re.search(rf'<meta\s+(?:property|name)="{prop}"\s+content="([^"]*)"', page)
        return html_module.unescape(match.group(1)) if match else None

    title = _meta("og:title") or _meta("title")
    if not title:
        return None

    channel_match = re.search(r'"ownerChannelName":"((?:[^"\\]|\\.)*)"', page)
    channel = None
    if channel_match:
        try:
            channel = json.loads(f'"{channel_match.group(1)}"')
        except ValueError:
            channel = None

    return {
        "video_id": video_id,
        "title": title,
        "channel": channel,
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }


def fetch_transcript(video_id: str) -> Optional[dict]:
    """영상의 실제 자막을 통째로 받아온다. 없으면 None.

    None이 돌아오면 그 영상은 꿀팁에 붙이지 않는다 — 내용을 확인할 방법이 없는
    영상을 "이런 내용입니다"라고 소개하는 게 이 기능에서 제일 하면 안 되는 일이다.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        logger.error("[YOUTUBE_TRANSCRIPT] youtube-transcript-api 미설치 - "
                     "pip install youtube-transcript-api 필요(자막 없이는 영상 연결 불가)")
        return None

    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)

        transcript = None
        # 사람이 단 자막을 먼저, 없으면 자동 생성 자막을 쓴다.
        for finder in (transcript_list.find_manually_created_transcript,
                       transcript_list.find_generated_transcript):
            try:
                transcript = finder(TRANSCRIPT_LANGUAGES)
                break
            except Exception:
                continue
        if transcript is None:
            logger.info(f"[YOUTUBE_TRANSCRIPT] 지원 언어 자막 없음 video_id={video_id}")
            return None

        fetched = transcript.fetch()
        text = " ".join(s.text.strip() for s in fetched if s.text and s.text.strip())
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) < MIN_TRANSCRIPT_CHARS:
            logger.info(f"[YOUTUBE_TRANSCRIPT] 자막이 너무 짧음 video_id={video_id} chars={len(text)}")
            return None

        return {
            "video_id": video_id,
            "language": transcript.language_code,
            "is_generated": transcript.is_generated,
            "text": text,
            "char_count": len(text),
        }
    except Exception as e:
        # 자막 비활성화/영상 삭제/지역 차단 등 — 전부 "이 영상은 못 쓴다"로 같다.
        logger.info(f"[YOUTUBE_TRANSCRIPT] 자막 수집 실패 video_id={video_id} err={type(e).__name__}")
        return None


def is_relevant_transcript(text: str) -> bool:
    """자막에 입시 관련 이야기가 실제로 나오는지 — 제목 낚시 영상을 걸러낸다."""
    if not text:
        return False
    hits = sum(1 for kw in RELEVANCE_KEYWORDS if kw in text)
    return hits >= 3
