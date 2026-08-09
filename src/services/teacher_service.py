import logging
from datetime import datetime
from sqlite3 import IntegrityError
from typing import List

from src import db
from src.errors import NotFoundError
from src.password_utils import hash_password
from src.dto.teachers import TeacherCreateRequest, TeacherSummaryDTO

logger = logging.getLogger("passion_mate")

VALID_PARTS = ["일렉기타", "베이스", "작곡", "보컬", "미디", "드럼"]


def create_teacher(payload: TeacherCreateRequest) -> TeacherSummaryDTO:
    logger.info(f"[CREATE_TEACHER] 시작 username={payload.username}")
    username = payload.username.strip()
    display_name = payload.display_name.strip()
    part = payload.part.strip()

    if not username or not payload.password or not display_name:
        raise ValueError("아이디, 비밀번호, 이름을 모두 입력해 주세요.")
    if part not in VALID_PARTS:
        raise ValueError(f"파트는 다음 중 하나여야 합니다: {', '.join(VALID_PARTS)}")

    pwd_hash, salt = hash_password(payload.password)
    now_iso = datetime.now().isoformat()
    try:
        new_id = db.create_teacher(username, pwd_hash, salt, display_name, "teacher", part, now_iso)
    except IntegrityError:
        raise ValueError(f"이미 사용 중인 아이디입니다: {username}")

    return TeacherSummaryDTO(
        id=new_id, username=username, display_name=display_name,
        role="teacher", part=part, status="ACTIVE", created_at=now_iso,
    )


def get_all_teachers() -> List[TeacherSummaryDTO]:
    logger.info("[GET_ALL_TEACHERS] 시작")
    rows = db.get_all_teachers()
    return [TeacherSummaryDTO(**row) for row in rows]


def toggle_teacher_status(teacher_id: int) -> str:
    """ACTIVE <-> INACTIVE 토글 (기존 인사이트 토글과 동일한 패턴). 새 상태 문자열을 반환."""
    logger.info(f"[TOGGLE_TEACHER_STATUS] 시작 teacher_id={teacher_id}")
    teacher = db.get_teacher_by_id(teacher_id)
    if not teacher:
        raise NotFoundError("존재하지 않는 선생님 계정입니다.")
    if teacher["role"] == "director":
        raise ValueError("원장 계정은 비활성화할 수 없습니다.")

    new_status = "INACTIVE" if teacher["status"] == "ACTIVE" else "ACTIVE"
    db.set_teacher_status(teacher_id, new_status)
    return new_status
