import logging

from fastapi import APIRouter, HTTPException, Depends, Request

from src.auth import verify_teacher_auth
from src.errors import NotFoundError
from src.services import qa_service
from src.dto.qa import QuestionAskRequest, QuestionResolveRequest, QuestionAskResponse, QuestionListResponse
from src.dto.common import MessageResponse

logger = logging.getLogger("passion_mate")
router = APIRouter()


@router.post("/api/qa/ask", response_model=QuestionAskResponse)
async def ask_question(payload: QuestionAskRequest):
    """학생이 선생님에게 질문을 등록하는 API.
    동시에 선생님의 커리큘럼을 학습한 AI가 추천 답변(초안)을 백엔드에서 실시간 생성하여 적재합니다."""
    try:
        draft = await qa_service.ask_question(payload)
        return QuestionAskResponse(success=True, message="선생님께 질문이 성공적으로 접수되었습니다. 💌", data=draft)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"success": False, "message": str(e)})
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("Q&A 질문 제출 처리 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "Q&A 질문 제출 처리 중 오류 발생", "error": str(e)})


@router.post("/api/qa/resolve", response_model=MessageResponse, dependencies=[Depends(verify_teacher_auth)])
async def resolve_question(payload: QuestionResolveRequest):
    """선생님이 질문에 대해 최종 답변을 확정하여 완료 처리하는 API. (교사용 보안 검증 적용)"""
    try:
        qa_service.resolve_question(payload)
        return MessageResponse(success=True, message="답변 전송이 완료되었습니다! 🎓")
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"success": False, "message": str(e)})
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("질문 답변 처리 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "질문 답변 처리 중 오류 발생", "error": str(e)})


@router.get("/api/qa/student/{student_id}", response_model=QuestionListResponse)
async def get_student_questions(student_id: int):
    """특정 학생의 질문 히스토리 및 교사 피드백 조회 API."""
    try:
        questions = qa_service.get_questions_for_student(student_id)
        return QuestionListResponse(success=True, data=questions)
    except Exception as e:
        logger.exception("개인 Q&A 목록 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "개인 Q&A 목록 조회 중 오류 발생", "error": str(e)})
