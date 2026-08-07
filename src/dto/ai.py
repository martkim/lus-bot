from typing import Optional
from pydantic import BaseModel


class AIChatRequest(BaseModel):
    message: str
    studentId: Optional[int] = None


class AIChatResponse(BaseModel):
    success: bool
    reply: Optional[str] = None
    message: Optional[str] = None


class AnalysisReportResponse(BaseModel):
    success: bool
    report: str
    created_at: str
    source: str


class AICurriculumChatRequest(BaseModel):
    message: str


class AICurriculumChatResponse(BaseModel):
    success: bool
    reply: str


class AnalyzeFileResponse(BaseModel):
    success: bool
    message: str
    analysis: str
