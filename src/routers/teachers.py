import logging

from fastapi import APIRouter, HTTPException, Depends, Request

from src.auth import require_director, verify_teacher_auth, TEACHER_TOKEN_HEADER
from src.errors import NotFoundError
from src.services import teacher_service
from src.dto.teachers import (
    TeacherCreateRequest, TeacherCreateResponse, TeacherListResponse, TeacherStatusToggleResponse,
    TeacherDTO, TeacherMeResponse, TeacherLoginRequest, TeacherLoginResponse, TeacherLogoutResponse,
)

logger = logging.getLogger("passion_mate")
router = APIRouter()


@router.post("/api/teachers/login", response_model=TeacherLoginResponse)
async def login_teacher(payload: TeacherLoginRequest):
    """선생님 로그인: 아이디/비밀번호를 확인하고 로그인 유지용 토큰을 발급합니다.

    인증이 아직 없는 상태에서 부르는 엔드포인트라 Depends(verify_teacher_auth)가 붙지 않는다."""
    try:
        result = await teacher_service.login_teacher(payload)
        return TeacherLoginResponse(
            success=True, message=f"{result.teacher.display_name} 선생님, 환영합니다!", data=result
        )
    except PermissionError as e:
        raise HTTPException(status_code=401, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("선생님 로그인 처리 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "선생님 로그인 처리 중 오류 발생", "error": str(e)})


@router.post("/api/teachers/logout", response_model=TeacherLogoutResponse)
async def logout_teacher(request: Request):
    """로그아웃: 보낸 토큰을 서버에서 폐기합니다.

    이미 만료됐거나 없는 토큰으로 불러도 성공으로 답한다 — 어느 쪽이든 프런트가 할 일
    (저장된 토큰 지우고 로그인 화면으로)은 같고, 여기서 401을 주면 로그아웃이 실패한
    것처럼 보여 토큰이 남는 쪽이 더 나쁘다."""
    try:
        teacher_service.logout_teacher(request.headers.get(TEACHER_TOKEN_HEADER, ""))
        return TeacherLogoutResponse(success=True, message="로그아웃되었습니다.")
    except Exception as e:
        logger.exception("선생님 로그아웃 처리 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "로그아웃 처리 중 오류 발생", "error": str(e)})


@router.get("/api/teachers/me", response_model=TeacherMeResponse)
async def get_my_teacher_info(teacher: TeacherDTO = Depends(verify_teacher_auth)):
    """로그인한 선생님 본인의 role/part 정보. 프런트가 원장/파트 선생님 UI를 분기하는 데 사용."""
    return TeacherMeResponse(success=True, data=teacher)


@router.post("/api/teachers", response_model=TeacherCreateResponse, dependencies=[Depends(require_director)])
async def create_teacher(payload: TeacherCreateRequest):
    """원장 전용: 파트 담당 선생님 계정을 새로 만듭니다."""
    try:
        teacher = await teacher_service.create_teacher(payload)
        return TeacherCreateResponse(success=True, message="선생님 계정이 생성되었습니다.", data=teacher)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("선생님 계정 생성 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "선생님 계정 생성 중 오류 발생", "error": str(e)})


@router.get("/api/teachers", response_model=TeacherListResponse, dependencies=[Depends(require_director)])
async def get_teachers():
    """원장 전용: 전체 선생님 계정 목록."""
    try:
        teachers = teacher_service.get_all_teachers()
        return TeacherListResponse(success=True, data=teachers)
    except Exception as e:
        logger.exception("선생님 목록 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "선생님 목록 조회 중 오류 발생", "error": str(e)})


@router.patch("/api/teachers/{teacher_id}/toggle-status", response_model=TeacherStatusToggleResponse, dependencies=[Depends(require_director)])
async def toggle_teacher_status(teacher_id: int):
    """원장 전용: 선생님 계정 활성/비활성 토글 (비활성화되면 로그인 불가)."""
    try:
        new_status = teacher_service.toggle_teacher_status(teacher_id)
        return TeacherStatusToggleResponse(success=True, status=new_status)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"success": False, "message": str(e)})
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("선생님 상태 토글 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "선생님 상태 변경 중 오류 발생", "error": str(e)})
