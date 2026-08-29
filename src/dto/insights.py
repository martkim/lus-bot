from typing import List, Optional
from pydantic import BaseModel


class InsightDTO(BaseModel):
    id: int
    insight_type: str
    title: str
    html_content: str
    is_active: int
    created_at: str
    part: Optional[str] = None


class DailyInsightResponse(BaseModel):
    success: bool
    data: Optional[InsightDTO] = None
    message: Optional[str] = None


class InsightSummaryDTO(BaseModel):
    id: int
    insight_type: str
    title: str
    is_active: int
    created_at: str
    part: Optional[str] = None


class InsightListResponse(BaseModel):
    success: bool
    data: List[InsightSummaryDTO]


class InsightToggleResponse(BaseModel):
    success: bool
    is_active: int
