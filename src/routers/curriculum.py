import logging

from fastapi import APIRouter, HTTPException, Depends

from src.auth import verify_teacher_auth
from src.services import curriculum_service
from src.dto.curriculum import CurriculumUpdateRequest, CurriculumResponse
from src.dto.common import MessageResponse

logger = logging.getLogger("passion_mate")
router = APIRouter()


@router.get("/api/curriculum", response_model=CurriculumResponse, dependencies=[Depends(verify_teacher_auth)])
async def get_curriculum():
    """현재 커리큘럼(curriculum.txt)을 반환합니다."""
    try:
        content = curriculum_service.get_curriculum()
        return CurriculumResponse(success=True, curriculum=content)
    except Exception as e:
        logger.exception("커리큘럼 파일 읽기 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "커리큘럼 파일 읽기 오류", "error": str(e)})


@router.post("/api/curriculum", response_model=MessageResponse, dependencies=[Depends(verify_teacher_auth)])
async def update_curriculum(payload: CurriculumUpdateRequest):
    """수정된 커리큘럼(curriculum.txt)을 저장합니다."""
    try:
        curriculum_service.save_curriculum(payload.curriculum_content)
        return MessageResponse(success=True, message="커리큘럼이 성공적으로 업데이트되었습니다.")
    except Exception as e:
        logger.exception("커리큘럼 파일 저장 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "커리큘럼 파일 저장 오류", "error": str(e)})
