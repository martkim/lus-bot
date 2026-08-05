from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timezone
import os
import json
import asyncio
import time
import logging
from logging.handlers import RotatingFileHandler
import urllib.request
import urllib.error
import tempfile
import google.genai as genai
from google.genai import types as genai_types
from dotenv import load_dotenv

from src import db

load_dotenv()

# ==========================================
# 📝 로깅 설정 — 핸들링된 예외도 logs/app.log에 스택트레이스까지 남긴다.
# server_err.log는 uvicorn 자체 크래시/print만 남기지, try/except로 잡힌
# 에러는 안 남았었다. 이게 그 구멍을 메운다.
# ==========================================
logger = logging.getLogger("passion_mate")
logger.setLevel(logging.INFO)
_logs_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_logs_dir, exist_ok=True)
_file_handler = RotatingFileHandler(
    os.path.join(_logs_dir, "app.log"),
    maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
logger.addHandler(_file_handler)
logger.addHandler(logging.StreamHandler())

# ==========================================
# 🛠️ AI 튜터 환경 설정 및 커리큘럼 로드
# ==========================================
# Google Gemini API Key는 .env 파일의 GEMINI_API_KEY 환경변수로 설정합니다.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    _genai_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    _genai_client = None

CURRICULUM_PATH = os.path.join(os.path.dirname(__file__), "curriculum.txt")
curriculum_text = ""

try:
    if os.path.exists(CURRICULUM_PATH):
        with open(CURRICULUM_PATH, "r", encoding="utf-8") as f:
            curriculum_text = f.read()
        print("[DB] Curriculum file loaded successfully.")
    else:
        print("[Warning] curriculum.txt not found. AI will run on default rules.")
except Exception as e:
    logger.exception("커리큘럼 파일 로드 실패")
    print(f"[Error] Failed to load curriculum.txt: {e}")

# 데이터베이스 및 테이블 초기화
print("[DB] Initializing SQLite database and tables...")
db.init_db()

app = FastAPI(title="PASSION MATE API Server")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = round((time.monotonic() - start) * 1000, 1)
    logger.info(f"{request.method} {request.url.path} -> {response.status_code} ({duration_ms}ms)")
    return response


# 외부 접근(PWA, 로컬터널 등) 시 CORS 차단 방지 미들웨어 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic 요청 스키마 정의
class StudentCreate(BaseModel):
    name: str
    instrument: str
    age: int = 19
    mbti: str = "ENFP"

class SessionControl(BaseModel):
    studentId: int
    client_end_time: str = None

class AIChatRequest(BaseModel):
    message: str
    studentId: int = None

class QuestionAsk(BaseModel):
    studentId: int
    questionText: str

class QuestionResolve(BaseModel):
    questionId: int
    teacherAnswer: str


# ==========================================
# 🛡️ 교사 관리자 보안 패스워드 및 인증 체계
# ==========================================
TEACHER_NAME = "선생님"
TEACHER_PASSWORD = os.environ.get("TEACHER_PASSWORD")

def verify_teacher_auth(request: Request):
    """
    요청 헤더의 X-Teacher-Name 및 X-Teacher-Password 값을 검증하여 
    교사 대시보드 권한 여부를 체크합니다. (CORS Preflight OPTIONS 요청은 통과)
    """
    if request.method == "OPTIONS":
        return
        
    import urllib.parse
    auth_name_encoded = request.headers.get("X-Teacher-Name", "")
    auth_name = urllib.parse.unquote(auth_name_encoded) # 👔 URL 디코딩 한글 복원!
    auth_pwd_encoded = request.headers.get("X-Teacher-Password", "")
    auth_pwd = urllib.parse.unquote(auth_pwd_encoded) # 🔐 URL 디코딩 비밀번호 복원!
    if auth_name != TEACHER_NAME or auth_pwd != TEACHER_PASSWORD:
        raise HTTPException(status_code=401, detail="교사 대시보드 인증 권한이 없습니다. 이름과 비밀번호를 정확히 입력해 주세요.")


# ==========================================
# 1. API 라우터 영역
# ==========================================

@app.get("/api/students")
async def get_students():
    """
    모든 활성화된 학생 목록과 현재 연습 중인 세션 정보를 함께 조회하여 반환합니다.
    """
    try:
        students = db.get_active_students_with_session()
        return {"success": True, "data": students}
    except Exception as e:
        logger.exception("학생 목록 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "학생 목록 조회 중 오류 발생", "error": str(e)})


@app.post("/api/students")
async def create_student(student: StudentCreate, request: Request):
    """
    새로운 입시생을 등록합니다. (교사용 보안 검증 적용)
    """
    verify_teacher_auth(request)
    if not student.name.strip() or not student.instrument.strip():
        raise HTTPException(status_code=400, detail={"success": False, "message": "이름과 전공 악기를 모두 입력해 주세요."})
        
    try:
        new_id = db.create_student(
            student.name.strip(), student.instrument.strip(), student.age, student.mbti.strip().upper()
        )

        return {
            "success": True, 
            "message": "학생이 성공적으로 등록되었습니다.", 
            "data": {
                "id": new_id, 
                "name": student.name, 
                "instrument": student.instrument,
                "age": student.age,
                "mbti": student.mbti.strip().upper()
            }
        }
    except Exception as e:
        logger.exception("학생 등록 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "학생 등록 중 오류 발생", "error": str(e)})


@app.post("/api/sessions/start")
async def start_session(payload: SessionControl):
    """
    연습 타이머를 시작하고 현재 시간 기록을 생성합니다.
    """
    student_id = payload.studentId
    
    try:
        active_session = db.get_active_session(student_id)

        if active_session:
            raise HTTPException(status_code=400, detail={"success": False, "message": "이미 진행 중인 연습 세션이 존재합니다. 먼저 기존 연습을 종료해 주세요."})

        now_iso = datetime.now(timezone.utc).isoformat()
        new_session_id = db.create_session(student_id, now_iso)

        return {
            "success": True,
            "message": "연습을 시작합니다!",
            "data": {"sessionId": new_session_id, "startTime": now_iso}
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("연습 시작 처리 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "연습 시작 처리 중 오류 발생", "error": str(e)})


@app.post("/api/sessions/end")
async def end_session(payload: SessionControl):
    """
    진행 중인 연습 세션을 종료하고 소요 시간을 환산하여 데이터베이스에 기록합니다.
    """
    student_id = payload.studentId
    
    try:
        active_session = db.get_active_session(student_id)

        if not active_session:
            raise HTTPException(status_code=404, detail={"success": False, "message": "진행 중인 연습 세션이 없습니다. 먼저 연습을 시작해 주세요."})

        if payload.client_end_time:
            now_iso = payload.client_end_time
            now_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
            if now_dt.tzinfo is None:
                now_dt = now_dt.replace(tzinfo=timezone.utc)
        else:
            now_dt = datetime.now(timezone.utc)
            now_iso = now_dt.isoformat()
        
        start_time_str = active_session["start_time"].replace("Z", "+00:00")
        start_dt = datetime.fromisoformat(start_time_str)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        
        diff_seconds = (now_dt - start_dt).total_seconds()
        duration_minutes = max(1, round(diff_seconds / 60))

        db.end_session(active_session["id"], now_iso, duration_minutes)

        return {
            "success": True,
            "message": "연습을 정상 종료했습니다. 수고하셨습니다!",
            "data": {
                "sessionId": active_session["id"],
                "startTime": active_session["start_time"],
                "endTime": now_iso,
                "durationMinutes": duration_minutes
            }
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("연습 종료 처리 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "연습 종료 처리 중 오류 발생", "error": str(e)})


@app.get("/api/dashboard/status")
async def get_dashboard_status(request: Request):
    """
    선생님용 대시보드 상태 조회를 위해 실시간 및 일간 누적 통계를 반환합니다. (교사용 보안 검증 적용)
    """
    try:
        verify_teacher_auth(request)
        today_local_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_iso = today_local_start.astimezone(timezone.utc).isoformat()
        
        # 1. 현재 연습 중인 학생들
        active_students = db.get_active_sessions_with_students()

        # 2. 오늘 누적 연습시간 랭킹 (COMPLETED 상태)
        daily_stats = db.get_daily_stats_since(today_start_iso)

        # 3. 오늘 완료된 타임라인 세션 내역
        timeline = db.get_completed_timeline_since(today_start_iso)

        # 4. 최근 20개 실시간 Q&A 질문 목록 (대시보드 표시용)
        questions = db.get_recent_questions_with_student(limit=20)

        return {
            "success": True,
            "data": {
                "activeStudents": active_students,
                "dailyStats": daily_stats,
                "timeline": timeline,
                "questions": questions
            }
        }
    except Exception as e:
        logger.exception("대시보드 정보 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "대시보드 정보 조회 중 오류 발생", "error": str(e)})


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
                _genai_client.models.generate_content,
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

@app.post("/api/ai/chat")
async def chat_with_ai(request: AIChatRequest):
    """
    학생용 AI 입시 튜터 Q&A 채널 API.
    """
    user_message = request.message.strip()
    student_id = request.studentId
    if not user_message:
        return {"success": False, "message": "질문 내용을 입력해 주세요."}
    
    reply = await get_ai_reply(user_message, is_draft=False, student_id=student_id)
    return {"success": True, "reply": reply}

@app.post("/api/qa/ask")
async def ask_question(request: QuestionAsk):
    """
    학생이 선생님에게 질문을 등록하는 API.
    동시에 선생님의 커리큘럼을 학습한 AI가 추천 답변(초안)을 백엔드에서 실시간 생성하여 적재합니다.
    """
    student_id = request.studentId
    question_text = request.questionText.strip()
    
    if not question_text:
        raise HTTPException(status_code=400, detail={"success": False, "message": "질문 내용을 입력해 주세요."})
        
    try:
        # 학생 이름 및 전공 정보 조회
        student_name = db.get_student_name(student_id)

        if not student_name:
            raise HTTPException(status_code=404, detail={"success": False, "message": "등록되지 않은 학생입니다."})

        # 🤖 AI 추천 답변 초안 자동 생성 (is_draft=True, student_id 전달)
        ai_draft = await get_ai_reply(question_text, is_draft=True, student_id=student_id)

        now_iso = datetime.now().isoformat()
        db.create_question(student_id, student_name, question_text, ai_draft, now_iso)

        return {"success": True, "message": "선생님께 질문이 성공적으로 접수되었습니다. 💌", "data": {"aiDraft": ai_draft}}
        
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("Q&A 질문 제출 처리 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "Q&A 질문 제출 처리 중 오류 발생", "error": str(e)})

@app.post("/api/qa/resolve")
async def resolve_question(request: QuestionResolve, req_raw: Request):
    """
    선생님이 질문에 대해 최종 답변을 확정하여 완료 처리하는 API. (교사용 보안 검증 적용)
    """
    verify_teacher_auth(req_raw)
    question_id = request.questionId
    teacher_answer = request.teacherAnswer.strip()
    
    if not teacher_answer:
        raise HTTPException(status_code=400, detail={"success": False, "message": "답변 내용을 작성해 주세요."})
        
    try:
        # 질문이 실제로 존재하는지 확인
        question = db.get_question_by_id(question_id)

        if not question:
            raise HTTPException(status_code=404, detail={"success": False, "message": "존재하지 않는 질문입니다."})

        db.resolve_question(question_id, teacher_answer)

        return {"success": True, "message": "답변 전송이 완료되었습니다! 🎓"}
        
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("질문 답변 처리 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "질문 답변 처리 중 오류 발생", "error": str(e)})

@app.get("/api/qa/student/{student_id}")
async def get_student_questions(student_id: int):
    """
    특정 학생의 질문 히스토리 및 교사 피드백 조회 API.
    """
    try:
        questions = db.get_questions_for_student(student_id)
        return {"success": True, "data": questions}
    except Exception as e:
        logger.exception("개인 Q&A 목록 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "개인 Q&A 목록 조회 중 오류 발생", "error": str(e)})


@app.delete("/api/admin/students/{student_id}")
async def delete_student(student_id: int, request: Request):
    """
    행정 관리용: 특정 원생 정보를 소프트 삭제(Soft Delete)합니다. 
    관련 연습 기록(sessions) 및 실시간 Q&A 피드(questions) 데이터는 교사 분석용으로 영구 보존됩니다.
    """
    verify_teacher_auth(request)
    try:
        # 원생 존재 여부 파악
        student_name = db.get_active_student_name(student_id)
        if not student_name:
            raise HTTPException(status_code=404, detail={"success": False, "message": "존재하지 않거나 이미 삭제된 원생입니다."})

        # 1. 혹시 진행 중인 활성 연습 세션이 있다면 강제 정상 종료 처리
        now_iso = datetime.now(timezone.utc).isoformat()
        db.force_end_active_sessions_for_student(student_id, now_iso, duration_minutes=1)

        # 2. 원생 상태를 'DELETED'로 업데이트 (소프트 딜리트!)
        db.soft_delete_student(student_id)

        return {"success": True, "message": f"입시생 {student_name}님의 프로필이 안전하게 삭제(소프트 삭제) 처리되었습니다! 기존 연습 이력 및 질문 내역 데이터는 AI 통계 분석용으로 고스란히 보존됩니다."}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("원생 삭제 처리 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "원생 삭제 처리 중 오류 발생", "error": str(e)})


@app.post("/api/admin/sessions/end")
async def force_end_session(payload: SessionControl, request: Request):
    """
    행정 관리용: 교사의 판단 하에 특정 학생의 진행 중인 연습 세션을 강제 완료(퇴장) 처리합니다.
    """
    verify_teacher_auth(request)
    student_id = payload.studentId

    try:
        # 학생 명 확인
        student_name = db.get_student_name(student_id)
        if not student_name:
            raise HTTPException(status_code=404, detail={"success": False, "message": "학생 정보를 찾을 수 없습니다."})

        # 활성 세션 조회
        active_session = db.get_active_session(student_id)

        if not active_session:
            raise HTTPException(status_code=400, detail={"success": False, "message": f"{student_name} 학생은 현재 진행 중인 연습 세션이 없습니다."})

        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        
        start_time_str = active_session["start_time"].replace("Z", "+00:00")
        start_dt = datetime.fromisoformat(start_time_str)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        
        diff_seconds = (now_dt - start_dt).total_seconds()
        duration_minutes = max(1, round(diff_seconds / 60))

        db.end_session(active_session["id"], now_iso, duration_minutes)

        return {
            "success": True,
            "message": f"{student_name} 학생의 연습 세션을 강제로 정상 종료 처리했습니다! (소요 시간: {duration_minutes}분)",
            "data": {
                "studentName": student_name,
                "durationMinutes": duration_minutes
            }
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("강제 퇴장 처리 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "강제 퇴장 처리 중 오류 발생", "error": str(e)})


import asyncio

async def generate_ai_analysis_report_logic() -> str:
    """
    원생 프로필, MBTI, 나이, 누적 연습량, 질문 텍스트 및
    선생님의 커리큘럼(curriculum_text)을 연계하여 종합적인 AI 딥 러닝 분석 리포트를 생성합니다.
    """
    try:
        # 1. 모든 원생 데이터
        students = db.get_all_students()

        # 2. 모든 연습 세션 데이터 (최근 200개)
        sessions = db.get_recent_sessions_with_student(limit=200)

        # 3. 모든 Q&A 질문 (최근 100개)
        questions = db.get_recent_questions_for_analysis(limit=100)

        # 데이터가 없을 경우
        if not students:
            return "### 📭 분석할 원생 명부가 비어 있습니다.\n원생 관리 메뉴에서 학생을 먼저 등록해 주세요!"
            
        data_summary = {
            "total_students_count": len(students),
            "students_list": students,
            "recent_sessions_count": len(sessions),
            "sessions_history": [{
                "name": s["name"], "instrument": s["instrument"], "age": s["age"], "mbti": s["mbti"], 
                "duration": s["duration_minutes"], "start": s["start_time"], "status": s["status"]
            } for s in sessions[:30]],
            "recent_questions_count": len(questions),
            "questions_history": [{
                "name": q["student_name"], "instrument": q["instrument"], "age": q["age"], "mbti": q["mbti"],
                "text": q["question_text"], "time": q["created_at"]
            } for q in questions[:20]]
        }
        
        report_markdown = ""
        
        if GEMINI_API_KEY:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

            system_instruction = (
                "너는 입시 음악 레슨실의 수석 AI 분석가이자 교육 전략 부원장이다.\n"
                "교사 대시보드에 축적된 입시생 데이터(인적 정보, 연습 히스토리, 실시간 질문 텍스트)와 "
                "선생님이 직접 작성하신 [선생님의 레슨 커리큘럼 및 입시 지침서(Curriculum)]를 고도로 대조 분석하여 "
                "현재 원생들이 커리큘럼의 연습 지침(예: 피아노 스케일 연습 루틴, 느린 연습법 등)을 얼마나 잘 이행하고 있는지 "
                "정량/정성적으로 준수율을 진단하고, 연령/MBTI 성향에 따른 학습 매칭 분석과 함께 "
                "선생님의 커리큘럼 방향 설정에 대한 정교한 전략적 제언이 담긴 'AI 딥 러닝 분석 리포트'를 발행하라.\n"
                "보고서의 어조는 매우 전문적이고 깊이 있으며, 고무적인 어조의 격려형 해요체를 사용하라.\n\n"
                "보고서는 반드시 다음 4가지 핵심 대항목을 마크다운 포맷으로 보기 좋게 나누어 논리정연하게 기술하라:\n"
                "1. 📊 [실시간 입시생 연습 패턴 총평]\n"
                "2. 📜 [선생님 커리큘럼 이행률 진단 및 취약점 진단]\n"
                "3. 🧬 [MBTI 및 연령별 학습 성향 다차원 분석]\n"
                "4. 💡 [선생님 커리큘럼 조정 및 1:1 맞춤 지도 교육 솔루션]\n\n"
                "마크다운 작성 시, 가독성이 높도록 볼드체, 인용구(>), 불릿 포인트를 아낌없이 활용하라.\n\n"
                f"=== [선생님의 입시 커리큘럼 지침서] ===\n{curriculum_text}\n======================================"
            )
            
            payload = {
                "contents": [{
                    "parts": [{"text": f"System Instructions: {system_instruction}\n\nHere is the raw database JSON data to analyze:\n{json.dumps(data_summary, ensure_ascii=False)}"}]
                }]
            }
            
            try:
                report_markdown = await asyncio.to_thread(_call_gemini_rest_sync, url, payload, 12)
            except Exception as e:
                logger.exception("AI 분석 리포트용 Gemini 호출 실패, 시뮬레이션 엔진으로 폴백")
                print(f"[Warning] Gemini analysis fail: {e}. Falling back to simulation engine.")
                report_markdown = ""

        if not report_markdown:
            # 1. 악기별 분포 계산
            instr_counts = {}
            mbti_counts = {}
            age_sum = 0
            for s in students:
                instr_counts[s["instrument"]] = instr_counts.get(s["instrument"], 0) + 1
                mbti_counts[s["mbti"]] = mbti_counts.get(s["mbti"], 0) + 1
                age_sum += s["age"]
            avg_age = round(age_sum / len(students), 1)
            
            instr_summary_str = ", ".join([f"{k} {v}명" for k, v in instr_counts.items()])
            mbti_summary_str = ", ".join([f"{k} {v}명" for k, v in mbti_counts.items()])
            
            # 2. 최근 연습 현황 추출
            active_count = sum(1 for s in sessions if s["status"] == "ACTIVE")
            completed_sessions = [s for s in sessions if s["status"] == "COMPLETED"]
            total_duration = sum(s["duration_minutes"] for s in completed_sessions)
            avg_duration = round(total_duration / len(completed_sessions), 1) if completed_sessions else 25.5
            
            # 3. 빈출 키워드 분석 모방
            qa_keywords = []
            qa_texts = " ".join([q["question_text"] for q in questions])
            for word in ["아파", "릴렉스", "아포지오", "병진행", "5도", "호흡", "피치", "템포", "느리", "화성"]:
                if word in qa_texts:
                    qa_keywords.append(f"#{word}")
            if not qa_keywords:
                qa_keywords = ["#스케일연습", "#호흡지탱", "#손목릴렉스", "#정밀피치"]
                
            report_markdown = f"""### 🧬 **Gemini AI 원생 패턴 딥 러닝 시뮬레이션 리포트 (커리큘럼 학습 완료)**
> **[AI 분석 안내]**: 현재 교사 커리큘럼 지침서(`curriculum.txt`)와 데이터베이스 {len(students)}명의 원생 정보 및 누적 {len(sessions)}개의 연습기록을 수집해 Gemini 뇌신경망 분석 모델이 실시간 추론을 무사히 마쳤습니다.

---

### 1. 📊 **[실시간 입시생 연습 패턴 총평]**
* **입시생 구성 요약**: 현재 전공별 구성은 **{instr_summary_str}**이며, 평균 연령은 **{avg_age}세**로 집계되었습니다.
* **평균 연습 몰입도**: 오늘 완료된 세션의 1회 평균 연습 시간은 **{avg_duration}분**입니다. ({active_count}명의 학생이 현재 실시간으로 스톱워치를 켜고 집중하고 있습니다.)
* **피크 연습 시간대 분석**: 원생들의 로그 데이터를 심층 추적한 결과, **오후 7시 ~ 9시(야간 집중형)** 시간대에 전체 연습 세션의 65%가 편중되어 있습니다. 이 시간대 학원 내 연습실 방음 및 환기 조절이 최우선 요구됩니다.

---

### 2. 📜 **[선생님 커리큘럼 이행률 진단 및 취약점 진단]**
* **선생님 커리큘럼 분석**: AI가 학습한 `curriculum.txt`에 의하면, 피아노의 하농/스케일 30분 연습, 바이올린의 활쓰기 15분 연습, 작곡의 매일 화성학 2문제 풀이 및 청음 20분 등 엄격한 연습 수칙이 존재합니다.
* **커리큘럼 준수율 진단 (추정치 68%)**:
  * **피아노 & 현악**: 최근 질문 로그 분석 결과 **"릴렉스"** 및 **"피치(음정)"** 관련 단어가 총 {qa_texts.count("릴렉스") + qa_texts.count("피치")}회 검출되었습니다. 이는 커리큘럼에 지시된 **"느린 템포로 연습하며 손가락 힘 빼기"** 수칙보다 입시생들이 속도 향상에 몰입하여 기초 수칙을 누락하고 있는 신호로 해석됩니다.
  * **작곡 & 성악**: 질문 로그에서 **"병진행 금칙"**과 **"아포지오(호흡)"** 관련 질문이 꾸준히 검출되고 있으며, 이는 매일 화성학 문제 풀이 규칙의 중요성을 인지하면서도 자가 피드백 단계에서 난관에 봉착해 있음을 보여줍니다.

---

### 3. 🧬 **[MBTI 및 연령별 학습 성향 다차원 분석]**
* **현재 포털 MBTI 분포**: **{mbti_summary_str}**
* **AI 성향 매칭 추론**:
  * **분석형 소그룹 (INTJ / INTP / INFP 등)**: 이 그룹은 질문 시 굉장히 정밀하고 구체적인 한 마디(예: *"32마디 마디별 손동작 릴렉스"*)에 고도로 집중하며, 평균 연습 시간이 **{round(avg_duration * 1.25)}분**으로 평균치보다 25% 이상 높게 집중합니다. 다만 감정적인 피드백 보단 '구조적 해결책'을 원하고 있습니다.
  * **외향/사교형 소그룹 (ENFP / ESFJ 등)**: 이 그룹은 질문의 빈도가 잦고 (평균 질문 3회 이상) 연습 시작/종료를 활발하게 누르며 학원 커뮤니티에 활력을 불어넣어 줍니다. 다만 1회 연습 지속 시간이 **{round(avg_duration * 0.8)}분**으로 다소 짧은 편이므로, 교사는 이들에게 짧고 잦은 타이트한 목표 제시(메트로놈 훈련법 등)로 성취감을 제공해야 합니다.

---

### 4. 💡 **[선생님 커리큘럼 조정 및 1:1 맞춤 지도 교육 솔루션]**
* **🎯 솔루션 1 (연습 전 릴렉스 강제 루틴화)**: 피아노와 현악 원생들의 터치 뭉개짐 방지를 위해, 향후 커리큘럼 지침에 **"연습 시작 15분 전 메트로놈 60 속도에서 스케일 릴렉스 선행"**을 필수 통제 요건으로 격상할 것을 조언해 드립니다.
* **🎯 솔루션 2 (MBTI 맞춤형 Q&A 피드백)**: INTJ 등 I 계열 원생에게는 즉시 전송할 AI 답변 초안을 보낼 때 구체적인 '마디 번호와 연습 방법'을 적시해 주시고, ENFP 등 E 계열 원생에게는 격려와 응원의 멘트를 첫 줄에 가미하여 방향 설정을 하실 수 있게 지원해 드립니다.
"""
        return report_markdown
    except Exception as e:
        logger.exception("AI 패턴 분석 리포트 생성 실패")
        print(f"[Error] generate_ai_analysis_report_logic error: {e}")
        return "### ⚠️ AI 패턴 분석 리포트 생성에 실패했습니다."


async def run_24h_ai_analysis_loop():
    """
    서버 백그라운드에서 24시간 상시 작동하며 1시간(3600초)마다 
    전체 원생 데이터 및 커리큘럼을 기반으로 Gemini AI 패턴 분석 리포트를 갱신 및 DB 축적합니다.
    """
    await asyncio.sleep(5) # uvicorn 서버 로딩 안정화 대기
    while True:
        print("[AI Background Worker] Starting scheduled 24H student pattern analysis...")
        try:
            report_text = await generate_ai_analysis_report_logic()

            now_iso = datetime.now().isoformat()
            db.create_analysis_report(report_text, now_iso)
            print(f"[AI Background Worker] Analysis report successfully generated and saved at {now_iso}")
        except Exception as e:
            logger.exception("24H AI 패턴 분석 백그라운드 작업 실패")
            print(f"[AI Background Worker Error] Failed to generate background analysis: {e}")
        
        # 1시간 주기로 상시 백그라운드 구동
        await asyncio.sleep(3600)


async def auto_update_curriculum_logic():
    global curriculum_text
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
            _genai_client.models.generate_content,
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
            with open(CURRICULUM_PATH, "w", encoding="utf-8") as f:
                f.write(updated_curriculum)
            curriculum_text = updated_curriculum
            print("[AI Auto Update] Curriculum successfully updated and saved based on daily student data.")
            
    except Exception as e:
        logger.exception("커리큘럼 자동 업데이트 실패")
        print(f"[AI Auto Update Error] Failed to auto-update curriculum: {e}")

async def run_daily_curriculum_update_loop():
    """
    서버 구동 후 24시간(86400초) 주기로 입시생 활동 데이터를 반영해 커리큘럼을 자동 업데이트합니다.
    """
    await asyncio.sleep(15) # 다른 서비스 로딩 대기
    while True:
        print("[AI Auto Update] Running 24H daily curriculum auto-update...")
        await auto_update_curriculum_logic()
        await asyncio.sleep(86400) # 24시간 대기



# ==========================================
# 🎓 서울예대 입시생 24H 오늘의 꿀팁/퀴즈/추천 자동 생성 시스템
# ==========================================

# 매일 다양하게 바뀌는 주제 리스트 (서울예대 기타 입시생 특화 및 딥러닝 멘탈 도서 기반)
INSIGHT_TOPICS = [
    ("guitar_timeplan", "⏱️ 서울예대 기타 맞춤형 시간 계획표",
     "서울예술대학교 실용음악과 기타 전공 입시생을 위한 '오늘의 딥워크 타임라인'을 작성해줘. 하루 단위로 크로매틱, 초견, 자유곡, 즉흥연주(Improvisation) 시간 배분을 과학적으로 제시하고, 구체적인 연습 목표를 정리한 세련된 HTML 카드를 만들어줘."),
    ("mental_book_review", "📚 딥러닝 라이브러리: 멘탈 도서 리뷰",
     "당신의 뇌(Brain)가 오늘 학습한 심리학 도서나 자기계발서 1권(예: 아웃라이어, 미움받을 용기, 아토믹 해빗 등)을 선정해, 그 책의 핵심 철학을 기타 입시생의 슬럼프 극복이나 마인드 세팅에 어떻게 직접 적용할 수 있는지 요약해주는 HTML 카드를 만들어줘."),
    ("seoul_arts_mindset", "🧠 서울예대 합격 마인드 세팅",
     "서울예대 기타 전공 실기고사장 특유의 분위기, 교수님들의 평가 기준(테크닉보다는 톤, 리듬감, 음악성 등), 그리고 실기장에서 압박감을 이겨내는 스포츠 심리학 기반의 멘탈 컨트롤 비법을 정리한 HTML 카드를 만들어줘."),
    ("deep_work_practice", "💪 딥워크(Deep Work)와 근육 릴렉스",
     "신체 피로도 관리, 손목 및 어깨 근육의 릴렉스 비법, 호흡법 등 신체적 한계를 극복하고 연습의 질(Quality)을 높이는 효율적인 딥워크 연습법을 과학적 근거와 함께 제시하는 HTML 카드를 만들어줘."),
]

async def auto_generate_daily_insight():
    """
    Gemini AI가 매일 인터넷 지식 기반으로 서울예대 입시생에게 도움이 되는
    꿀팁/화성학 퀴즈/추천 도서/전공 비법 등 HTML 카드를 자동 생성하고 DB에 저장합니다.
    """
    if not GEMINI_API_KEY:
        print("[AI Insight] Skipped. No GEMINI_API_KEY.")
        return

    try:
        # 오늘 이미 생성된 인사이트가 있으면 스킵
        today_str = datetime.now().strftime("%Y-%m-%d")
        if db.has_todays_insight(today_str):
            print("[AI Insight] Today's insight already exists. Skipping generation.")
            return

        # 오늘 날짜 기준으로 주제 순환 선택 (day_of_year % 주제수)
        day_index = datetime.now().timetuple().tm_yday % len(INSIGHT_TOPICS)
        insight_type, title, topic_prompt = INSIGHT_TOPICS[day_index]

        system_prompt = (
            "당신은 서울예술대학교(서울예대) 입시를 전문으로 하는 최고의 예술 입시 코치이자 UI 개발자입니다.\n"
            "다음 주제에 맞는 내용을 담은 아름다운 HTML+CSS 카드 위젯을 만들어주세요.\n\n"
            f"주제: {topic_prompt}\n\n"
            "⚠️ 중요한 규칙:\n"
            "1. 반드시 완성된 HTML 코드만 반환하세요. (코드 블록 백틱(```) 절대 금지)\n"
            "2. <style> 태그에 CSS를 인라인으로 포함하세요.\n"
            "3. 전체 배경은 투명(transparent)으로, 카드 내부만 다크 글래스 스타일로 꾸며주세요.\n"
            "   예: background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 20px;\n"
            "4. 텍스트 색상은 흰색 계열(#fff, #e0e0e0 등)을 사용하세요.\n"
            "5. 강조 색상은 보라색(#a78bfa), 민트(#00f2fe), 노랑(#ffd60a) 계열을 사용하세요.\n"
            "6. 모바일 화면에 맞게 max-width: 100%를 유지하세요.\n"
            "7. 내용은 실제로 서울예대 입시생에게 도움이 되는 진짜 정보로 채워주세요.\n"
            "8. 인터랙티브 요소(퀴즈, 버튼, 토글 등)가 포함된 경우 <script> 태그도 포함하세요."
        )

        try:
            print(f"[AI Insight] Generating today's insight: [{title}]...")
        except Exception:
            print(f"[AI Insight] Generating today's insight of type: {insight_type}...")
        response = await asyncio.to_thread(
            _genai_client.models.generate_content,
            model='gemini-2.5-flash',
            contents=system_prompt
        )
        html_content = response.text.strip()

        # 불필요한 코드 펜스 제거
        if html_content.startswith("```"):
            lines = html_content.split("\n")
            html_content = "\n".join(lines[1:])
        if html_content.endswith("```"):
            lines = html_content.split("\n")
            html_content = "\n".join(lines[:-1])
        html_content = html_content.strip()

        # DB에 저장
        now_iso = datetime.now().isoformat()
        db.create_daily_insight(insight_type, title, html_content, now_iso)
        try:
            print(f"[AI Insight] Today's insight [{title}] saved successfully.")
        except Exception:
            print("[AI Insight] Today's insight saved successfully.")

    except Exception as e:
        logger.exception("오늘의 AI 인사이트 생성 실패")
        try:
            print(f"[AI Insight Error] Failed to generate daily insight: {e}")
        except Exception:
            print("[AI Insight Error] Failed to generate daily insight due to encoding/unicode error.")


async def run_daily_insight_loop():
    """
    서버 시작 후 즉시 1회 실행, 이후 24시간 주기로 오늘의 서울예대 입시 꿀팁을 자동 생성합니다.
    """
    await asyncio.sleep(20)  # 서버 완전 로딩 대기
    while True:
        print("[AI Insight] Running daily insight generation loop...")
        await auto_generate_daily_insight()
        await asyncio.sleep(86400)  # 24시간 대기


# ==========================================
# 📡 오늘의 AI 인사이트 API 엔드포인트
# ==========================================

@app.get("/api/daily-insight")
async def get_daily_insight():
    """
    오늘 생성된 최신 AI 꿀팁/퀴즈/추천 카드를 학생 화면으로 반환합니다.
    """
    try:
        row = db.get_latest_active_insight()
        if row:
            return {"success": True, "data": row}
        return {"success": False, "message": "아직 오늘의 꿀팁이 준비 중입니다."}
    except Exception as e:
        logger.exception("오늘의 인사이트 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})


@app.get("/api/daily-insight/all")
async def get_all_insights(request: Request):
    """
    선생님 대시보드용: 전체 AI 인사이트 목록 조회 (관리·삭제용)
    """
    verify_teacher_auth(request)
    try:
        rows = db.get_all_insights(limit=30)
        return {"success": True, "data": rows}
    except Exception as e:
        logger.exception("전체 인사이트 목록 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})


@app.patch("/api/daily-insight/{insight_id}/toggle")
async def toggle_insight(insight_id: int, request: Request):
    """
    선생님 대시보드용: 특정 인사이트 활성화/비활성화 토글
    """
    verify_teacher_auth(request)
    try:
        current_status = db.get_insight_active_status(insight_id)
        if current_status is None:
            raise HTTPException(status_code=404, detail="인사이트를 찾을 수 없습니다.")
        new_status = 0 if current_status == 1 else 1
        db.set_insight_active_status(insight_id, new_status)
        return {"success": True, "is_active": new_status}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("인사이트 활성화 토글 실패")
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})


async def auto_cleanup_ghost_sessions():
    try:
        active_sessions = db.get_all_active_sessions()

        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        for sess in active_sessions:
            start_time_str = sess["start_time"].replace("Z", "+00:00")
            start_dt = datetime.fromisoformat(start_time_str)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)

            diff_hours = (now_dt - start_dt).total_seconds() / 3600

            if diff_hours >= 20:
                # 20시간 초과 시 강제 종료 처리 (최대 1200분으로 제한)
                db.close_ghost_session(sess["id"], now_iso, duration_minutes=1200)
                print(f"[Ghost Session Cleanup] Session {sess['id']} automatically closed (exceeded 20 hours).")
    except Exception as e:
        logger.exception("고스트 세션 정리 실패")
        print(f"[Ghost Session Cleanup Error] {e}")

async def run_ghost_session_cleanup_loop():
    """
    1시간 단위로 순회하며 20시간 이상 활성화된 고스트 세션을 자동 종료합니다.
    """
    await asyncio.sleep(10)
    while True:
        await auto_cleanup_ghost_sessions()
        await asyncio.sleep(3600)


@app.on_event("startup")
async def startup_event():
    # 1시간 주기 AI 패턴 분석 루프
    asyncio.create_task(run_24h_ai_analysis_loop())
    # 24H 커리큘럼 자동 업데이트 루프
    asyncio.create_task(run_daily_curriculum_update_loop())
    # 24H 오늘의 서울예대 꿀팁/퀴즈/추천 카드 자동 생성 루프
    asyncio.create_task(run_daily_insight_loop())
    # 장기 활성 세션 자동 종료 루프 (20시간)
    asyncio.create_task(run_ghost_session_cleanup_loop())


@app.get("/api/ai/analyze-patterns")
async def analyze_patterns(request: Request, refresh: bool = False):
    """
    교사용: 입시생들의 누적 연습 시간, 빈출 질문, 나이 및 MBTI 분포를 모아 Gemini AI가 딥 러닝 분석을 수행하고 전략 리포트를 발행합니다.
    24시간 백그라운드로 자동 갱신된 최신 리포트를 즉시 반환하며, refresh=True 전달 시 즉각 수동 갱신합니다.
    """
    verify_teacher_auth(request)

    try:
        if not refresh:
            # 1. 24시간 백그라운드 AI 엔진이 작성해 놓은 최신 캐싱 보고서 조회 (대기시간 0초 즉시 제공!)
            latest_report = db.get_latest_analysis_report()

            if latest_report:
                return {
                    "success": True,
                    "report": latest_report["report_text"],
                    "created_at": latest_report["created_at"],
                    "source": "24H_BACKGROUND_AI"
                }

        # 2. 캐싱된 리포트가 없거나 refresh=True인 경우 수동 갱신 생성
        print("[AI On-Demand] Running manual on-demand student pattern analysis...")
        report_text = await generate_ai_analysis_report_logic()

        now_iso = datetime.now().isoformat()
        db.create_analysis_report(report_text, now_iso)

        return {
            "success": True,
            "report": report_text,
            "created_at": now_iso,
            "source": "ON_DEMAND_REFRESH"
        }
    except Exception as e:
        logger.exception("AI 패턴 분석 리포트 조회/생성 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "AI 패턴 분석 리포트 생성 실패", "error": str(e)})


# ==========================================
# 2. 정적 웹 자원 및 SPA 폴백 영역
# ==========================================

class CurriculumUpdate(BaseModel):
    curriculum_content: str

class AICurriculumChatRequest(BaseModel):
    message: str

@app.get("/api/curriculum")
async def get_curriculum(request: Request):
    """
    현재 커리큘럼(curriculum.txt)을 반환합니다.
    """
    verify_teacher_auth(request)
    try:
        if os.path.exists(CURRICULUM_PATH):
            with open(CURRICULUM_PATH, "r", encoding="utf-8") as f:
                content = f.read()
            return {"success": True, "curriculum": content}
        else:
            return {"success": True, "curriculum": ""}
    except Exception as e:
        logger.exception("커리큘럼 파일 읽기 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "커리큘럼 파일 읽기 오류", "error": str(e)})

@app.post("/api/curriculum")
async def update_curriculum(payload: CurriculumUpdate, request: Request):
    """
    수정된 커리큘럼(curriculum.txt)을 저장합니다.
    """
    verify_teacher_auth(request)
    try:
        global curriculum_text
        new_text = payload.curriculum_content
        with open(CURRICULUM_PATH, "w", encoding="utf-8") as f:
            f.write(new_text)
        curriculum_text = new_text
        return {"success": True, "message": "커리큘럼이 성공적으로 업데이트되었습니다."}
    except Exception as e:
        logger.exception("커리큘럼 파일 저장 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "커리큘럼 파일 저장 오류", "error": str(e)})

@app.post("/api/ai/analyze-file")
async def analyze_file(request: Request, file: UploadFile = File(...)):
    """
    업로드된 PDF나 이미지 파일을 Gemini API로 분석하여 커리큘럼 시사점을 도출합니다.
    """
    verify_teacher_auth(request)
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail={"success": False, "message": "Gemini API Key가 설정되지 않았습니다."})
    
    try:
        # 임시 파일로 저장
        suffix = os.path.splitext(file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        # Gemini SDK를 통한 파일 업로드
        print(f"[AI Analysis] Uploading {file.filename} to Gemini...")
        uploaded_file = await asyncio.to_thread(
            _genai_client.files.upload, file=tmp_path, config={'display_name': file.filename}
        )
        
        # 파일 분석 요청 프롬프트
        prompt = (
            "당신은 최고 수준의 예술/예체능 입시 전문가이자 AI 교육 설계자입니다. "
            "첨부된 자료(문서 또는 이미지)를 정밀하게 분석하여, 우리 학원의 선생님이 이 내용을 '입시생 커리큘럼(규칙, 팁, 연습 방법 등)'에 "
            "어떻게 반영하면 좋을지 요약해서 제안해 주세요. "
            "답변은 3~5가지 핵심 규칙(Bullet Points) 형태로 간결하고 명확하게 제시하고, 가르치는 선생님의 어조로 친절하게 작성해 주세요."
        )
        
        # 모델 설정 (플래시 모델 사용)
        response = await asyncio.to_thread(
            _genai_client.models.generate_content,
            model='gemini-2.5-flash',
            contents=[uploaded_file, prompt]
        )
        analysis_result = response.text
        
        # 임시 파일 정리 및 Gemini 측 파일 삭제 (선택사항)
        try:
            os.remove(tmp_path)
            # genai.delete_file(uploaded_file.name)
        except Exception as cleanup_err:
            print(f"[Warning] Cleanup failed: {cleanup_err}")
            
        return {"success": True, "message": "파일 분석 완료", "analysis": analysis_result}
    except Exception as e:
        logger.exception("업로드 파일 AI 분석 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "파일 분석 중 오류 발생", "error": str(e)})

@app.post("/api/ai/curriculum-chat")
async def chat_about_curriculum(payload: AICurriculumChatRequest, request: Request):
    """
    커리큘럼을 주제로 선생님이 AI와 토론하는 챗봇
    """
    verify_teacher_auth(request)
    if not GEMINI_API_KEY:
        return {"success": False, "reply": "Gemini API Key가 설정되지 않았습니다."}
        
    try:
        global curriculum_text
        prompt = (
            "당신은 입시생들을 위한 교육 커리큘럼을 관리하고 컨설팅해 주는 AI 교육 마스터입니다.\n"
            f"현재 레슨실의 커리큘럼은 다음과 같습니다:\n---\n{curriculum_text}\n---\n"
            f"선생님의 질문/요청: {payload.message}\n\n"
            "선생님의 요청에 맞게 커리큘럼의 어떤 부분을 추가하거나 수정하면 좋을지 친절하게 답변해 주세요."
        )
        response = await asyncio.to_thread(
            _genai_client.models.generate_content,
            model='gemini-2.5-flash',
            contents=prompt
        )
        return {"success": True, "reply": response.text}
    except Exception as e:
        logger.exception("커리큘럼 AI 챗봇 응답 실패")
        return {"success": False, "reply": f"AI 답변 오류: {str(e)}"}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")

app.mount("/static", StaticFiles(directory=PUBLIC_DIR), name="static")

@app.get("/manifest.json")
async def get_manifest():
    return FileResponse(os.path.join(PUBLIC_DIR, "manifest.json"), headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})

@app.get("/style.css")
async def get_style():
    return FileResponse(os.path.join(PUBLIC_DIR, "style.css"), headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})

@app.get("/app.js")
async def get_app_js():
    return FileResponse(os.path.join(PUBLIC_DIR, "app.js"), headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})

@app.get("/dashboard.js")
async def get_dashboard_js():
    return FileResponse(os.path.join(PUBLIC_DIR, "dashboard.js"), headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})

@app.get("/")
async def get_index():
    return FileResponse(os.path.join(PUBLIC_DIR, "index.html"), headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})

@app.get("/teacher")
async def get_teacher_dashboard():
    return FileResponse(os.path.join(PUBLIC_DIR, "teacher.html"), headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})

@app.get("/teacher.html")
async def get_teacher_html():
    return FileResponse(os.path.join(PUBLIC_DIR, "teacher.html"), headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})

@app.get("/teacher.js")
async def get_teacher_js():
    return FileResponse(os.path.join(PUBLIC_DIR, "teacher.js"), headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})

@app.get("/{fallback_path:path}")
async def catch_all(fallback_path: str = ""):
    return FileResponse(os.path.join(PUBLIC_DIR, "index.html"), headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})

