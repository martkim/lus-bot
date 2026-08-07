from typing import List, Optional
from pydantic import BaseModel


class StudentCreateRequest(BaseModel):
    name: str
    instrument: str
    age: int = 19
    mbti: str = "ENFP"


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


class StudentListResponse(BaseModel):
    success: bool
    data: List[StudentDTO]


class StudentCreatedDTO(BaseModel):
    id: int
    name: str
    instrument: str
    age: int
    mbti: str


class StudentCreateResponse(BaseModel):
    success: bool
    message: str
    data: StudentCreatedDTO
