from pydantic import BaseModel


class CurriculumUpdateRequest(BaseModel):
    curriculum_content: str


class CurriculumResponse(BaseModel):
    success: bool
    curriculum: str
