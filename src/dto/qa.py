from typing import List, Optional
from pydantic import BaseModel


class QuestionAskRequest(BaseModel):
    studentId: int
    questionText: str


class QuestionResolveRequest(BaseModel):
    questionId: int
    teacherAnswer: str


class AiDraftDTO(BaseModel):
    aiDraft: str


class QuestionAskResponse(BaseModel):
    success: bool
    message: str
    data: AiDraftDTO


class QuestionDTO(BaseModel):
    """A student's own question history entry."""
    id: int
    question_text: str
    ai_answer: Optional[str] = None
    teacher_answer: Optional[str] = None
    created_at: str
    status: str


class QuestionListResponse(BaseModel):
    success: bool
    data: List[QuestionDTO]


class QuestionWithStudentDTO(BaseModel):
    """Question + student info, used on the teacher dashboard feed."""
    id: int
    student_id: Optional[int] = None
    student_name: str
    instrument: Optional[str] = None
    question_text: str
    ai_answer: Optional[str] = None
    teacher_answer: Optional[str] = None
    created_at: str
    status: str
