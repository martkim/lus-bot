"""QA 에이전트 Controller — 요청을 받아 Service에 넘기고 응답만 만든다.

읽기는 선생님 인증, 수동 실행은 원장 전용이다. 점검은 에뮬레이터를 띄우고 Gemini
호출까지 쓰는 무거운 작업이라 아무나 돌릴 수 있으면 안 된다.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from src.auth import require_director, verify_teacher_auth
from src.dto.qa_agent import (
    QaAgentStatusResponse, QaRunDetailResponse, QaRunListResponse,
    TriggerRunRequest, TriggerRunResponse,
)
from src.errors import NotFoundError, ValidationError
from src.services import qa_agent_service

logger = logging.getLogger("passion_mate")
router = APIRouter()


@router.get("/api/qa-agent/status", response_model=QaAgentStatusResponse,
            dependencies=[Depends(verify_teacher_auth)])
async def get_qa_agent_status():
    """에이전트가 지금 무엇을 감시하고 있는지, 마지막 점검 결과는 무엇인지."""
    try:
        return QaAgentStatusResponse(success=True, data=qa_agent_service.get_status())
    except Exception as e:
        logger.exception("QA 에이전트 상태 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "상태 조회 중 오류 발생", "error": str(e)})


@router.get("/api/qa-agent/runs", response_model=QaRunListResponse,
            dependencies=[Depends(verify_teacher_auth)])
async def list_qa_agent_runs(limit: int = 20):
    """최근 점검 목록."""
    try:
        return QaRunListResponse(success=True, data=qa_agent_service.list_runs(min(max(limit, 1), 100)))
    except Exception as e:
        logger.exception("QA 점검 목록 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "점검 목록 조회 중 오류 발생", "error": str(e)})


@router.get("/api/qa-agent/runs/{run_id}", response_model=QaRunDetailResponse,
            dependencies=[Depends(verify_teacher_auth)])
async def get_qa_agent_run(run_id: int):
    """점검 1건의 전체 항목(1차/2차/실화면)."""
    try:
        return QaRunDetailResponse(success=True, data=qa_agent_service.get_run_detail(run_id))
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("QA 점검 상세 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "점검 상세 조회 중 오류 발생", "error": str(e)})


@router.get("/api/qa-agent/runs/{run_id}/screenshot", dependencies=[Depends(verify_teacher_auth)])
async def get_qa_agent_screenshot(run_id: int):
    """그 점검에서 가상 폰이 실제로 보여준 화면."""
    try:
        path = qa_agent_service.get_screenshot_path(run_id)
        return FileResponse(str(path), media_type="image/png", filename=path.name)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("QA 화면 캡처 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "화면 캡처 조회 중 오류 발생", "error": str(e)})


@router.post("/api/qa-agent/run", response_model=TriggerRunResponse,
             dependencies=[Depends(require_director)])
async def trigger_qa_agent_run(payload: TriggerRunRequest):
    """지금 바로 점검을 돌린다. 백그라운드로 실행되고 즉시 응답한다."""
    try:
        started, message = await qa_agent_service.trigger_manual_run(
            payload.features, payload.withDevice, payload.withJudge)
        return TriggerRunResponse(success=started, message=message)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("QA 점검 수동 실행 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "점검 실행 중 오류 발생", "error": str(e)})
