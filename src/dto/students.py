from typing import List, Optional
from pydantic import BaseModel


class StudentCreateRequest(BaseModel):
    name: str
    instrument: str
    age: int = 19


class StudentDTO(BaseModel):
    """Active student row + current session info, exactly as the student/teacher
    frontends read it (field names are load-bearing — see public/app.js,
    public/dashboard.js)."""
    id: int
    name: str
    instrument: str
    age: Optional[int] = None
    mbti: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[str] = None
    active_session_id: Optional[int] = None
    active_session_start: Optional[str] = None
    # 새로고침해도 '무엇을 연습 중이었는지'를 화면에 되살리기 위해 함께 내려준다
    active_session_label: Optional[str] = None
    active_session_plan_id: Optional[int] = None


class StudentListResponse(BaseModel):
    success: bool
    data: List[StudentDTO]


class StudentCreatedDTO(BaseModel):
    id: int
    name: str
    instrument: str
    age: int
    mbti: Optional[str] = None


class StudentCreateResponse(BaseModel):
    success: bool
    message: str
    data: StudentCreatedDTO


class UnclaimedStudentDTO(BaseModel):
    id: int
    name: str
    instrument: str


class UnclaimedStudentListResponse(BaseModel):
    success: bool
    data: List[UnclaimedStudentDTO]


class StudentClaimRequest(BaseModel):
    studentId: int
    username: str
    password: str
    mbti: str


class StudentLoginRequest(BaseModel):
    username: str
    password: str


class StudentAuthDTO(BaseModel):
    id: int
    name: str
    instrument: str
    age: Optional[int] = None
    mbti: Optional[str] = None


class StudentAuthResponse(BaseModel):
    success: bool
    message: str
    data: StudentAuthDTO
