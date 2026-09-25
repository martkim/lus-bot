# -*- coding: utf-8 -*-
"""꿀팁 카드 HTML 렌더러 — 구조화된 내용을 정해진 틀에 부어 안전한 HTML을 만든다.

**왜 AI에게 HTML을 맡기지 않는가**

예전에는 Gemini에게 `<style>`까지 포함한 카드 HTML을 통째로 만들게 했다. 그래서
프롬프트에 색을 일일이 적어줘야 했고("흰 배경이니 어두운 글자를 써라"), 학생 화면
테마가 다크로 바뀐 뒤에도 그 문구가 그대로 남아 글자가 안 보이는 사고가 반복됐다.
색을 아는 쪽은 CSS지 AI가 아니다.

그래서 여기서는 **색을 단 하나도 쓰지 않는다.** 클래스만 붙이고, 실제 색은
public/student-theme.css의 테마 변수가 정한다. 테마가 바뀌면 카드도 같이 바뀐다.

또 하나: 여기 들어오는 글자는 전부 바깥에서 온 것이다(AI 생성물, 유튜브 제목,
대학 공고 제목). 전부 이스케이프한다. 링크도 http/https만 통과시킨다.
"""
import html
import logging
import urllib.parse
from typing import List, Optional

logger = logging.getLogger("passion_mate")

ALLOWED_LINK_SCHEMES = ("http", "https")


def _esc(value: Optional[str]) -> str:
    """어떤 값이 와도 HTML 안에 넣어도 안전한 문자열로."""
    return html.escape(str(value), quote=True) if value is not None else ""


def _safe_url(url: Optional[str]) -> Optional[str]:
    """http/https 링크만 통과. javascript: 같은 건 통째로 버린다."""
    if not url:
        return None
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except Exception:
        return None
    if parsed.scheme.lower() not in ALLOWED_LINK_SCHEMES or not parsed.netloc:
        logger.warning(f"[RENDERER] 허용되지 않는 링크 제외 url={url[:80]!r}")
        return None
    return url.strip()


def _paragraphs(text: Optional[str]) -> str:
    """줄바꿈으로 나뉜 글을 <p>들로. 빈 줄은 버린다."""
    if not text:
        return ""
    lines = [line.strip() for line in str(text).split("\n") if line.strip()]
    return "".join(f"<p>{_esc(line)}</p>" for line in lines)


def _format_authors(authors: Optional[List[str]], limit: int = 2) -> str:
    """'Ericsson 외 2인' 형태로 줄인다. 저자가 없으면 빈 문자열."""
    if not authors:
        return ""
    names = [a for a in authors if a]
    if not names:
        return ""
    if len(names) <= limit:
        return ", ".join(names)
    return f"{', '.join(names[:limit])} 외 {len(names) - limit}인"


def render_paper_section(paper: Optional[dict]) -> str:
    """근거 논문 출처 블록. 논문이 없으면 아무것도 안 그린다.

    꿀팁에 근거 논문이 없는 경우는 원래 생기면 안 된다(서비스가 논문 없이는
    카드를 만들지 않는다). 그래도 방어적으로 빈 문자열을 돌려준다.
    """
    if not paper:
        return ""

    title = _esc(paper.get("title"))
    link = _safe_url(paper.get("url") or (f"https://doi.org/{paper['doi']}" if paper.get("doi") else None))
    meta_bits = [b for b in (
        _format_authors(paper.get("authors")),
        str(paper["year"]) if paper.get("year") else "",
        paper.get("journal") or "",
    ) if b]
    meta = _esc(" · ".join(meta_bits))

    title_html = (f'<a class="tip-source-link" href="{_esc(link)}" target="_blank" rel="noopener noreferrer">{title}</a>'
                  if link else f'<span class="tip-source-link">{title}</span>')

    return (
        '<aside class="tip-source">'
        '<span class="tip-source-label">근거 논문</span>'
        f'{title_html}'
        f'<span class="tip-source-meta">{meta}</span>'
        '</aside>'
    )


def render_video_section(video: Optional[dict]) -> str:
    """관련 영상 블록 — 자막을 실제로 받아 분석한 영상만 들어온다."""
    if not video:
        return ""

    link = _safe_url(video.get("url"))
    if not link:
        return ""

    title = _esc(video.get("title"))
    channel = _esc(video.get("channel"))
    summary = _esc(video.get("analysis_summary"))
    quote = (video.get("transcript_excerpt") or "").strip()

    points_html = ""
    points = video.get("key_points") or []
    if points:
        items = "".join(f"<li>{_esc(p)}</li>" for p in points[:3])
        points_html = f'<ul class="tip-video-points">{items}</ul>'

    quote_html = f'<blockquote class="tip-video-quote">{_esc(quote)}</blockquote>' if quote else ""
    summary_html = f'<p class="tip-video-summary">{summary}</p>' if summary else ""

    return (
        '<aside class="tip-video">'
        '<span class="tip-source-label">영상으로 보기</span>'
        f'<a class="tip-video-link" href="{_esc(link)}" target="_blank" rel="noopener noreferrer">{title}</a>'
        f'<span class="tip-video-channel">{channel}</span>'
        f'{summary_html}{quote_html}{points_html}'
        '<span class="tip-video-note">영상 자막을 실제로 받아 분석한 내용입니다</span>'
        '</aside>'
    )


def render_card(content: dict, paper: Optional[dict] = None, video: Optional[dict] = None) -> str:
    """꿀팁 카드 한 장을 완성한다.

    content는 AI가 채워 보낸 구조화 필드다:
      headline       : 한 줄 제목
      paper_plain    : 논문이 말하는 것을 쉬운 말로
      how_to_apply   : 오늘 해볼 것 (리스트)
      caution        : 주의할 점 (선택)
    """
    headline = _esc(content.get("headline"))
    paper_plain = _paragraphs(content.get("paper_plain"))

    steps = content.get("how_to_apply") or []
    steps_html = ""
    if steps:
        items = "".join(f"<li>{_esc(step)}</li>" for step in steps[:5])
        steps_html = (
            '<section class="tip-block">'
            '<h3 class="tip-h">오늘 이렇게 해보기</h3>'
            f'<ol class="tip-steps">{items}</ol>'
            '</section>'
        )

    caution = content.get("caution")
    caution_html = ""
    if caution:
        caution_html = (
            '<section class="tip-block tip-caution">'
            '<h3 class="tip-h">이건 조심하세요</h3>'
            f'{_paragraphs(caution)}'
            '</section>'
        )

    plain_html = ""
    if paper_plain:
        plain_html = (
            '<section class="tip-block">'
            '<h3 class="tip-h">연구가 말하는 것</h3>'
            f'{paper_plain}'
            '</section>'
        )

    lede_html = f'<p class="tip-lede">{headline}</p>' if headline else ""

    return (
        '<article class="tip-card">'
        f'{lede_html}{plain_html}{steps_html}{caution_html}'
        f'{render_paper_section(paper)}'
        f'{render_video_section(video)}'
        '</article>'
    )
