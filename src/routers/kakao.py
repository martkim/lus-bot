import logging

from fastapi import APIRouter, Request

from src.services import kakao_service

logger = logging.getLogger("passion_mate")
router = APIRouter()


def _skill_response(text: str) -> dict:
    """카카오 i 오픈빌더 스킬 응답 v2.0 포맷으로 감싸기."""
    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {"simpleText": {"text": text}}
            ]
        }
    }


@router.post("/api/kakao/webhook")
async def kakao_webhook(request: Request):
    """카카오 i 오픈빌더 스킬 웹훅. 인증 없음 — 카카오 서버가 직접 호출.
    요청 바디에서 userRequest.user.id(카카오 사용자 ID)와 userRequest.utterance(발화)만 사용."""
    try:
        body = await request.json()
        user_request = body.get("userRequest", {})
        kakao_user_id = user_request.get("user", {}).get("id")
        utterance = user_request.get("utterance", "")

        if not kakao_user_id:
            return _skill_response("요청을 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.")

        reply = await kakao_service.handle_kakao_message(kakao_user_id, utterance)
        return _skill_response(reply)
    except Exception as e:
        logger.exception("카카오 웹훅 처리 실패")
        return _skill_response("일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
