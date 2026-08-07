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


class ForceEndedDTO(BaseModel):
    studentName: str
    durationMinutes: int


class ForceEndSessionResponse(BaseModel):
    success: bool
    message: str
    data: ForceEndedDTO
