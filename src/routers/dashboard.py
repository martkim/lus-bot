import logging

from fastapi import APIRouter, HTTPException, Depends

from src.auth import verify_teacher_auth
from src.services import dashboard_service
from src.dto.dashboard import DashboardStatusResponse

logger = logging.getLogger("passion_mate")
router = APIRouter()


@router.get("/api/dashboard/status", response_model=DashboardStatusResponse, dependencies=[Depends(verify_teacher_auth)])
async def get_dashboard_status():
    """선생님용 대시보드 상태 조회를 위해 실시간 및 일간 누적 통계를 반환합니다. (교사용 보안 검증 적용)"""
    try:
        status = dashboard_service.get_dashboard_status()
        return DashboardStatusResponse(success=True, data=status)
    except Exception as e:
        logger.exception("대시보드 정보 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "대시보드 정보 조회 중 오류 발생", "error": str(e)})
