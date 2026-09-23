from typing import List, Optional
from pydantic import BaseModel


class SessionControlRequest(BaseModel):
    studentId: int
    client_end_time: Optional[str] = None
    label: Optional[str] = None     # 이번 세션에서 무엇을 연습하는지
    planId: Optional[int] = None    # 계획 슬롯에서 시작했다면 그 슬롯 id


class SessionStartedDTO(BaseModel):
    sessionId: int
    startTime: str
    label: Optional[str] = None
    planId: Optional[int] = None


class SessionStartResponse(BaseModel):
    success: bool
    message: str
    data: SessionStartedDTO


class SessionEndedDTO(BaseModel):
    sessionId: int
    startTime: str
    endTime: str
    durationMinutes: int


class SessionEndResponse(BaseModel):
    success: bool
    message: str
    data: SessionEndedDTO


class GoalProgressDTO(BaseModel):
    goalMinutes: int
    doneMinutes: int
    blocks: int          # 목표를 몇 칸으로 나눴는지
    filledBlocks: int    # 그중 꽉 찬 칸 수
    partialFill: int     # 다음 칸이 몇 % 찼는지 (0~99)


class GoalProgressResponse(BaseModel):
    success: bool
    data: GoalProgressDTO


class SessionEntryDTO(BaseModel):
    startTime: str
    endTime: str
    durationMinutes: int
    label: Optional[str] = None


class TodaySummaryDTO(BaseModel):
    """학생 화면 상단 요약 — 한 번의 호출로 타임라인과 지표를 함께 내려준다."""
    sessions: List[SessionEntryDTO]
    sessionCount: int
    totalMinutes: int
    streakDays: int      # 오늘(또는 어제)부터 거슬러 며칠 연속으로 연습했는지


class TodaySummaryResponse(BaseModel):
    success: bool
    data: TodaySummaryDTO


class ForceEndedDTO(BaseModel):
    studentName: str
    durationMinutes: int


class ForceEndSessionResponse(BaseModel):
    success: bool
    message: str
    data: ForceEndedDTO
