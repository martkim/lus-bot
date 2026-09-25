# -*- coding: utf-8 -*-
"""오늘의 꿀팁 근거 계층(논문 / 영상 / 입시정보)의 요청·응답 형태.

세 가지가 한 파일에 있는 이유: 전부 "꿀팁을 떠받치는 근거"라는 한 기능의 부품이고,
선생님 대시보드에서도 한 화면에서 같이 다뤄진다.
"""
from typing import List, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------- 논문
class PaperDTO(BaseModel):
    id: int
    doi: str
    title: str
    authors: List[str] = []
    year: Optional[int] = None
    journal: Optional[str] = None
    url: Optional[str] = None
    open_access_url: Optional[str] = None
    topic: Optional[str] = None
    angle: Optional[str] = None
    cited_by: int = 0
    # 초록(근거 원문)을 확보했는가. 0이면 꿀팁 생성에 쓰이지 않는다.
    has_evidence: int = 0
    use_count: int = 0
    last_used_at: Optional[str] = None
    is_active: int = 1


class PaperListResponse(BaseModel):
    success: bool
    data: List[PaperDTO] = []
    usable_count: int = 0


class AddPaperRequest(BaseModel):
    doi: str
    topic: str
    angle: str


class AddPaperResponse(BaseModel):
    success: bool
    doi: Optional[str] = None
    title: Optional[str] = None
    has_evidence: bool = False
    message: Optional[str] = None


# ---------------------------------------------------------------- 영상
class VideoDTO(BaseModel):
    id: int
    video_id: str
    title: str
    channel: Optional[str] = None
    url: str
    published_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    view_count: Optional[int] = None
    parts: List[str] = []
    transcript_language: Optional[str] = None
    transcript_chars: Optional[int] = None
    # 자막 원문에서 그대로 옮겨온 한 토막. 비어 있으면 꿀팁에 붙지 않는다.
    transcript_excerpt: Optional[str] = None
    analysis_summary: Optional[str] = None
    key_points: List[str] = []
    relevance_score: int = 0
    source: Optional[str] = None
    use_count: int = 0
    is_active: int = 1


class VideoListResponse(BaseModel):
    success: bool
    data: List[VideoDTO] = []
    search_enabled: bool = False


class AddVideoRequest(BaseModel):
    url: str


class AddVideoResponse(BaseModel):
    success: bool
    video_id: Optional[str] = None
    title: Optional[str] = None
    message: Optional[str] = None


class VideoToggleResponse(BaseModel):
    success: bool
    is_active: int


# ---------------------------------------------------------------- 입시 정보
class AdmissionInfoDTO(BaseModel):
    id: int
    title: str
    summary: Optional[str] = None
    category: Optional[str] = None
    school: Optional[str] = None
    board_name: Optional[str] = None
    parts: List[str] = []
    posted_at: Optional[str] = None
    deadline: Optional[str] = None
    source_url: Optional[str] = None
    source_type: Optional[str] = None
    status: str = "pending"
    approved_by: Optional[str] = None
    collected_at: Optional[str] = None


class AdmissionInfoListResponse(BaseModel):
    success: bool
    data: List[AdmissionInfoDTO] = []
    counts: dict = {}


class AddAdmissionInfoRequest(BaseModel):
    title: str
    summary: Optional[str] = None
    school: Optional[str] = None
    category: Optional[str] = None
    parts: List[str] = []
    deadline: Optional[str] = None
    source_url: Optional[str] = None


class AdmissionInfoStatusRequest(BaseModel):
    status: str


class AdmissionInfoResponse(BaseModel):
    success: bool
    data: Optional[AdmissionInfoDTO] = None
    message: Optional[str] = None


class CollectResultResponse(BaseModel):
    success: bool
    collected: int = 0
    new: int = 0
    classified: int = 0
    message: Optional[str] = None
