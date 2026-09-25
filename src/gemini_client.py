import os
import google.genai as genai

# Google Gemini API Key는 .env 파일의 GEMINI_API_KEY 환경변수로 설정합니다.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
_genai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


def get_client():
    return _genai_client


def is_configured() -> bool:
    return bool(GEMINI_API_KEY)


def strip_code_fence(text: str) -> str:
    """Gemini가 JSON을 ```json ... ``` 펜스로 감싸 보내는 경우가 잦아 그걸 걷어낸다.

    insight/video/입시정보 서비스가 전부 같은 처리를 하고 있어 여기로 모았다.
    """
    text = (text or "").strip()
    if text.startswith("```"):
        # 첫 줄이 ```json 같은 펜스 표시라 통째로 버린다.
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = "\n".join(text.split("\n")[:-1])
    return text.strip()
