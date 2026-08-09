import logging

from fastapi import APIRouter, HTTPException, Depends

from src.auth import require_director
from src.errors import NotFoundError
from src.services import student_service
from src.dto.students import StudentCreateRequest, StudentListResponse, StudentCreateResponse
from src.dto.common import MessageResponse

logger = logging.getLogger("passion_mate")
router = APIRouter()


@router.get("/api/students", response_model=StudentListResponse)
async def get_students():
    """모든 활성화된 학생 목록과 현재 연습 중인 세션 정보를 함께 조회하여 반환합니다."""
    try:
        students = student_service.get_active_students()
        return StudentListResponse(success=True, data=students)
    except Exception as e:
        logger.exception("학생 목록 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "학생 목록 조회 중 오류 발생", "error": str(e)})


@router.post("/api/students", response_model=StudentCreateResponse, dependencies=[Depends(require_director)])
async def create_student(student: StudentCreateRequest):
    """새로운 입시생을 등록합니다. (원장 전용)"""
    try:
        created = student_service.create_student(student)
        return StudentCreateResponse(success=True, message="학생이 성공적으로 등록되었습니다.", data=created)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("학생 등록 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "학생 등록 중 오류 발생", "error": str(e)})


@router.delete("/api/admin/students/{student_id}", response_model=MessageResponse, dependencies=[Depends(require_director)])
async def delete_student(student_id: int):
    """행정 관리용(원장 전용): 특정 원생 정보를 소프트 삭제(Soft Delete)합니다.
    관련 연습 기록(sessions) 및 실시간 Q&A 피드(questions) 데이터는 교사 분석용으로 영구 보존됩니다."""
    try:
        student_name = student_service.delete_student(student_id)
        return MessageResponse(
            success=True,
            message=f"입시생 {student_name}님의 프로필이 안전하게 삭제(소프트 삭제) 처리되었습니다! 기존 연습 이력 및 질문 내역 데이터는 AI 통계 분석용으로 고스란히 보존됩니다.",
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("원생 삭제 처리 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "원생 삭제 처리 중 오류 발생", "error": str(e)})
