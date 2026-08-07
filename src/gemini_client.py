import os
import google.genai as genai

# Google Gemini API Key는 .env 파일의 GEMINI_API_KEY 환경변수로 설정합니다.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
_genai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


def get_client():
    return _genai_client


def is_configured() -> bool:
    return bool(GEMINI_API_KEY)
