import logging
import sqlite3
from datetime import datetime

from src import db
from src.password_utils import verify_password
from src.services.ai_chat_service import get_ai_reply

logger = logging.getLogger("passion_mate")


async def handle_kakao_message(kakao_user_id: str, utterance: str) -> str:
    """카카오 i 오픈빌더 스킬 웹훅으로 들어온 발화 1건을 처리해 응답 텍스트를 반환합니다.

    카카오 사용자 ID는 우리 학생 계정과 아무 관계가 없어서, 최초 대화 시 "아이디 비밀번호"
    형식으로 1회 인증받아 kakao_links에 매핑해 둔다. 이후로는 같은 kakao_user_id의 메시지를
    자동으로 그 학생의 질문으로 처리 — 웹 챗봇과 완전히 같은 ai_chat_service.get_ai_reply를
    재사용하므로 하루 사용 한도(DAILY_AI_LIMIT_PER_STUDENT)도 웹/카카오가 그대로 공유된다.
    """
    utterance = (utterance or "").strip()
    if not utterance:
        return "메시지를 입력해 주세요."

    student_id = db.get_student_id_by_kakao_user(kakao_user_id)

    if student_id is None:
        return await _try_link(kakao_user_id, utterance)

    logger.info(f"[KAKAO_MESSAGE] kakao_user_id={kakao_user_id} student_id={student_id}")
    return await get_ai_reply(utterance, is_draft=False, student_id=student_id)


async def _try_link(kakao_user_id: str, utterance: str) -> str:
    """미연결 사용자의 발화를 "아이디 비밀번호" 형식으로 해석해 학생 계정과 연결 시도."""
    parts = utterance.split(maxsplit=1)
    if len(parts) != 2:
        return (
            "안녕하세요! 아직 이 카카오톡 계정이 연결되지 않았어요. 🔗\n"
            "PASSION MATE 웹앱에서 쓰시는 아이디와 비밀번호를 순서대로 입력해 주세요.\n"
            "예) mystudent123 mypassword"
        )

    username, password = parts[0].strip(), parts[1].strip()
    student_row = db.get_student_by_username(username)
    if not student_row or not verify_password(password, student_row["password_hash"], student_row["password_salt"]):
        return "아이디 또는 비밀번호가 올바르지 않습니다. 다시 입력해 주세요."

    logger.info(f"[KAKAO_LINK] kakao_user_id={kakao_user_id} student_id={student_row['id']}")
    now_iso = datetime.now().isoformat()
    try:
        db.link_kakao_user(kakao_user_id, student_row["id"], now_iso)
    except sqlite3.IntegrityError:
        # 이미 연결된 뒤 재시도(예: 메시지 중복 전송) - 새로 연결할 필요 없이 그냥 안내
        logger.info(f"[KAKAO_LINK] kakao_user_id={kakao_user_id} 이미 연결되어 있음")
        return "이미 연결된 계정입니다. 바로 질문해 보세요!"

    return (
        f"{student_row['name']} 학생, 연결이 완료됐어요! 🎉\n"
        "이제부터 이 카카오톡 대화창에서 바로 AI 튜터에게 질문할 수 있어요. "
        "웹앱과 하루 이용 한도(2회)를 함께 씁니다."
    )
