import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form

from src.auth import verify_teacher_auth
from src.errors import NotFoundError
from src.services import homework_service
from src.dto.teachers import TeacherDTO
from src.dto.homework import HomeworkListResponse, HomeworkTeacherListResponse, HomeworkCreateResponse

logger = logging.getLogger("passion_mate")
router = APIRouter()


@router.post("/api/homework", response_model=HomeworkCreateResponse)
async def create_homework(
    studentId: int = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    dueDate: str = Form(""),
    file: Optional[UploadFile] = File(None),
    teacher: TeacherDTO = Depends(verify_teacher_auth),
):
    """선생님이 학생에게 개인 숙제를 부여합니다. 파트 담당 선생님은 자기 파트 학생에게만, 원장은 제한 없이 가능합니다."""
    try:
        homework = await homework_service.create_homework(studentId, title, description, dueDate, file, teacher)
        return HomeworkCreateResponse(success=True, message="숙제가 등록되었습니다.", data=homework)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"success": False, "message": str(e)})
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("숙제 등록 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "숙제 등록 중 오류 발생", "error": str(e)})


@router.get("/api/homework/student/{student_id}", response_model=HomeworkListResponse)
async def get_student_homework(student_id: int):
    """특정 학생 앞으로 등록된 숙제 목록 (학생용, 인증 불필요)."""
    try:
        homework = homework_service.get_homework_for_student(student_id)
        return HomeworkListResponse(success=True, data=homework)
    except Exception as e:
        logger.exception("학생 숙제 목록 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "숙제 목록 조회 중 오류 발생", "error": str(e)})


@router.get("/api/homework/teacher", response_model=HomeworkTeacherListResponse)
async def get_teacher_homework(teacher: TeacherDTO = Depends(verify_teacher_auth)):
    """로그인한 선생님 본인이 낸 숙제 목록."""
    try:
        homework = homework_service.get_homework_for_teacher(teacher.id)
        return HomeworkTeacherListResponse(success=True, data=homework)
    except Exception as e:
        logger.exception("선생님 숙제 목록 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "숙제 목록 조회 중 오류 발생", "error": str(e)})
