import logging

from fastapi import APIRouter, HTTPException, Depends

from src.auth import verify_teacher_auth
from src.errors import NotFoundError
from src.services import insight_service
from src.dto.insights import DailyInsightResponse, InsightListResponse, InsightToggleResponse

logger = logging.getLogger("passion_mate")
router = APIRouter()


@router.get("/api/daily-insight", response_model=DailyInsightResponse)
async def get_daily_insight():
    """오늘 생성된 최신 AI 꿀팁/퀴즈/추천 카드를 학생 화면으로 반환합니다."""
    try:
        insight = insight_service.get_latest_active_insight()
        if insight:
            return DailyInsightResponse(success=True, data=insight)
        return DailyInsightResponse(success=False, message="아직 오늘의 꿀팁이 준비 중입니다.")
    except Exception as e:
        logger.exception("오늘의 인사이트 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})


@router.get("/api/daily-insight/all", response_model=InsightListResponse, dependencies=[Depends(verify_teacher_auth)])
async def get_all_insights():
    """선생님 대시보드용: 전체 AI 인사이트 목록 조회 (관리·삭제용)"""
    try:
        insights = insight_service.get_all_insights()
        return InsightListResponse(success=True, data=insights)
    except Exception as e:
        logger.exception("전체 인사이트 목록 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})


@router.patch("/api/daily-insight/{insight_id}/toggle", response_model=InsightToggleResponse, dependencies=[Depends(verify_teacher_auth)])
async def toggle_insight(insight_id: int):
    """선생님 대시보드용: 특정 인사이트 활성화/비활성화 토글"""
    try:
        new_status = insight_service.toggle_insight(insight_id)
        return InsightToggleResponse(success=True, is_active=new_status)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("인사이트 활성화 토글 실패")
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})
