from typing import List, Optional

from pydantic import BaseModel


class PracticePlanDTO(BaseModel):
    id: int
    content: str
    done: bool          # done_date가 오늘이면 True (자정이 지나면 저절로 False가 된다)
    sortOrder: int


class PracticePlanListDTO(BaseModel):
    plans: List[PracticePlanDTO]
    maxSlots: int       # 화면에서 '추가' 버튼을 언제 잠글지 판단하는 데 쓴다


class PracticePlanListResponse(BaseModel):
    success: bool
    data: PracticePlanListDTO


class CreatePracticePlanRequest(BaseModel):
    studentId: int
    content: str


class UpdatePracticePlanRequest(BaseModel):
    studentId: int
    content: Optional[str] = None
    done: Optional[bool] = None


class PracticePlanResponse(BaseModel):
    success: bool
    message: str
    data: PracticePlanDTO


class DeletePracticePlanRequest(BaseModel):
    studentId: int


class SimpleResponse(BaseModel):
    success: bool
    message: str


class UpdateDailyGoalRequest(BaseModel):
    studentId: int
    goalMinutes: int
