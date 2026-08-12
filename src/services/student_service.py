import logging
import sqlite3
from datetime import datetime, timezone
from typing import List

from src import db
from src.errors import NotFoundError
from src.password_utils import hash_password, verify_password
from src.dto.students import (
    StudentCreateRequest, StudentDTO, StudentCreatedDTO,
    UnclaimedStudentDTO, StudentClaimRequest, StudentLoginRequest, StudentAuthDTO,
)

logger = logging.getLogger("passion_mate")

VALID_MBTI_TYPES = [
    "ISTJ", "ISFJ", "INFJ", "INTJ",
    "ISTP", "ISFP", "INFP", "INTP",
    "ESTP", "ESFP", "ENFP", "ENTP",
    "ESTJ", "ESFJ", "ENFJ", "ENTJ",
]


def get_active_students() -> List[StudentDTO]:
    logger.info("[GET_ACTIVE_STUDENTS] 시작")
    rows = db.get_active_students_with_session()
    return [StudentDTO(**row) for row in rows]


def create_student(payload: StudentCreateRequest) -> StudentCreatedDTO:
    logger.info("[CREATE_STUDENT] 시작")
    name = payload.name.strip()
    instrument = payload.instrument.strip()
    if not name or not instrument:
        raise ValueError("이름과 전공 악기를 모두 입력해 주세요.")

    new_id = db.create_student(name, instrument, payload.age)
    return StudentCreatedDTO(id=new_id, name=name, instrument=instrument, age=payload.age, mbti=None)


def delete_student(student_id: int) -> str:
    """소프트 삭제 + 진행 중인 세션 강제 종료. 삭제된 학생 이름을 반환."""
    logger.info(f"[DELETE_STUDENT] 시작 student_id={student_id}")
    student_name = db.get_active_student_name(student_id)
    if not student_name:
        raise NotFoundError("존재하지 않거나 이미 삭제된 원생입니다.")

    now_iso = datetime.now(timezone.utc).isoformat()
    db.force_end_active_sessions_for_student(student_id, now_iso, duration_minutes=1)
    db.soft_delete_student(student_id)
    return student_name


def get_unclaimed_students() -> List[UnclaimedStudentDTO]:
    logger.info("[GET_UNCLAIMED_STUDENTS] 시작")
    rows = db.get_unclaimed_students()
    return [UnclaimedStudentDTO(**row) for row in rows]


def claim_student(payload: StudentClaimRequest) -> StudentAuthDTO:
    logger.info(f"[CLAIM_STUDENT] 시작 student_id={payload.studentId}")
    username = payload.username.strip()
    password = payload.password.strip()
    mbti = payload.mbti.strip().upper()
    if not username or not password:
        raise ValueError("아이디와 비밀번호를 모두 입력해 주세요.")
    if len(password) < 4:
        raise ValueError("비밀번호는 4자 이상이어야 합니다.")
    if mbti not in VALID_MBTI_TYPES:
        raise ValueError("올바른 MBTI 유형을 선택해 주세요.")

    pwd_hash, salt = hash_password(password)
    try:
        affected = db.claim_student_account(payload.studentId, username, pwd_hash, salt, mbti)
    except sqlite3.IntegrityError:
        raise ValueError(f"이미 사용 중인 아이디입니다: {username}")

    if affected == 0:
        raise NotFoundError("존재하지 않거나 이미 가입 완료된 학생입니다.")

    student_row = db.get_student_by_username(username)
    return StudentAuthDTO(**student_row)


def login_student(payload: StudentLoginRequest) -> StudentAuthDTO:
    logger.info(f"[LOGIN_STUDENT] 시작 username={payload.username}")
    student_row = db.get_student_by_username(payload.username.strip())
    if not student_row or not verify_password(payload.password, student_row["password_hash"], student_row["password_salt"]):
        raise PermissionError("아이디 또는 비밀번호가 올바르지 않습니다.")

    return StudentAuthDTO(**student_row)
