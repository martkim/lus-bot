import urllib.parse
import logging

from fastapi import Request, HTTPException, Depends

from src import db
from src.password_utils import verify_password
from src.dto.teachers import TeacherDTO

logger = logging.getLogger("passion_mate")


def verify_teacher_auth(request: Request) -> TeacherDTO:
    """
    요청 헤더의 X-Teacher-Name(아이디)/X-Teacher-Password 값으로 teachers 테이블을 조회해
    인증합니다. 성공하면 인증된 선생님 정보(TeacherDTO, role/part 포함)를 반환 —
    원장/파트 담당 선생님 권한 분기는 이 반환값을 기준으로 한다.

    FastAPI Depends()로 라우터에 연결해서 사용합니다.
    """
    if request.method == "OPTIONS":
        return None

    auth_name_encoded = request.headers.get("X-Teacher-Name", "")
    username = urllib.parse.unquote(auth_name_encoded)  # 👔 URL 디코딩 한글 복원!
    auth_pwd_encoded = request.headers.get("X-Teacher-Password", "")
    password = urllib.parse.unquote(auth_pwd_encoded)  # 🔐 URL 디코딩 비밀번호 복원!

    teacher_row = db.get_teacher_by_username(username) if username else None
    if not teacher_row or not verify_password(password, teacher_row["password_hash"], teacher_row["password_salt"]):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다. 정확히 입력해 주세요.")

    return TeacherDTO(
        id=teacher_row["id"],
        username=teacher_row["username"],
        display_name=teacher_row["display_name"],
        role=teacher_row["role"],
        part=teacher_row["part"],
    )


def require_director(teacher: TeacherDTO = Depends(verify_teacher_auth)) -> TeacherDTO:
    """원장 전용 엔드포인트에 붙이는 의존성 — role이 director가 아니면 403."""
    if teacher.role != "director":
        raise HTTPException(status_code=403, detail="원장 선생님만 이용할 수 있는 기능입니다.")
    return teacher
