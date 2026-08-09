import logging

from fastapi import APIRouter, HTTPException, Depends

from src.auth import require_director
from src.errors import NotFoundError
from src.services import teacher_service
from src.dto.teachers import (
    TeacherCreateRequest, TeacherCreateResponse, TeacherListResponse, TeacherStatusToggleResponse,
)

logger = logging.getLogger("passion_mate")
router = APIRouter()


@router.post("/api/teachers", response_model=TeacherCreateResponse, dependencies=[Depends(require_director)])
async def create_teacher(payload: TeacherCreateRequest):
    """원장 전용: 파트 담당 선생님 계정을 새로 만듭니다."""
    try:
        teacher = teacher_service.create_teacher(payload)
        return TeacherCreateResponse(success=True, message="선생님 계정이 생성되었습니다.", data=teacher)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("선생님 계정 생성 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "선생님 계정 생성 중 오류 발생", "error": str(e)})


@router.get("/api/teachers", response_model=TeacherListResponse, dependencies=[Depends(require_director)])
async def get_teachers():
    """원장 전용: 전체 선생님 계정 목록."""
    try:
        teachers = teacher_service.get_all_teachers()
        return TeacherListResponse(success=True, data=teachers)
    except Exception as e:
        logger.exception("선생님 목록 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "선생님 목록 조회 중 오류 발생", "error": str(e)})


@router.patch("/api/teachers/{teacher_id}/toggle-status", response_model=TeacherStatusToggleResponse, dependencies=[Depends(require_director)])
async def toggle_teacher_status(teacher_id: int):
    """원장 전용: 선생님 계정 활성/비활성 토글 (비활성화되면 로그인 불가)."""
    try:
        new_status = teacher_service.toggle_teacher_status(teacher_id)
        return TeacherStatusToggleResponse(success=True, status=new_status)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"success": False, "message": str(e)})
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("선생님 상태 토글 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "선생님 상태 변경 중 오류 발생", "error": str(e)})
