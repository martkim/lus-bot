import os
import urllib.parse
import logging

from fastapi import Request, HTTPException

logger = logging.getLogger("passion_mate")

TEACHER_NAME = "선생님"
TEACHER_PASSWORD = os.environ.get("TEACHER_PASSWORD")


def verify_teacher_auth(request: Request):
    """
    요청 헤더의 X-Teacher-Name 및 X-Teacher-Password 값을 검증하여
    교사 대시보드 권한 여부를 체크합니다. (CORS Preflight OPTIONS 요청은 통과)

    FastAPI Depends()로 라우터에 연결해서 사용합니다.
    """
    if request.method == "OPTIONS":
        return

    auth_name_encoded = request.headers.get("X-Teacher-Name", "")
    auth_name = urllib.parse.unquote(auth_name_encoded)  # 👔 URL 디코딩 한글 복원!
    auth_pwd_encoded = request.headers.get("X-Teacher-Password", "")
    auth_pwd = urllib.parse.unquote(auth_pwd_encoded)  # 🔐 URL 디코딩 비밀번호 복원!
    if auth_name != TEACHER_NAME or auth_pwd != TEACHER_PASSWORD:
        raise HTTPException(status_code=401, detail="교사 대시보드 인증 권한이 없습니다. 이름과 비밀번호를 정확히 입력해 주세요.")
