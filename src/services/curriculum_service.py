import os
import json
import asyncio
import logging
import tempfile
from datetime import datetime, timezone

from src import db
from src.gemini_client import GEMINI_API_KEY, get_client
from src.curriculum_store import CURRICULUM_PATH, get_curriculum_text, set_curriculum_text

logger = logging.getLogger("passion_mate")


def get_curriculum() -> str:
    logger.info("[GET_CURRICULUM] 시작")
    if os.path.exists(CURRICULUM_PATH):
        with open(CURRICULUM_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def save_curriculum(new_text: str) -> None:
    logger.info("[SAVE_CURRICULUM] 시작")
    with open(CURRICULUM_PATH, "w", encoding="utf-8") as f:
        f.write(new_text)
    set_curriculum_text(new_text)


async def auto_update_curriculum_logic():
    if not GEMINI_API_KEY:
        print("[AI Auto Update] Skipped. No GEMINI_API_KEY.")
        return

    try:
        # 오늘 치 데이터 및 최근 50개의 질문 수집
        today_local_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_iso = today_local_start.astimezone(timezone.utc).isoformat()

        recent_sessions = db.get_sessions_since(today_start_iso)
        recent_questions = db.get_recent_questions_simple(limit=50)

        data_summary = {
            "recent_sessions_count": len(recent_sessions),
            "recent_questions": [q["question_text"] for q in recent_questions]
        }

        curriculum_text = get_curriculum_text()
        prompt = (
            "당신은 입시 학원의 'AI 교육 마스터'입니다.\n"
            "아래는 학생들의 최근 활동(완료된 세션 수 및 질문 목록)입니다.\n"
            f"{json.dumps(data_summary, ensure_ascii=False)}\n\n"
            f"=== [현재 적용 중인 커리큘럼] ===\n{curriculum_text}\n\n"
            "위 학생 데이터를 기반으로, 현재 커리큘럼을 더욱 유용하게 자동 업데이트해 주세요.\n"
            "기존 커리큘럼의 포맷과 원칙은 최대한 파괴하지 않고 유지하되, 최근 발생한 빈출 질문이나 취약점을 해결할 수 있는 '새로운 팁과 맞춤형 지침'을 적절한 항목에 자연스럽게 덧붙여 주세요.\n"
            "코드 블록 백틱(```)은 절대 쓰지 말고, 즉시 파일에 덮어쓸 수 있도록 완성된 전체 텍스트만 반환해 주세요."
        )

        response = await asyncio.to_thread(
            get_client().models.generate_content,
            model='gemini-2.5-flash',
            contents=prompt
        )
        updated_curriculum = response.text.strip()

        # 불필요한 마크다운 백틱 제거
        if updated_curriculum.startswith("```"):
            updated_curriculum = "\n".join(updated_curriculum.split("\n")[1:])
        if updated_curriculum.endswith("```"):
            updated_curriculum = "\n".join(updated_curriculum.split("\n")[:-1])
        updated_curriculum = updated_curriculum.strip()

        if updated_curriculum:
            save_curriculum(updated_curriculum)
            print("[AI Auto Update] Curriculum successfully updated and saved based on daily student data.")

    except Exception as e:
        logger.exception("커리큘럼 자동 업데이트 실패")
        print(f"[AI Auto Update Error] Failed to auto-update curriculum: {e}")


async def analyze_uploaded_file(filename: str, content: bytes) -> str:
    logger.info(f"[ANALYZE_UPLOADED_FILE] 시작 filename={filename}")
    if not GEMINI_API_KEY:
        raise ValueError("Gemini API Key가 설정되지 않았습니다.")

    suffix = os.path.splitext(filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        print(f"[AI Analysis] Uploading {filename} to Gemini...")
        uploaded_file = await asyncio.to_thread(
            get_client().files.upload, file=tmp_path, config={'display_name': filename}
        )

        prompt = (
            "당신은 최고 수준의 예술/예체능 입시 전문가이자 AI 교육 설계자입니다. "
            "첨부된 자료(문서 또는 이미지)를 정밀하게 분석하여, 우리 학원의 선생님이 이 내용을 '입시생 커리큘럼(규칙, 팁, 연습 방법 등)'에 "
            "어떻게 반영하면 좋을지 요약해서 제안해 주세요. "
            "답변은 3~5가지 핵심 규칙(Bullet Points) 형태로 간결하고 명확하게 제시하고, 가르치는 선생님의 어조로 친절하게 작성해 주세요."
        )

        response = await asyncio.to_thread(
            get_client().models.generate_content,
            model='gemini-2.5-flash',
            contents=[uploaded_file, prompt]
        )
        return response.text
    finally:
        try:
            os.remove(tmp_path)
        except Exception as cleanup_err:
            print(f"[Warning] Cleanup failed: {cleanup_err}")


async def chat_about_curriculum(message: str) -> str:
    logger.info("[CHAT_ABOUT_CURRICULUM] 시작")
    curriculum_text = get_curriculum_text()
    prompt = (
        "당신은 입시생들을 위한 교육 커리큘럼을 관리하고 컨설팅해 주는 AI 교육 마스터입니다.\n"
        f"현재 레슨실의 커리큘럼은 다음과 같습니다:\n---\n{curriculum_text}\n---\n"
        f"선생님의 질문/요청: {message}\n\n"
        "선생님의 요청에 맞게 커리큘럼의 어떤 부분을 추가하거나 수정하면 좋을지 친절하게 답변해 주세요."
    )
    response = await asyncio.to_thread(
        get_client().models.generate_content,
        model='gemini-2.5-flash',
        contents=prompt
    )
    return response.text
