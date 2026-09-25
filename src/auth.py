import asyncio
import urllib.parse
import logging

from fastapi import Request, HTTPException, Depends

from src import db
from src.password_utils import verify_password
from src.dto.teachers import TeacherDTO
from src.services import teacher_service

logger = logging.getLogger("passion_mate")

# 로그인 시 발급받은 토큰을 싣는 헤더. 이게 인증의 기본 경로다.
TEACHER_TOKEN_HEADER = "X-Teacher-Token"


async def verify_teacher_auth(request: Request) -> TeacherDTO:
    """
    요청을 보낸 선생님을 식별합니다. 성공하면 TeacherDTO(role/part 포함)를 반환 —
    원장/파트 담당 선생님 권한 분기는 이 반환값을 기준으로 한다.

    인증 경로는 두 가지이고, 순서가 중요하다:

    1. X-Teacher-Token — 기본 경로. 로그인 때 한 번 발급받은 토큰으로, DB 조회 1번 +
       sha256 1번이면 끝난다.
    2. X-Teacher-Name / X-Teacher-Password — 예전 방식 폴백. 토큰을 받기 전에 열어둔
       화면이 아직 떠 있을 수 있어 남겨둔다. 이 경로는 pbkdf2(260,000회)를 타므로 요청당
       실측 ~236ms가 붙는다. CPU 바운드라 그냥 호출하면 그 시간만큼 이벤트 루프 전체가
       멈추기 때문에 asyncio.to_thread로 스레드풀에 위임한다 (hashlib의 OpenSSL 구현은
       연산 중 GIL을 놓아주므로 실제 병렬 처리도 된다).

    이 의존성은 선생님 인증이 필요한 거의 모든 엔드포인트에 물려 있어 요청마다 호출되고,
    대시보드는 5초마다 폴링한다 — 1번 경로로 들어오는 게 정상이고, 2번은 과도기용이다.

    FastAPI Depends()로 라우터에 연결해서 사용합니다.
    """
    if request.method == "OPTIONS":
        return None

    token = request.headers.get(TEACHER_TOKEN_HEADER, "")
    if token:
        teacher = teacher_service.resolve_teacher_by_token(token)
        if teacher:
            return teacher
        # 토큰을 보냈는데 안 맞으면 만료됐거나 폐기된 것이다. 비밀번호 폴백으로 흘려보내지
        # 않고 여기서 끊어야, 프런트가 '다시 로그인' 상태로 정확히 돌아간다.
        raise HTTPException(status_code=401, detail="로그인이 만료되었습니다. 다시 로그인해 주세요.")

    auth_name_encoded = request.headers.get("X-Teacher-Name", "")
    username = urllib.parse.unquote(auth_name_encoded)  # URL 디코딩 한글 복원!
    auth_pwd_encoded = request.headers.get("X-Teacher-Password", "")
    password = urllib.parse.unquote(auth_pwd_encoded)  # URL 디코딩 비밀번호 복원!

    teacher_row = db.get_teacher_by_username(username) if username else None
    is_valid = teacher_row and await asyncio.to_thread(
        verify_password, password, teacher_row["password_hash"], teacher_row["password_salt"]
    )
    if not is_valid:
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
