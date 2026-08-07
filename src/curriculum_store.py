import os
import logging

logger = logging.getLogger("passion_mate")

CURRICULUM_PATH = os.path.join(os.path.dirname(__file__), "../curriculum.txt")
_curriculum_text = ""


def load_curriculum():
    """앱 시작 시 1회 호출 — curriculum.txt를 메모리에 캐싱."""
    global _curriculum_text
    try:
        if os.path.exists(CURRICULUM_PATH):
            with open(CURRICULUM_PATH, "r", encoding="utf-8") as f:
                _curriculum_text = f.read()
            print("[DB] Curriculum file loaded successfully.")
        else:
            print("[Warning] curriculum.txt not found. AI will run on default rules.")
    except Exception as e:
        logger.exception("커리큘럼 파일 로드 실패")
        print(f"[Error] Failed to load curriculum.txt: {e}")


def get_curriculum_text() -> str:
    return _curriculum_text


def set_curriculum_text(new_text: str):
    global _curriculum_text
    _curriculum_text = new_text
