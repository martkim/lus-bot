from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os
import time
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

# src.auth / src.gemini_client 등이 모듈 임포트 시점에 os.environ을 읽으므로,
# 다른 src.* 임포트보다 반드시 먼저 .env를 로드해야 한다. (안 그러면 TEACHER_PASSWORD/
# GEMINI_API_KEY가 전부 None으로 굳어버림 — 실제로 이 순서 버그로 인증이 깨졌던 걸 재현/발견함)
load_dotenv()

from src import db, background
from src.curriculum_store import load_curriculum
from src.routers import students, sessions, dashboard, qa, ai, insights, curriculum, teachers, pages

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

# 커리큘럼 캐시 로드 + DB 초기화 (앱 생성 전, 1회)
load_curriculum()
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

# ==========================================
# 라우터 등록 (Controller 계층 — src/routers/*)
# pages 라우터는 캐치올(/{fallback_path:path})을 포함하므로 반드시 마지막에 등록
# ==========================================
app.include_router(students.router)
app.include_router(sessions.router)
app.include_router(dashboard.router)
app.include_router(qa.router)
app.include_router(ai.router)
app.include_router(insights.router)
app.include_router(curriculum.router)
app.include_router(teachers.router)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
app.mount("/static", StaticFiles(directory=PUBLIC_DIR), name="static")

app.include_router(pages.router)


@app.on_event("startup")
async def startup_event():
    background.register_all()
