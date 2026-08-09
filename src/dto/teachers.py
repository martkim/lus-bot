from typing import List, Optional
from pydantic import BaseModel


class TeacherDTO(BaseModel):
    """인증된 선생님 정보 — verify_teacher_auth()가 반환, 비밀번호 관련 필드는 없음."""
    id: int
    username: str
    display_name: str
    role: str  # 'director' | 'teacher'
    part: Optional[str] = None


class TeacherCreateRequest(BaseModel):
    username: str
    password: str
    display_name: str
    part: str  # VALID_PARTS 중 하나


class TeacherSummaryDTO(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    part: Optional[str] = None
    status: str
    created_at: str


class TeacherListResponse(BaseModel):
    success: bool
    data: List[TeacherSummaryDTO]


class TeacherCreateResponse(BaseModel):
    success: bool
    message: str
    data: TeacherSummaryDTO


class TeacherStatusToggleResponse(BaseModel):
    success: bool
    status: str
