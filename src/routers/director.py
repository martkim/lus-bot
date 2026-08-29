import logging

from fastapi import APIRouter, HTTPException, Response, Depends

from src.auth import require_director
from src.services import director_stats_service

logger = logging.getLogger("passion_mate")
router = APIRouter()


@router.get("/api/director/stats/export", dependencies=[Depends(require_director)])
async def export_stats_excel():
    """원장 전용: 선생님별 담당 원생 수 + 전체 재적생 상세를 엑셀 파일로 다운로드."""
    try:
        content = director_stats_service.generate_stats_excel()
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=passion_mate_stats.xlsx"},
        )
    except Exception as e:
        logger.exception("원장 통계 엑셀 생성 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "통계 엑셀 생성 중 오류 발생", "error": str(e)})
