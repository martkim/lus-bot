import logging

from fastapi import APIRouter, HTTPException, Depends

from src.auth import verify_teacher_auth
from src.services import dashboard_service
from src.dto.teachers import TeacherDTO
from src.dto.dashboard import DashboardStatusResponse

logger = logging.getLogger("passion_mate")
router = APIRouter()


@router.get("/api/dashboard/status", response_model=DashboardStatusResponse)
async def get_dashboard_status(teacher: TeacherDTO = Depends(verify_teacher_auth)):
    """선생님용 대시보드 상태 조회. 원장은 전체, 파트 담당 선생님은 자기 파트 학생만 반환. (교사용 보안 검증 적용)"""
    try:
        status = dashboard_service.get_dashboard_status(teacher)
        return DashboardStatusResponse(success=True, data=status)
    except Exception as e:
        logger.exception("대시보드 정보 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "대시보드 정보 조회 중 오류 발생", "error": str(e)})
