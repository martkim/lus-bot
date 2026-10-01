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

# Gemini 무료 티어 일일 한도(20회) 중 백그라운드 루프가 이미 하루 6회를 고정으로 쓴다.
# 학생 8명이 나눠 쓴다는 가정하에 1인당 하루 2회로 제한 — 한 학생이 반복 호출해서
# 다른 학생들 몫까지 소진시키는 걸 막는다.
DAILY_AI_LIMIT_PER_STUDENT = 2

# Gemini가 안 될 때 내보내는 전공별 폴백. 키는 students.instrument에 저장되는 값이자
# insight_service.PART_FOCUS의 키와 같은 6개다 — 셋이 어긋나면 그 전공 학생만
# 조용히 일반 답변을 받게 된다.
PART_FALLBACK_TIPS = {
    "일렉기타": (
        "**[일렉기타 연습 수칙]**\n\n"
        "- 크로매틱과 운지 워밍업 10분으로 시작하세요. 손에 힘이 들어가는 속도면 아직 빠른 겁니다.\n"
        "- 코드는 모양이 아니라 구성음으로 외우고, 같은 코드를 세 가지 보이싱으로 짚어 보세요.\n"
        "- 앰프와 페달 세팅을 곡마다 적어 두세요. 실기장 장비가 달라도 돌아올 기준점이 됩니다."
    ),
    "베이스": (
        "**[베이스 연습 수칙]**\n\n"
        "- 루트만 짚지 말고 코드톤 안에서 다음 코드로 이어지는 워킹 라인을 매일 10분 만들어 보세요.\n"
        "- 메트로놈을 2박과 4박에만 두세요. 모든 박에 두면 박이 밀리는 걸 스스로 못 느낍니다.\n"
        "- 킥 드럼 패턴을 틀어놓고 그 위에 라인을 얹는 연습이 베이스의 본업입니다."
    ),
    "작곡": (
        "**[작곡 연습 수칙]**\n\n"
        "- 매일 코드 진행 하나를 받아적고, 왜 그 자리에 그 코드가 왔는지 기능으로 설명해 보세요.\n"
        "- 8마디짜리라도 끝을 맺으세요. 미완성 스케치 열 개보다 완성한 한 곡이 입시에 쓰입니다.\n"
        "- 시창청음 15분을 매일 넣으세요. 작곡 전공도 실기에서 청음을 봅니다."
    ),
    "보컬": (
        "**[보컬 연습 수칙]**\n\n"
        "- 발성 전 호흡 훈련 10분. 많이 마시는 게 아니라 일정하게 내보내는 것이 목표입니다.\n"
        "- 음정은 느낌이 아니라 확인입니다. 피아노나 튜너로 대조해 어느 쪽으로 밀리는지 알아 두세요.\n"
        "- 고음은 지르는 게 아닙니다. 목에 힘이 들어가는 지점 아래를 먼저 다듬고 올라가세요."
    ),
    "미디": (
        "**[미디 연습 수칙]**\n\n"
        "- 작업 템플릿과 단축키 열 개를 손에 붙이세요. 트랙 까는 시간이 작업 시간을 잡아먹습니다.\n"
        "- 프리셋만 고르지 말고 오실레이터-필터-엔벨로프를 직접 움직여 소리 변화를 익히세요.\n"
        "- 믹싱은 플러그인 전에 페이더입니다. 레벨 밸런스만으로 들을 만한 상태를 먼저 만드세요."
    ),
    "드럼": (
        "**[드럼 연습 수칙]**\n\n"
        "- 느린 템포에서 정확히 맞는지부터 확인하고 올리세요. 메트로놈 없는 연습은 연습이 아닙니다.\n"
        "- 그루브는 세기의 차이에서 나옵니다. 스네어와 하이햇의 강약을 의도적으로 다르게 쳐 보세요.\n"
        "- 필인이 마디를 넘기지 않게 하세요. 필 치다 박 놓치는 것이 가장 흔한 감점 요인입니다."
    ),
}


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

    if student_id is not None:
        today_str = datetime.now().strftime("%Y-%m-%d")
        usage_count = db.get_todays_ai_usage_count(student_id, today_str)
        if usage_count >= DAILY_AI_LIMIT_PER_STUDENT:
            logger.info(f"[AI_LIMIT] student_id={student_id} 일일 한도 초과 ({usage_count}/{DAILY_AI_LIMIT_PER_STUDENT})")
            if is_draft:
                return "(오늘 AI 사용 한도를 넘어 자동 초안을 생성하지 못했습니다 — 선생님께서 직접 답변해 주세요.)"
            return (
                "오늘 AI 상담을 이미 2회 이용하셨어요! 하루 이용 한도라서 내일 다시 이용해 주세요. "
                "급한 질문은 '질문하기'로 선생님께 직접 남겨주시면 답변해 드릴게요."
            )

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
        if student_id is not None:
            # 성공/실패 여부와 무관하게 시도 시점에 기록 — 실패해도 Google 쪽 요청은
            # 이미 나갔을 수 있어 공용 쿼터 보호 관점에서 보수적으로 카운트한다.
            db.record_ai_usage(student_id, datetime.now().isoformat())

        if is_draft:
            system_instruction = (
                "너는 입시생이 선생님에게 직접 물어볼 질문에 대해, 선생님이 보고 즉시 전송하거나 가볍게 수정하여 답변할 수 있도록 "
                "선생님의 연습 커리큘럼 및 지침서(Curriculum)에 입각하여 명확하고 정중하게 답변 초안을 작성해주는 '버스트인 AI 비서'이다.\n"
                "선생님의 어조(전문적이고 따뜻한 격려의 말투)로 답변을 작성하라. 답변은 2~4문장 내외로 간결하고 핵심적으로 하되, 절대 반말을 쓰지 마라.\n"
                "이모지와 그림문자는 절대 쓰지 마라. 글자만 사용하라.\n\n"
                f"=== [질문 학생의 오늘 학습 내용] ===\n{student_context}\n\n"
                f"=== [선생님의 커리큘럼 및 지침서] ===\n{curriculum_text}\n======================================"
            )
        else:
            system_instruction = (
                "너는 실기 시험을 준비하는 음악 입시생의 학습/연습을 전담하는 '버스트인 AI 튜터' 보조교사이다.\n"
                "항상 친절하고 전문적이며, 학생들에게 영감을 주고 용기를 불어넣는 따뜻한 어조(반말이 아닌 격려의 말투)로 대답하라.\n"
                "특히 아래 명시된 '선생님의 연습 커리큘럼 및 지침서(Curriculum)' 내용을 절대 거스르지 말고 이에 입각하여 조언하라.\n"
                "학생이 '오늘 연습이 안돼요', '울고싶다' 등 감정적인 말을 하면 적극적으로 다독이며 공감을 주어라.\n"
                "이모지와 그림문자는 절대 쓰지 마라. 글자만 사용하라.\n\n"
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
        welcome_prefix = f"**{name} 학생 ({instrument} 전공)**, 반갑습니다! 오늘 벌써 **{today_minutes}분**이나 연습하셨군요. "
        if today_minutes > 0:
            welcome_prefix += "열정 가득한 태도에 진심으로 박수를 보냅니다!\n\n"
        else:
            welcome_prefix += "연습 시작하기를 누르고 집중 훈련을 시작해 볼까요?\n\n"
    else:
        welcome_prefix = "**버스트인 AI 튜터**의 맞춤형 가이드입니다.\n\n"

    # 멘탈/실기 고민이 먼저다. 전공 수칙을 들고 오면 "슬럼프가 왔어요"에 드럼 연습법을
    # 답하게 된다. ("힘"은 "손목 힘 빼기"에도 걸려서 뺐다.)
    if "슬럼프" in msg or "우울" in msg or "좌절" in msg or "포기" in msg:
        return (
            welcome_prefix +
            "**[슬럼프일 때]**\n\n"
            "슬럼프에는 난이도를 낮추는 게 정답입니다. 입시곡을 붙들지 말고 워밍업과 기초 패턴만 30분 하고 끝내세요.\n"
            "제일 위험한 건 악기를 아예 안 만지는 날이 이어지는 겁니다. 짧아도 매일 손을 대는 쪽으로 버티세요.\n"
            "그래도 안 풀리면 혼자 끌지 말고 선생님께 이야기하세요."
        )
    if "긴장" in msg or "떨려" in msg or "실기" in msg or "시험" in msg:
        return (
            welcome_prefix +
            "**[실기 긴장 다루기]**\n\n"
            "긴장은 없애는 게 아니라 익숙해지는 겁니다.\n"
            "- 실기 3주 전부터 주 1회는 친구나 선생님 앞에서, 실제 순서(입장-인사-연주)대로 모의 실기를 해보세요.\n"
            "- 긴장 자체보다 '긴장한 상태로 연주해 본 경험'이 점수를 지킵니다.\n"
            "- 실기 2주 전부터는 새 창법이나 새 세팅을 시도하지 마세요."
        )

    # 전공은 로그인 정보에서 바로 온다. 메시지에 전공 이름을 안 써도 자기 전공으로 답한다.
    part = (student_info["instrument"] if student_info else None) or ""
    if part not in PART_FALLBACK_TIPS:
        part = next((p for p in PART_FALLBACK_TIPS if p in msg), "")

    if part:
        return welcome_prefix + PART_FALLBACK_TIPS[part]

    if is_draft:
        return (
            welcome_prefix +
            f"학생이 물어본 '{user_message}'에 대한 답변 초안입니다.\n\n"
            "지금은 AI 연결이 안 돼 전공별 기본 지침만 불러올 수 있습니다. "
            "학생의 전공이 등록돼 있으면 그 전공 수칙이 자동으로 나옵니다."
        )
    return (
        welcome_prefix +
        "지금은 AI 연결이 일시적으로 안 되는 상태라 기본 안내만 드릴 수 있어요.\n\n"
        "전공(일렉기타, 베이스, 작곡, 보컬, 미디, 드럼)이나 '슬럼프', '실기 긴장'처럼 "
        "궁금한 걸 적어주시면 그에 맞는 연습 수칙을 바로 알려드립니다.\n"
        "잠시 뒤에 다시 물어보시면 AI 튜터가 평소처럼 답해 드려요."
    )


async def chat(payload: AIChatRequest) -> str:
    """/api/ai/chat 용 — 빈 메시지 처리만 하고 get_ai_reply에 위임."""
    logger.info("[AI_CHAT] 시작")
    user_message = payload.message.strip()
    if not user_message:
        return None
    return await get_ai_reply(user_message, is_draft=False, student_id=payload.studentId)
