from typing import List, Optional
from pydantic import BaseModel


class TeacherDTO(BaseModel):
    """인증된 선생님 정보 — verify_teacher_auth()가 반환, 비밀번호 관련 필드는 없음."""
    id: int
    username: str
    display_name: str
    role: str  # 'director' | 'teacher'
    part: Optional[str] = None


class TeacherLoginRequest(BaseModel):
    username: str
    password: str


class TeacherLoginDTO(BaseModel):
    """로그인 성공 응답 — 발급된 토큰과 신원을 함께 준다.

    프런트가 곧바로 원장/파트 UI를 분기할 수 있도록 teacher를 같이 실어 보낸다.
    (예전엔 로그인 직후 /api/teachers/me를 한 번 더 불러야 했다.)"""
    token: str
    expires_at: str
    teacher: TeacherDTO


class TeacherLoginResponse(BaseModel):
    success: bool
    message: str
    data: TeacherLoginDTO


class TeacherLogoutResponse(BaseModel):
    success: bool
    message: str


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


class TeacherMeResponse(BaseModel):
    success: bool
    data: TeacherDTO
