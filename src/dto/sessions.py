from typing import Optional
from pydantic import BaseModel


class SessionControlRequest(BaseModel):
    studentId: int
    client_end_time: Optional[str] = None


class SessionStartedDTO(BaseModel):
    sessionId: int
    startTime: str


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


class ForceEndedDTO(BaseModel):
    studentName: str
    durationMinutes: int


class ForceEndSessionResponse(BaseModel):
    success: bool
    message: str
    data: ForceEndedDTO
