import logging

from fastapi import APIRouter, HTTPException, Depends

from src.auth import verify_teacher_auth
from src.errors import NotFoundError, ConflictError
from src.services import session_service
from src.dto.sessions import (
    SessionControlRequest, SessionStartResponse, SessionEndResponse, ForceEndSessionResponse
)

logger = logging.getLogger("passion_mate")
router = APIRouter()


@router.post("/api/sessions/start", response_model=SessionStartResponse)
async def start_session(payload: SessionControlRequest):
    """연습 타이머를 시작하고 현재 시간 기록을 생성합니다."""
    try:
        started = session_service.start_session(payload)
        return SessionStartResponse(success=True, message="연습을 시작합니다!", data=started)
    except ConflictError as e:
        raise HTTPException(status_code=400, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("연습 시작 처리 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "연습 시작 처리 중 오류 발생", "error": str(e)})


@router.post("/api/sessions/end", response_model=SessionEndResponse)
async def end_session(payload: SessionControlRequest):
    """진행 중인 연습 세션을 종료하고 소요 시간을 환산하여 데이터베이스에 기록합니다."""
    try:
        ended = session_service.end_session(payload)
        return SessionEndResponse(success=True, message="연습을 정상 종료했습니다. 수고하셨습니다!", data=ended)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("연습 종료 처리 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "연습 종료 처리 중 오류 발생", "error": str(e)})


@router.post("/api/admin/sessions/end", response_model=ForceEndSessionResponse, dependencies=[Depends(verify_teacher_auth)])
async def force_end_session(payload: SessionControlRequest):
    """행정 관리용: 교사의 판단 하에 특정 학생의 진행 중인 연습 세션을 강제 완료(퇴장) 처리합니다."""
    try:
        result = session_service.force_end_session(payload)
        message = f"{result.studentName} 학생의 연습 세션을 강제로 정상 종료 처리했습니다! (소요 시간: {result.durationMinutes}분)"
        return ForceEndSessionResponse(success=True, message=message, data=result)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"success": False, "message": str(e)})
    except ConflictError as e:
        raise HTTPException(status_code=400, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("강제 퇴장 처리 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "강제 퇴장 처리 중 오류 발생", "error": str(e)})
