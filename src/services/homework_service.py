import os
import logging
from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from fastapi import UploadFile

from src import db
from src.errors import NotFoundError
from src.dto.teachers import TeacherDTO
from src.dto.homework import HomeworkDTO, HomeworkTeacherViewDTO

logger = logging.getLogger("passion_mate")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads", "homework")

# 학원 회선 440Mbps 기준(오버헤드 감안 실효 ~33~38MB/s)으로도 1초 안팎에 끝나면서
# 악보 사진/스캔 PDF 첨부를 넉넉히 커버하는 상한선.
MAX_ATTACHMENT_SIZE_BYTES = 20 * 1024 * 1024


async def create_homework(
    student_id: int, title: str, description: str, due_date: str,
    file: Optional[UploadFile], teacher: TeacherDTO,
) -> HomeworkTeacherViewDTO:
    logger.info(f"[CREATE_HOMEWORK] 시작 student_id={student_id} teacher_id={teacher.id}")
    student = db.get_student_basic(student_id)
    if not student:
        raise NotFoundError("존재하지 않는 학생입니다.")
    if teacher.role != "director" and teacher.part != student["instrument"]:
        raise ValueError("자기 파트 학생에게만 숙제를 낼 수 있습니다.")

    title = title.strip()
    if not title:
        raise ValueError("숙제 제목을 입력해 주세요.")

    attachment_filename = None
    attachment_path = None
    if file is not None and file.filename:
        content = await file.read()
        if len(content) > MAX_ATTACHMENT_SIZE_BYTES:
            raise ValueError(f"첨부파일은 {MAX_ATTACHMENT_SIZE_BYTES // (1024*1024)}MB 이하만 가능합니다.")

        os.makedirs(UPLOAD_DIR, exist_ok=True)
        stored_name = f"{uuid4().hex}_{file.filename}"
        with open(os.path.join(UPLOAD_DIR, stored_name), "wb") as f:
            f.write(content)
        attachment_filename = file.filename
        attachment_path = f"/uploads/homework/{stored_name}"

    now_iso = datetime.now().isoformat()
    new_id = db.create_homework(
        student_id, teacher.id, title, description or None, due_date or None,
        attachment_filename, attachment_path, now_iso,
    )

    return HomeworkTeacherViewDTO(
        id=new_id, studentId=student_id, studentName=student["name"], title=title,
        description=description or None, dueDate=due_date or None,
        attachmentFilename=attachment_filename, attachmentUrl=attachment_path,
        createdAt=now_iso,
    )


def get_homework_for_student(student_id: int) -> List[HomeworkDTO]:
    logger.info(f"[GET_HOMEWORK_FOR_STUDENT] 시작 student_id={student_id}")
    rows = db.get_homework_for_student(student_id)
    return [
        HomeworkDTO(
            id=row["id"], studentId=row["student_id"], title=row["title"],
            description=row["description"], dueDate=row["due_date"],
            attachmentFilename=row["attachment_filename"], attachmentUrl=row["attachment_path"],
            createdAt=row["created_at"],
        )
        for row in rows
    ]


def get_homework_for_teacher(teacher_id: int) -> List[HomeworkTeacherViewDTO]:
    logger.info(f"[GET_HOMEWORK_FOR_TEACHER] 시작 teacher_id={teacher_id}")
    rows = db.get_homework_for_teacher(teacher_id)
    return [
        HomeworkTeacherViewDTO(
            id=row["id"], studentId=row["student_id"], studentName=row["student_name"], title=row["title"],
            description=row["description"], dueDate=row["due_date"],
            attachmentFilename=row["attachment_filename"], attachmentUrl=row["attachment_path"],
            createdAt=row["created_at"],
        )
        for row in rows
    ]
