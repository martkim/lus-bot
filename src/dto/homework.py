from typing import List, Optional
from pydantic import BaseModel


class HomeworkDTO(BaseModel):
    """학생이 자기 앞으로 온 숙제 목록을 조회할 때 쓰는 뷰."""
    id: int
    studentId: int
    title: str
    description: Optional[str] = None
    dueDate: Optional[str] = None
    attachmentFilename: Optional[str] = None
    attachmentUrl: Optional[str] = None
    createdAt: str


class HomeworkTeacherViewDTO(BaseModel):
    """선생님이 자기가 낸 숙제 목록을 조회할 때 쓰는 뷰 (학생 이름 포함)."""
    id: int
    studentId: int
    studentName: str
    title: str
    description: Optional[str] = None
    dueDate: Optional[str] = None
    attachmentFilename: Optional[str] = None
    attachmentUrl: Optional[str] = None
    createdAt: str


class HomeworkListResponse(BaseModel):
    success: bool
    data: List[HomeworkDTO]


class HomeworkTeacherListResponse(BaseModel):
    success: bool
    data: List[HomeworkTeacherViewDTO]


class HomeworkCreateResponse(BaseModel):
    success: bool
    message: str
    data: HomeworkTeacherViewDTO
