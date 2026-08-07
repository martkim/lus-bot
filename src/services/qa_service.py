import logging
from datetime import datetime
from typing import List

from src import db
from src.errors import NotFoundError
from src.services.ai_chat_service import get_ai_reply
from src.dto.qa import QuestionAskRequest, QuestionResolveRequest, AiDraftDTO, QuestionDTO, QuestionWithStudentDTO

logger = logging.getLogger("passion_mate")


async def ask_question(payload: QuestionAskRequest) -> AiDraftDTO:
    logger.info(f"[ASK_QUESTION] 시작 student_id={payload.studentId}")
    question_text = payload.questionText.strip()
    if not question_text:
        raise ValueError("질문 내용을 입력해 주세요.")

    student_name = db.get_student_name(payload.studentId)
    if not student_name:
        raise NotFoundError("등록되지 않은 학생입니다.")

    # 🤖 AI 추천 답변 초안 자동 생성 (is_draft=True)
    ai_draft = await get_ai_reply(question_text, is_draft=True, student_id=payload.studentId)

    now_iso = datetime.now().isoformat()
    db.create_question(payload.studentId, student_name, question_text, ai_draft, now_iso)

    return AiDraftDTO(aiDraft=ai_draft)


def resolve_question(payload: QuestionResolveRequest) -> None:
    logger.info(f"[RESOLVE_QUESTION] 시작 question_id={payload.questionId}")
    teacher_answer = payload.teacherAnswer.strip()
    if not teacher_answer:
        raise ValueError("답변 내용을 작성해 주세요.")

    question = db.get_question_by_id(payload.questionId)
    if not question:
        raise NotFoundError("존재하지 않는 질문입니다.")

    db.resolve_question(payload.questionId, teacher_answer)


def get_questions_for_student(student_id: int) -> List[QuestionDTO]:
    logger.info(f"[GET_STUDENT_QUESTIONS] 시작 student_id={student_id}")
    rows = db.get_questions_for_student(student_id)
    return [QuestionDTO(**row) for row in rows]
