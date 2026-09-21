import logging

from fastapi import APIRouter, HTTPException

from src.errors import NotFoundError, ValidationError
from src.services import plan_service
from src.dto.plans import (
    PracticePlanListResponse, PracticePlanResponse, SimpleResponse,
    CreatePracticePlanRequest, UpdatePracticePlanRequest, DeletePracticePlanRequest,
    UpdateDailyGoalRequest,
)

logger = logging.getLogger("passion_mate")
router = APIRouter()


@router.get("/api/plans/{student_id}", response_model=PracticePlanListResponse)
async def get_practice_plans(student_id: int):
    """학생이 직접 쓴 연습 계획 슬롯 목록."""
    try:
        data = plan_service.get_plans(student_id)
        return PracticePlanListResponse(success=True, data=data)
    except Exception as e:
        logger.exception("연습 계획 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "연습 계획 조회 중 오류 발생", "error": str(e)})


@router.post("/api/plans", response_model=PracticePlanResponse)
async def create_practice_plan(payload: CreatePracticePlanRequest):
    """새 계획 슬롯을 맨 뒤에 추가."""
    try:
        plan = plan_service.create_plan(payload.studentId, payload.content)
        return PracticePlanResponse(success=True, message="계획을 추가했습니다.", data=plan)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail={"success": False, "message": str(e)})
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("연습 계획 추가 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "연습 계획 추가 중 오류 발생", "error": str(e)})


@router.patch("/api/plans/{plan_id}", response_model=PracticePlanResponse)
async def update_practice_plan(plan_id: int, payload: UpdatePracticePlanRequest):
    """계획 문구 수정 또는 체크 상태 변경."""
    try:
        plan = plan_service.update_plan(plan_id, payload.studentId, payload.content, payload.done)
        return PracticePlanResponse(success=True, message="계획을 수정했습니다.", data=plan)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail={"success": False, "message": str(e)})
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("연습 계획 수정 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "연습 계획 수정 중 오류 발생", "error": str(e)})


@router.post("/api/plans/{plan_id}/delete", response_model=SimpleResponse)
async def delete_practice_plan(plan_id: int, payload: DeletePracticePlanRequest):
    """계획 슬롯 삭제.

    DELETE가 아니라 POST인 이유: 본인 확인용 studentId를 본문으로 받아야 하는데,
    DELETE의 요청 본문은 중간 프록시에서 버려지는 경우가 있어 신뢰하기 어렵다."""
    try:
        plan_service.delete_plan(plan_id, payload.studentId)
        return SimpleResponse(success=True, message="계획을 삭제했습니다.")
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("연습 계획 삭제 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "연습 계획 삭제 중 오류 발생", "error": str(e)})


@router.post("/api/students/daily-goal", response_model=SimpleResponse)
async def update_daily_goal(payload: UpdateDailyGoalRequest):
    """학생 본인이 하루 목표 연습시간을 직접 지정."""
    try:
        minutes = plan_service.update_daily_goal(payload.studentId, payload.goalMinutes)
        return SimpleResponse(success=True, message=f"오늘의 목표를 {minutes}분으로 바꿨습니다.")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail={"success": False, "message": str(e)})
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("목표 시간 변경 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "목표 시간 변경 중 오류 발생", "error": str(e)})
