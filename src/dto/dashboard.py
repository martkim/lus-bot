from typing import List, Optional
from pydantic import BaseModel

from src.dto.qa import QuestionWithStudentDTO


class ActiveStudentDTO(BaseModel):
    student_id: int
    name: str
    instrument: Optional[str] = None
    session_id: int
    start_time: str


class DailyStatDTO(BaseModel):
    student_id: int
    name: str
    instrument: Optional[str] = None
    total_minutes: int
    session_count: int


class TimelineEntryDTO(BaseModel):
    name: str
    instrument: Optional[str] = None
    start_time: str
    end_time: str
    duration_minutes: int


class DashboardStatusDTO(BaseModel):
    activeStudents: List[ActiveStudentDTO]
    dailyStats: List[DailyStatDTO]
    timeline: List[TimelineEntryDTO]
    questions: List[QuestionWithStudentDTO]


class DashboardStatusResponse(BaseModel):
    success: bool
    data: DashboardStatusDTO
