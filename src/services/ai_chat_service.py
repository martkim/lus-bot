import json
import asyncio
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone

from src import db
from src.gemini_client import GEMINI_API_KEY, get_client
from src.curriculum_store import get_curriculum_text
from src.dto.ai import AIChatRequest

logger = logging.getLogger("passion_mate")


def _call_gemini_rest_sync(url: str, payload: dict, timeout: int) -> str:
    """Blocking Gemini REST call (urllib has no async API). Always invoke via
    `await asyncio.to_thread(...)` from async code — called directly, this would
    freeze the whole event loop (every other request/response) for up to
    `timeout` seconds while waiting on the network."""
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        res_data = json.loads(response.read().decode("utf-8"))
        return res_data["candidates"][0]["content"]["parts"][0]["text"]


async def get_ai_reply(user_message: str, is_draft: bool = False, student_id: int = None) -> str:
    user_message = user_message.strip()
    if not user_message:
        return "질문 내용을 입력해 주세요."

    curriculum_text = get_curriculum_text()
    student_info = None
    today_minutes = 0
    session_count = 0

    if student_id is not None:
        try:
            student_info = db.get_student_basic(student_id)
            if student_info:
                # 오늘 하루 연습 통계 (완료된 세션 기준)
                today_local_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                today_start_iso = today_local_start.astimezone(timezone.utc).isoformat()

                stats_row = db.get_today_completed_stats(student_id, today_start_iso)
                today_minutes = stats_row["total_minutes"]
                session_count = stats_row["session_count"]

                student_context = (
                    f"이름: {student_info['name']}\n"
                    f"전공: {student_info['instrument']}\n"
                    f"오늘 총 연습 시간: {today_minutes}분\n"
                    f"오늘 완료한 연습 세션: {session_count}회"
                )
        except Exception as db_err:
            logger.exception("AI 챗봇용 학생 정보 조회 실패")
            print(f"[Warning] Database query failed: {db_err}")
            student_context = "등록된 학생 정보가 있으나 조회에 실패했습니다."
    else:
        student_context = "등록된 학생 정보가 없습니다."

    if GEMINI_API_KEY:
        if is_draft:
            system_instruction = (
                "너는 입시생이 선생님에게 직접 물어볼 질문에 대해, 선생님이 보고 즉시 전송하거나 가볍게 수정하여 답변할 수 있도록 "
                "선생님의 연습 커리큘럼 및 지침서(Curriculum)에 입각하여 명확하고 정중하게 답변 초안을 작성해주는 'PASSION MATE AI 비서'이다.\n"
                "선생님의 어조(전문적이고 따뜻한 격려의 말투)로 답변을 작성하라. 답변은 2~4문장 내외로 간결하고 핵심적으로 하되, 절대 반말을 쓰지 마라.\n\n"
                f"=== [질문 학생의 오늘 학습 내용] ===\n{student_context}\n\n"
                f"=== [선생님의 커리큘럼 및 지침서] ===\n{curriculum_text}\n======================================"
            )
        else:
            system_instruction = (
                "너는 입시생의 학습/연습을 전담하는 전문 'PASSION MATE AI 센터' 보조교사이다.\n"
                "항상 친절하고 전문적이며, 학생들에게 영감을 주고 용기를 불어넣는 따뜻한 어조(반말이 아닌 격려의 말투)로 대답하라.\n"
                "특히 아래 명시된 '선생님의 연습 커리큘럼 및 지침서(Curriculum)' 내용을 절대 거스르지 말고 이에 입각하여 조언하라.\n"
                "학생이 '오늘 연습이 안돼요', '울고싶다' 등 감정적인 말을 하면 적극적으로 다독이며 공감을 주어라.\n\n"
                f"=== [질문 학생의 오늘 학습 내용] ===\n{student_context}\n\n"
                f"=== [선생님의 커리큘럼 및 지침서] ===\n{curriculum_text}\n======================================"
            )

        try:
            prompt = f"System Instructions: {system_instruction}\n\nUser Question: {user_message}"
            response = await asyncio.to_thread(
                get_client().models.generate_content,
                model='gemini-2.5-flash',
                contents=prompt
            )
            return response.text.strip()
        except Exception as e:
            logger.exception("Gemini SDK 호출 실패, 폴백으로 전환")
            print(f"[Warning] Gemini SDK error: {e}. Falling back.")

        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=" + GEMINI_API_KEY
        payload = {
            "contents": [{
                "parts": [{"text": f"System Instructions: {system_instruction}\n\nUser Question: {user_message}"}]
            }]
        }

        try:
            reply_text = await asyncio.to_thread(_call_gemini_rest_sync, url, payload, 8)
            return reply_text
        except urllib.error.URLError as ue:
            print(f"[Warning] Gemini API Connection failed: {ue}. Falling back to rule-based Q&A.")
        except Exception as e:
            logger.exception("Gemini REST 호출 실패, 폴백으로 전환")
            print(f"[Warning] Gemini error: {e}. Falling back.")

    # Rule-based Q&A Fallback
    msg = user_message.lower()

    # 학생 정보가 있다면 이를 가미해서 멘트 구성
    welcome_prefix = ""
    if student_info:
        name = student_info["name"]
        instrument = student_info["instrument"]
        welcome_prefix = f"✨ **{name} 학생 ({instrument} 전공)**, 반갑습니다! 오늘 벌써 **{today_minutes}분**이나 연습하셨군요. "
        if today_minutes > 0:
            welcome_prefix += "열정 가득한 태도에 진심으로 박수를 보냅니다! 👏\n\n"
        else:
            welcome_prefix += "연습 시작하기를 누르고 집중 훈련을 시작해 볼까요? 🚀\n\n"
    else:
        welcome_prefix = "💡 **PASSION AI 튜터**의 맞춤형 가이드입니다.\n\n"

    is_piano = "피아노" in msg or "하농" in msg or "스케일" in msg or "건반" in msg or (student_info and "피아노" in student_info["instrument"])
    is_violin = "바이올린" in msg or "현악" in msg or "활" in msg or "피치" in msg or (student_info and ("바이올린" in student_info["instrument"] or "첼로" in student_info["instrument"]))
    is_composition = "작곡" in msg or "화성" in msg or "이론" in msg or "청음" in msg or (student_info and "작곡" in student_info["instrument"])
    is_vocal = "성악" in msg or "목" in msg or "발성" in msg or "호흡" in msg or (student_info and ("성악" in student_info["instrument"] or "보컬" in student_info["instrument"]))

    if is_piano:
        return (
            welcome_prefix +
            "🎹 **[선생님 피아노 연습 수칙]**\n\n"
            "우리 레슨실의 피아노 입시 규칙에 따라 안내해 드려요!\n"
            "- 매일 연습의 시작은 반드시 **하농(Hanon)과 스케일(Scale)을 30분 이상** 가볍게 치며 손가락을 풀고 릴렉스해야 합니다.\n"
            "- 손목의 힘을 빼는 감각이 가장 중요하니 건반을 억지로 때리지 마세요.\n"
            "- 쇼팽 에튀드 등 대곡은 처음 2~3일간 반드시 **느린 템포**로 연습하며 터치를 몸에 익혀야 템포를 올려도 뭉개지지 않습니다!"
        )
    elif is_violin:
        return (
            welcome_prefix +
            "🎻 **[선생님 바이올린/현악 연습 수칙]**\n\n"
            "바이올린 및 현악기 전공생은 아래 원칙을 매일 지켜야 합니다:\n"
            "- 활 쓰기(Bowing) 기초 연습을 개현(Open string)에서 **매일 15분 이상** 공들여 소리를 고르세요.\n"
            "- 튜너기를 켜두고 본인의 손가락 피치(Intonation)가 완벽한지 매 순간 점검하는 정밀 연습이 생명입니다.\n"
            "- 쉬프트 포지션을 이동할 때 어깨와 엄지손가락에 불필요한 힘을 꼭 빼주세요!"
        )
    elif is_composition:
        return (
            welcome_prefix +
            "📝 **[선생님 작곡/음악이론 수칙]**\n\n"
            "작곡 전공생의 24H 필수 과업 지침입니다:\n"
            "- **매일 화성학 풀이 2문제**를 꼼꼼히 풀고, 연필로 병진행(5도, 8도) 금칙 위반이 있는지 스스로 적어가며 체크하세요.\n"
            "- 매일 아침 귀를 깨워주는 **단선율/2성부 청음 20분 훈련**을 루틴으로 소화해 주세요.\n"
            "- 1주일에 한 곡씩 소나티네 분석 보고서를 꼭 제출해 주세요."
        )
    elif is_vocal:
        return (
            welcome_prefix +
            "🎤 **[선생님 성악 연습 수칙]**\n\n"
            "성악 입시를 위한 아름다운 호흡과 발성 원칙입니다:\n"
            "- 복식 호흡과 아포지오(Appoggio, 호흡 지탱) 감각을 살리기 위해 매일 15분간 호흡 전용 훈련을 마스터해야 합니다.\n"
            "- 목을 억지로 쥐어짜지 말고, 연구개(Soft palate)를 동그랗게 높여 비강 공명을 마음껏 울려주세요.\n"
            "- 이탈리아 가사의 경우 단순 소리뿐만 아니라 정확한 딕션과 뉘앙스를 담아 문학적으로 대답하는 훈련이 필요합니다."
        )
    elif "슬럼프" in msg or "힘" in msg or "우울" in msg or "좌절" in msg:
        return (
            welcome_prefix +
            "🌈 **[선생님의 따뜻한 멘탈 응원]**\n\n"
            "힘든 시기를 겪고 있군요. 슬럼프는 사실 성장을 바로 코앞에 두고 겪는 도약의 신호랍니다.\n"
            "억지로 어려운 입시 곡을 붙잡고 스트레스받지 마세요. 그럴 때는 쉬운 소곡집이나 좋아하는 팝, 혹은 하농을 가볍게 치며 손끝 감각을 즐겨보세요.\n"
            "하루에 단 30분만 악기를 매만지며 마음을 가다듬어도 훌륭한 성취입니다. 선생님이 언제나 곁에서 힘껏 응원하고 있어요. 힘내요! 🎹"
        )
    elif "입시" in msg or "시험" in msg or "실기" in msg or "긴장" in msg:
        return (
            welcome_prefix +
            "✨ **[실기 시험/입시 긴장 극복 꿀팁]**\n\n"
            "실기 시험장이 다가올수록 불안해지는 것은 지극히 당연한 열정의 증거입니다!\n"
            "- 실기 2주 전부터는 일주일에 3번 이상, 실제 연주복을 깔끔히 갖춰 입고 거울 앞에서 인사하고 연주하는 '모의 실기 시뮬레이션'을 반복해 보세요.\n"
            "- 무대 위에서의 긴장감을 설렘과 긍정적인 집중력의 네온 에너지로 치환시키는 연습이 많은 도움이 됩니다."
        )
    else:
        if is_draft:
            return (
                welcome_prefix +
                f"안녕하세요! 입시생의 질문에 대한 자동 분석 가이드입니다. 💡\n\n"
                f"학생이 물어본 '{user_message}'에 대해서는 우리 레슨실의 전공별 지침에 입각하여 성심껏 훈련하도록 지도하겠습니다.\n"
                f"세부 사항을 묻는 질문이라면 전공별 키워드('피아노', '바이올린', '성악', '작곡')를 포함해 대화해 보시는 것을 추천해 드립니다."
            )
        else:
            return (
                welcome_prefix +
                "안녕하세요! 입시생 여러분의 연습 메이트 AI 튜터입니다. 💡\n\n"
                "현재 AI 챗봇의 **[24H 자동 응답 모드]**가 안전하게 기동 중입니다.\n\n"
                "궁금하신 전공 지침이나 팁을 알아보기 위해 아래 키워드를 입력해 질문해 보세요!\n"
                "👉 **키워드 안내**: `'피아노', '바이올린', '성악', '작곡', '슬럼프', '입시'`\n\n"
                "*(💡 교사용 안내: 이 컴퓨터에 구글 Gemini API Key를 설정하시면 최첨단 음악 상담 AI 챗봇이 24시간 실시간 대화형으로 영구 활성화됩니다!)*"
            )


async def chat(payload: AIChatRequest) -> str:
    """/api/ai/chat 용 — 빈 메시지 처리만 하고 get_ai_reply에 위임."""
    logger.info("[AI_CHAT] 시작")
    user_message = payload.message.strip()
    if not user_message:
        return None
    return await get_ai_reply(user_message, is_draft=False, student_id=payload.studentId)
