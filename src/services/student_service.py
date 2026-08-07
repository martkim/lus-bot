import logging
from datetime import datetime, timezone
from typing import List

from src import db
from src.errors import NotFoundError
from src.dto.students import StudentCreateRequest, StudentDTO, StudentCreatedDTO

logger = logging.getLogger("passion_mate")


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

    mbti = payload.mbti.strip().upper()
    new_id = db.create_student(name, instrument, payload.age, mbti)
    return StudentCreatedDTO(id=new_id, name=name, instrument=instrument, age=payload.age, mbti=mbti)


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
